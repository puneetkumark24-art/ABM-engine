"""
abm_engine/channels/hubspot_channel.py
────────────────────────────────────────
Logs every action to HubSpot:
- Creates/updates contacts
- Logs email sent as an engagement
- Updates deal pipeline stage when contact replies
"""
from __future__ import annotations
from datetime import datetime
from loguru import logger
import httpx


HUBSPOT_BASE = "https://api.hubapi.com"


class HubSpotChannel:
    """
    Direct HubSpot v3 API integration.
    No SDK needed — cleaner and easier to debug.
    """

    def __init__(self, api_key: str):
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"{HUBSPOT_BASE}{endpoint}"
        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(url, json=payload, headers=self.headers)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            logger.error("HubSpot HTTP error {}: {}", e.response.status_code, e.response.text[:300])
            raise
        except Exception as e:
            logger.error("HubSpot error: {}", e)
            raise

    def _patch(self, endpoint: str, payload: dict) -> dict:
        url = f"{HUBSPOT_BASE}{endpoint}"
        with httpx.Client(timeout=20) as client:
            r = client.patch(url, json=payload, headers=self.headers)
        r.raise_for_status()
        return r.json()

    def _search(self, object_type: str, filter_group: dict) -> list[dict]:
        url     = f"{HUBSPOT_BASE}/crm/v3/objects/{object_type}/search"
        payload = {"filterGroups": [filter_group], "limit": 1}
        with httpx.Client(timeout=20) as client:
            r = client.post(url, json=payload, headers=self.headers)
        if r.status_code == 200:
            return r.json().get("results", [])
        return []

    # ─── Contact management ───────────────────────────────────────────────────

    def upsert_contact(
        self,
        email:       str,
        full_name:   str,
        role:        str,
        institution: str,
        country:     str,
        score:       int,
        tier:        str,
    ) -> str:
        """
        Create contact if not exists, update if exists.
        Returns HubSpot contact ID.
        """
        # Search by email
        existing = self._search(
            "contacts",
            {"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}
        )

        properties = {
            "email":     email,
            "firstname": full_name.split()[0],
            "lastname":  " ".join(full_name.split()[1:]),
            "jobtitle":  role,
            "company":   institution,
            "country":   country,
            "hs_lead_status": "IN_PROGRESS",
            # Custom properties (add these in HubSpot Settings → Properties)
            "abm_priority_score": str(score),
            "abm_tier":           tier,
        }

        try:
            if existing:
                contact_id = existing[0]["id"]
                self._patch(f"/crm/v3/objects/contacts/{contact_id}", {"properties": properties})
                logger.debug("HubSpot contact updated: {} ({})", full_name, contact_id)
            else:
                result     = self._post("/crm/v3/objects/contacts", {"properties": properties})
                contact_id = result["id"]
                logger.info("HubSpot contact created: {} ({})", full_name, contact_id)

            return contact_id

        except Exception as e:
            logger.error("HubSpot upsert_contact failed for {}: {}", full_name, e)
            return ""

    # ─── Engagement logging ───────────────────────────────────────────────────

    def log_email_sent(
        self,
        hubspot_contact_id: str,
        subject:            str,
        body:               str,
        touch_number:       int,
        institution:        str,
    ) -> str:
        """Log an outbound email as an engagement note."""
        note_body = (
            f"ABM Touch {touch_number} — EMAIL SENT\n"
            f"Institution: {institution}\n"
            f"Subject: {subject}\n\n"
            f"{body[:500]}{'...' if len(body) > 500 else ''}"
        )

        try:
            result = self._post("/crm/v3/objects/notes", {
                "properties": {
                    "hs_note_body":     note_body,
                    "hs_timestamp":     str(int(datetime.utcnow().timestamp() * 1000)),
                    "hs_attachment_ids": "",
                },
                "associations": [
                    {
                        "to":   {"id": hubspot_contact_id},
                        "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]
                    }
                ]
            })
            logger.debug("HubSpot note logged for contact {}", hubspot_contact_id)
            return result.get("id", "")

        except Exception as e:
            logger.error("HubSpot log_email_sent failed: {}", e)
            return ""

    def log_linkedin_touch(
        self,
        hubspot_contact_id: str,
        message:            str,
        touch_number:       int,
    ) -> str:
        """Log a LinkedIn touch as a note."""
        note_body = (
            f"ABM Touch {touch_number} — LINKEDIN\n\n"
            f"{message}"
        )
        try:
            result = self._post("/crm/v3/objects/notes", {
                "properties": {
                    "hs_note_body": note_body,
                    "hs_timestamp": str(int(datetime.utcnow().timestamp() * 1000)),
                },
                "associations": [
                    {
                        "to":    {"id": hubspot_contact_id},
                        "types": [{"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": 202}]
                    }
                ]
            })
            return result.get("id", "")
        except Exception as e:
            logger.error("HubSpot log_linkedin_touch failed: {}", e)
            return ""

    def mark_replied(self, hubspot_contact_id: str, contact_name: str) -> None:
        """Update contact status when they reply — triggers human handoff."""
        try:
            self._patch(f"/crm/v3/objects/contacts/{hubspot_contact_id}", {
                "properties": {
                    "hs_lead_status": "OPEN_DEAL",
                    "abm_replied":    "true",
                }
            })
            logger.info("HubSpot: {} marked as replied / OPEN_DEAL", contact_name)
        except Exception as e:
            logger.error("HubSpot mark_replied failed: {}", e)


# ─── Mock for development ─────────────────────────────────────────────────────

class HubSpotChannelMock:
    """Use when no HubSpot key is available yet."""

    def upsert_contact(self, **kwargs) -> str:
        logger.info("[MOCK HubSpot] Upsert contact: {}", kwargs.get("full_name"))
        return "MOCK-HS-001"

    def log_email_sent(self, **kwargs) -> str:
        logger.info("[MOCK HubSpot] Log email: touch {}", kwargs.get("touch_number"))
        return "MOCK-NOTE-001"

    def log_linkedin_touch(self, **kwargs) -> str:
        logger.info("[MOCK HubSpot] Log LinkedIn: touch {}", kwargs.get("touch_number"))
        return "MOCK-NOTE-002"

    def mark_replied(self, hubspot_contact_id: str, contact_name: str) -> None:
        logger.info("[MOCK HubSpot] Mark replied: {}", contact_name)
