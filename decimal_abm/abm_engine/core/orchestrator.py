"""
abm_engine/core/orchestrator.py
────────────────────────────────
Two-phase pipeline:

Phase 1 (automatic, runs daily):
  Research → Write → Save as DRAFT → stop
  Human reviews drafts in dashboard → approves/rejects/edits

Phase 2 (runs every 30 min, sends approved drafts):
  Load APPROVED drafts → Send via Mailchimp/SendGrid/Heyreach → Log to HubSpot
"""
from __future__ import annotations
import os
import time
from datetime import datetime
from loguru import logger

from .models import Contact, TouchRecord, TouchType, TouchStatus, Language
from ..database import db
from ..agents.researcher import ResearchAgent
from ..agents.writer     import WriterAgent
from ..agents.notifier   import NotifierAgent
from ..channels.email_channel     import EmailChannel
from ..channels.mailchimp_channel import MailchimpChannel, MailchimpChannelMock
from ..channels.linkedin_channel  import LinkedInChannel, LinkedInChannelMock
from ..channels.hubspot_channel   import HubSpotChannel, HubSpotChannelMock
from ..workflow import sequence_engine
from ..workflow.send_window import is_within_send_window


def _make_notifier() -> NotifierAgent:
    return NotifierAgent(
        twilio_account_sid    = os.environ.get("TWILIO_ACCOUNT_SID",""),
        twilio_auth_token     = os.environ.get("TWILIO_AUTH_TOKEN",""),
        twilio_from_whatsapp  = os.environ.get("TWILIO_FROM_WHATSAPP",""),
        alert_to_whatsapp     = os.environ.get("ALERT_TO_WHATSAPP",""),
        sendgrid_api_key      = os.environ.get("SENDGRID_API_KEY",""),
        alert_from_email      = os.environ.get("SENDGRID_FROM_EMAIL",""),
        alert_to_email        = os.environ.get("ALERT_TO_EMAIL",""),
        alert_from_name       = "Decimal ABM Engine",
    )


class Orchestrator:
    def __init__(self):
        api_key = os.environ["ANTHROPIC_API_KEY"]

        self.researcher  = ResearchAgent(api_key=api_key)
        self.writer      = WriterAgent(api_key=api_key)
        self.notifier    = _make_notifier()
        self.daily_limit = int(os.environ.get("OUTREACH_DAILY_LIMIT", 20))
        self.delay_secs  = int(os.environ.get("OUTREACH_DELAY_SECONDS", 15))

        # Mailchimp (campaigns/sequences)
        mc_key = os.environ.get("MAILCHIMP_API_KEY","")
        self.mailchimp_ch = MailchimpChannel(
            api_key    = mc_key,
            from_email = os.environ.get("SENDGRID_FROM_EMAIL",""),
            from_name  = os.environ.get("SENDGRID_FROM_NAME","Decimal Technologies"),
        ) if mc_key else MailchimpChannelMock()

        # SendGrid (individual 1:1)
        sg_key = os.environ.get("SENDGRID_API_KEY","")
        self.email_ch = EmailChannel(
            api_key    = sg_key,
            from_email = os.environ.get("SENDGRID_FROM_EMAIL",""),
            from_name  = os.environ.get("SENDGRID_FROM_NAME","Decimal Technologies"),
        ) if sg_key else None

        # LinkedIn
        hr_key, hr_camp = os.environ.get("HEYREACH_API_KEY",""), os.environ.get("HEYREACH_CAMPAIGN_ID","")
        self.linkedin_ch = LinkedInChannel(api_key=hr_key, campaign_id=hr_camp) \
            if (hr_key and hr_camp) else LinkedInChannelMock()

        # HubSpot
        hs_key = os.environ.get("HUBSPOT_API_KEY","")
        self.hubspot_ch = HubSpotChannel(api_key=hs_key) if hs_key else HubSpotChannelMock()

    # ── Phase 1: Generate drafts ──────────────────────────────────────────────

    def generate_drafts(self) -> dict:
        """
        For each contact due for outreach:
        Research → Write → Save as DRAFT (status=DRAFT).
        Does NOT send anything. Human reviews drafts in dashboard.
        """
        logger.info("═══ Draft Generation Started ═══")
        try:
            rows = sequence_engine.get_contacts_due(limit=self.daily_limit)
        except Exception as e:
            logger.error("Sequence engine unavailable ({}), falling back to legacy cadence", e)
            rows = db.get_contacts_due_for_outreach(limit=self.daily_limit)
        logger.info("{} contacts due for draft generation", len(rows))

        generated = skipped = errors = 0

        for row in rows:
            contact = self._row_to_contact(row)
            try:
                result = self._generate_for_contact(contact)
                generated += result == "generated"
                skipped   += result == "skipped"
                time.sleep(self.delay_secs)
            except Exception as e:
                errors += 1
                logger.error("Draft gen error for {}: {}", contact.full_name, e)

        summary = {"generated": generated, "skipped": skipped, "errors": errors}
        logger.info("═══ Draft Generation Complete: {} ═══", summary)
        self.notifier.engine_run_complete(
            sent=0, skipped=skipped, errors=errors
        )
        return summary

    def _generate_for_contact(self, contact: Contact) -> str:
        touch_num = (contact.current_touch or 0) + 1
        logger.info("Generating draft: {} @ {} | T{} | {} | {}",
            contact.full_name, contact.institution, touch_num,
            contact.tier, contact.relationship_type)

        if contact.replied:
            return "skipped"

        has_email    = bool(contact.email)
        has_linkedin = bool(contact.linkedin_url)
        if not has_email and not has_linkedin:
            return "skipped"

        # Research
        research = self.researcher.research_contact(contact)

        # Write email
        if has_email:
            email_msg = self.writer.generate_email(contact, research, touch_num)
            body_ar   = None
            if contact.needs_arabic and touch_num in (1, 4):
                try:
                    ar_msg  = self.writer._call(
                        f"Translate to formal MSA Arabic for senior KSA banking executive:\n\n"
                        f"Subject: {email_msg.subject}\n\n{email_msg.body}"
                    )
                    body_ar = ar_msg
                except Exception:
                    pass

            db.save_draft(
                contact_id   = contact.id,
                touch_number = touch_num,
                touch_type   = "EMAIL",
                language     = "EN",
                subject      = email_msg.subject or f"Decimal × {contact.institution}",
                body_en      = email_msg.body,
                body_ar      = body_ar,
                hook_used    = research.recommended_hook,
            )
            logger.info("Email draft saved for {} (T{})", contact.full_name, touch_num)

        # Write LinkedIn
        if has_linkedin:
            li_msg = self.writer.generate_linkedin_dm(contact, research, touch_num)
            db.save_draft(
                contact_id   = contact.id,
                touch_number = touch_num,
                touch_type   = "LINKEDIN",
                language     = "EN",
                subject      = None,
                body_en      = li_msg.body,
                body_ar      = None,
                hook_used    = research.recommended_hook,
            )
            logger.info("LinkedIn draft saved for {} (T{})", contact.full_name, touch_num)

        # Don't increment touch yet — only after send
        return "generated"

    # ── Phase 2: Send approved drafts ────────────────────────────────────────

    def send_approved_drafts(self) -> dict:
        """
        Sends all APPROVED drafts that haven't been sent yet.
        Runs every 30 minutes automatically.

        Gated by the KSA send window (T-TIME-2 in Build Artifact 3): outside
        business hours, on the Fri/Sat weekend, or on a configured blackout
        date, this returns immediately and sends nothing. Approved drafts
        stay APPROVED and unsent — they go out on the next in-window tick,
        they are never dropped or marked failed.
        """
        allowed, reason = is_within_send_window()
        if not allowed:
            logger.info("Send window closed ({}) — skipping this cycle", reason)
            return {"sent": 0, "skipped_window": reason}

        approved = db.get_approved_unsent_drafts()
        if not approved:
            return {"sent": 0}

        logger.info("Sending {} approved drafts", len(approved))
        sent = errors = 0

        for draft in approved:
            try:
                self._send_draft(draft)
                sent += 1
                time.sleep(5)
            except Exception as e:
                errors += 1
                logger.error("Send error for draft {}: {}", draft["id"], e)

        return {"sent": sent, "errors": errors}

    def _send_draft(self, draft: dict) -> None:
        contact_id  = draft["contact_id"]
        contact_row = db.get_contact_by_id(contact_id)
        if not contact_row:
            return

        # Ensure HubSpot contact exists
        if not contact_row.get("hubspot_contact_id") and contact_row.get("email"):
            hs_id = self.hubspot_ch.upsert_contact(
                email        = contact_row["email"],
                full_name    = contact_row["full_name"],
                role         = contact_row["role"],
                institution  = contact_row["institution"],
                country      = contact_row.get("country","Saudi Arabia"),
                score        = contact_row.get("priority_score",0),
                tier         = contact_row.get("tier","COLD"),
            )
            if hs_id:
                db.update_hubspot_id(contact_id, hs_id)
                contact_row["hubspot_contact_id"] = hs_id

        if draft["touch_type"] == "EMAIL" and contact_row.get("email"):
            self._send_email_draft(draft, contact_row)
        elif draft["touch_type"] == "LINKEDIN" and contact_row.get("linkedin_url"):
            self._send_linkedin_draft(draft, contact_row)

        # Increment touch counter after successful send
        db.increment_touch(contact_id)
        try:
            sequence_engine.advance(contact_id)
        except Exception as e:
            logger.warning("Sequence advance failed for contact {} (non-fatal): {}", contact_id, e)

    def _send_email_draft(self, draft: dict, contact: dict) -> None:
        """
        Use Mailchimp for transactional 1:1 sends.
        Falls back to SendGrid if Mailchimp unavailable.
        """
        body    = draft["body_en"]
        subject = draft["subject"] or f"Decimal × {contact['institution']}"

        result = self.mailchimp_ch.send(
            to_email   = contact["email"],
            to_name    = contact["full_name"],
            subject    = subject,
            body       = body,
            contact_id = contact["id"],
            touch_num  = draft["touch_number"],
        )

        mc_id = result.get("message_id") if result["success"] else None

        # If Mailchimp mock, try SendGrid
        if not result["success"] and self.email_ch:
            result = self.email_ch.send(
                to_email   = contact["email"],
                to_name    = contact["full_name"],
                subject    = subject,
                body       = body,
                contact_id = contact["id"],
                touch_num  = draft["touch_number"],
            )

        db.mark_draft_sent(
            draft["id"],
            mailchimp_id = mc_id,
            sendgrid_id  = result.get("message_id") if not mc_id else None,
        )

        # Log to HubSpot
        if contact.get("hubspot_contact_id"):
            hs_note = self.hubspot_ch.log_email_sent(
                hubspot_contact_id = contact["hubspot_contact_id"],
                subject=subject, body=body,
                touch_number=draft["touch_number"],
                institution=contact["institution"],
            )
            db.mark_draft_sent(draft["id"], hubspot_id=hs_note)

        logger.info("Email sent: {} T{}", contact["full_name"], draft["touch_number"])

    def _send_linkedin_draft(self, draft: dict, contact: dict) -> None:
        result = self.linkedin_ch.add_to_campaign(
            linkedin_url = contact["linkedin_url"],
            contact_name = contact["full_name"],
            message      = draft["body_en"],
            touch_num    = draft["touch_number"],
        )
        db.mark_draft_sent(draft["id"], heyreach_id=result.get("heyreach_id"))

        if contact.get("hubspot_contact_id"):
            self.hubspot_ch.log_linkedin_touch(
                hubspot_contact_id = contact["hubspot_contact_id"],
                message=draft["body_en"],
                touch_number=draft["touch_number"],
            )
        logger.info("LinkedIn sent: {} T{}", contact["full_name"], draft["touch_number"])

    @staticmethod
    def _row_to_contact(row: dict) -> Contact:
        return Contact(
            id                    = row["id"],
            account_id            = row.get("account_id"),
            full_name             = row["full_name"],
            role                  = row.get("role",""),
            persona               = row.get("persona","OTHER"),
            seniority             = row.get("seniority","VP"),
            is_ksa_national       = bool(row.get("is_ksa_national",0)),
            relationship_type     = row.get("relationship_type","TARGET"),
            institution           = row["institution"],
            country               = row.get("country","Saudi Arabia"),
            institution_type      = row.get("institution_type","Bank"),
            segment               = row.get("segment","COMMERCIAL"),
            email                 = row.get("email"),
            email_confidence      = row.get("email_confidence"),
            linkedin_url          = row.get("linkedin_url"),
            whatsapp              = row.get("whatsapp"),
            phone                 = row.get("phone"),
            phone_status          = row.get("phone_status"),
            key_signal            = row.get("key_signal",""),
            outreach_angle        = row.get("outreach_angle",""),
            product_fit           = row.get("product_fit",""),
            warmness              = row.get("warmness","Cold"),
            has_warm_relationship = bool(row.get("has_warm_relationship",0)),
            background_notes      = row.get("background_notes"),
            pitch_notes           = row.get("pitch_notes"),
            connection_paths      = row.get("connection_paths"),
            priority_score        = row.get("priority_score",0),
            tier                  = row.get("tier","COLD"),
            hubspot_contact_id    = row.get("hubspot_contact_id"),
            current_touch         = row.get("current_touch",0),
            is_active             = bool(row.get("is_active",1)),
            replied               = bool(row.get("replied",0)),
            reply_handled         = bool(row.get("reply_handled",0)),
        )
