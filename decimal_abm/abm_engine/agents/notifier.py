"""
abm_engine/agents/notifier.py
──────────────────────────────
Human handoff notifier — fires when a prospect replies.
Two channels:
  1. WhatsApp (via Twilio) — instant mobile alert
  2. Email (via SendGrid) — full context with reply text

No Slack. Nothing else needed.
"""
from __future__ import annotations
import os
import httpx
from loguru import logger


class NotifierAgent:
    """
    Sends WhatsApp + email alerts when a prospect replies.
    Human only steps in after receiving this alert.
    """

    def __init__(
        self,
        # Twilio (WhatsApp)
        twilio_account_sid: str = "",
        twilio_auth_token:  str = "",
        twilio_from_whatsapp: str = "",   # e.g. "whatsapp:+14155238886"
        alert_to_whatsapp:  str = "",     # e.g. "whatsapp:+919XXXXXXXXX"
        # SendGrid (email alert)
        sendgrid_api_key:   str = "",
        alert_from_email:   str = "",
        alert_to_email:     str = "",     # your personal email
        alert_from_name:    str = "Decimal ABM Engine",
    ):
        self.twilio_sid          = twilio_account_sid
        self.twilio_token        = twilio_auth_token
        self.twilio_from_wa      = twilio_from_whatsapp
        self.alert_to_wa         = alert_to_whatsapp
        self.sg_key              = sendgrid_api_key
        self.alert_from_email    = alert_from_email
        self.alert_to_email      = alert_to_email
        self.alert_from_name     = alert_from_name

    # ─── Main alert ───────────────────────────────────────────────────────────

    def reply_received(
        self,
        contact_name:  str,
        institution:   str,
        role:          str,
        touch_number:  int,
        channel:       str,        # "email" or "linkedin"
        reply_snippet: str,
        hubspot_url:   str = "",
    ) -> None:
        """
        Fire both alerts. Called the moment a prospect replies.
        Engine has already paused outreach to this contact.
        """
        self._send_whatsapp(
            contact_name  = contact_name,
            institution   = institution,
            role          = role,
            touch_number  = touch_number,
            channel       = channel,
            reply_snippet = reply_snippet,
            hubspot_url   = hubspot_url,
        )
        self._send_email_alert(
            contact_name  = contact_name,
            institution   = institution,
            role          = role,
            touch_number  = touch_number,
            channel       = channel,
            reply_snippet = reply_snippet,
            hubspot_url   = hubspot_url,
        )
        logger.info(
            "REPLY ALERTS sent (WhatsApp + Email) for {} @ {} (touch {}, {})",
            contact_name, institution, touch_number, channel
        )

    # ─── WhatsApp via Twilio ─────────────────────────────────────────────────

    def _send_whatsapp(
        self,
        contact_name: str,
        institution:  str,
        role:         str,
        touch_number: int,
        channel:      str,
        reply_snippet: str,
        hubspot_url:  str,
    ) -> None:
        if not all([self.twilio_sid, self.twilio_token, self.twilio_from_wa, self.alert_to_wa]):
            logger.debug("[WhatsApp mock] Reply from {} @ {}", contact_name, institution)
            return

        # Keep WhatsApp message tight — this is a mobile ping
        snippet_short = reply_snippet[:200].strip()
        if len(reply_snippet) > 200:
            snippet_short += "..."

        body = (
            f"🔔 *Prospect Replied* — Action needed\n\n"
            f"*Who:* {contact_name}\n"
            f"*At:* {institution}\n"
            f"*Role:* {role}\n"
            f"*Channel:* {channel.upper()} · Touch {touch_number}\n\n"
            f"*Their message:*\n{snippet_short}\n\n"
            f"⚡ Outreach paused. Reply within 2 hrs."
        )
        if hubspot_url:
            body += f"\n\n🔗 {hubspot_url}"

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
        try:
            with httpx.Client(timeout=15) as client:
                r = client.post(
                    url,
                    data={
                        "From": self.twilio_from_wa,
                        "To":   self.alert_to_wa,
                        "Body": body,
                    },
                    auth=(self.twilio_sid, self.twilio_token),
                )
            if r.status_code in (200, 201):
                logger.info("WhatsApp alert sent to {}", self.alert_to_wa)
            else:
                logger.warning("WhatsApp alert failed: {} — {}", r.status_code, r.text[:200])
        except Exception as e:
            logger.error("WhatsApp alert exception: {}", e)

    # ─── Email alert via SendGrid ────────────────────────────────────────────

    def _send_email_alert(
        self,
        contact_name: str,
        institution:  str,
        role:         str,
        touch_number: int,
        channel:      str,
        reply_snippet: str,
        hubspot_url:  str,
    ) -> None:
        if not all([self.sg_key, self.alert_from_email, self.alert_to_email]):
            logger.debug("[Email alert mock] Reply from {} @ {}", contact_name, institution)
            return

        subject = f"🔔 {contact_name} @ {institution} replied — respond now"

        html_body = f"""
<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;">
  <div style="background:#0F6E56;padding:16px 24px;border-radius:8px 8px 0 0;">
    <h2 style="color:white;margin:0;font-size:18px;">Prospect Replied — Action Required</h2>
  </div>
  <div style="border:1px solid #e0e0e0;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
    <table style="width:100%;border-collapse:collapse;margin-bottom:20px;">
      <tr><td style="color:#666;padding:6px 0;width:100px;font-size:14px;">Who</td>
          <td style="font-weight:600;font-size:14px;">{contact_name}</td></tr>
      <tr><td style="color:#666;padding:6px 0;font-size:14px;">Institution</td>
          <td style="font-size:14px;">{institution}</td></tr>
      <tr><td style="color:#666;padding:6px 0;font-size:14px;">Role</td>
          <td style="font-size:14px;">{role}</td></tr>
      <tr><td style="color:#666;padding:6px 0;font-size:14px;">Channel</td>
          <td style="font-size:14px;">{channel.upper()} · Touch {touch_number}</td></tr>
    </table>
    <div style="background:#f5f5f5;border-left:4px solid #0F6E56;padding:12px 16px;border-radius:4px;margin-bottom:20px;">
      <p style="color:#333;font-size:14px;margin:0;white-space:pre-wrap;">{reply_snippet[:800]}</p>
    </div>
    <p style="background:#FFF8E1;border:1px solid #FFE082;padding:12px;border-radius:4px;
              font-size:13px;color:#795548;margin-bottom:20px;">
      ⚡ ABM engine has <strong>paused outreach</strong> for this contact.
      Respond within 2 business hours for best conversion.
    </p>
    {"<a href='" + hubspot_url + "' style='display:inline-block;background:#0F6E56;color:white;" +
     "padding:10px 20px;border-radius:6px;text-decoration:none;font-size:14px;'>Open in HubSpot</a>"
     if hubspot_url else ""}
  </div>
  <p style="color:#aaa;font-size:12px;text-align:center;margin-top:12px;">Decimal ABM Engine</p>
</div>
"""
        text_body = (
            f"PROSPECT REPLIED — Action Required\n\n"
            f"Who: {contact_name}\n"
            f"Institution: {institution}\n"
            f"Role: {role}\n"
            f"Channel: {channel.upper()} · Touch {touch_number}\n\n"
            f"Their message:\n{reply_snippet[:800]}\n\n"
            f"Outreach paused. Respond within 2 hours.\n"
            + (f"\nHubSpot: {hubspot_url}" if hubspot_url else "")
        )

        url = "https://api.sendgrid.com/v3/mail/send"
        payload = {
            "personalizations": [{"to": [{"email": self.alert_to_email}]}],
            "from": {"email": self.alert_from_email, "name": self.alert_from_name},
            "subject": subject,
            "content": [
                {"type": "text/plain", "value": text_body},
                {"type": "text/html",  "value": html_body},
            ],
        }
        try:
            with httpx.Client(timeout=15) as client:
                r = client.post(
                    url,
                    json    = payload,
                    headers = {
                        "Authorization": f"Bearer {self.sg_key}",
                        "Content-Type":  "application/json",
                    },
                )
            if r.status_code in (200, 202):
                logger.info("Email alert sent to {}", self.alert_to_email)
            else:
                logger.warning("Email alert failed: {} — {}", r.status_code, r.text[:200])
        except Exception as e:
            logger.error("Email alert exception: {}", e)

    # ─── Engine-level notifications ───────────────────────────────────────────

    def engine_run_complete(self, sent: int, skipped: int, errors: int) -> None:
        """Daily summary — WhatsApp only (short message)."""
        if not all([self.twilio_sid, self.twilio_token, self.twilio_from_wa, self.alert_to_wa]):
            logger.info("[Daily summary mock] Sent:{} Skipped:{} Errors:{}", sent, skipped, errors)
            return

        body = (
            f"✅ ABM Engine — Daily Run Done\n"
            f"Sent: {sent} | Skipped: {skipped} | Errors: {errors}"
        )
        try:
            url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
            with httpx.Client(timeout=15) as client:
                client.post(
                    url,
                    data={"From": self.twilio_from_wa, "To": self.alert_to_wa, "Body": body},
                    auth=(self.twilio_sid, self.twilio_token),
                )
        except Exception as e:
            logger.error("Daily summary WhatsApp failed: {}", e)

    def engine_error(self, error: str) -> None:
        """Alert on engine crash — both channels."""
        msg = f"🚨 ABM Engine Error\n\n{error[:400]}"

        # WhatsApp
        if all([self.twilio_sid, self.twilio_token, self.twilio_from_wa, self.alert_to_wa]):
            try:
                url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
                with httpx.Client(timeout=15) as client:
                    client.post(
                        url,
                        data={"From": self.twilio_from_wa, "To": self.alert_to_wa, "Body": msg},
                        auth=(self.twilio_sid, self.twilio_token),
                    )
            except Exception as e:
                logger.error("Error alert WhatsApp failed: {}", e)
        else:
            logger.error("[Engine error mock]: {}", error)
