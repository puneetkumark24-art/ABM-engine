"""
abm_engine/channels/mailchimp_channel.py
──────────────────────────────────────────
Mailchimp Transactional (Mandrill) for 1:1 personalised sends.
Used for individual outreach emails from approved drafts.
Contact Bhagyam for the API key.
"""
from __future__ import annotations
import os
from loguru import logger
import httpx


class MailchimpChannel:
    """
    Sends transactional emails via Mailchimp Transactional (Mandrill API).
    Each send is a single personalised email — not a bulk campaign.
    """

    def __init__(self, api_key: str, from_email: str, from_name: str):
        self.api_key    = api_key
        self.from_email = from_email
        self.from_name  = from_name
        self.base_url   = "https://mandrillapp.com/api/1.0"

    def send(self, to_email: str, to_name: str, subject: str,
             body: str, contact_id: int, touch_num: int) -> dict:
        """
        Send a single transactional email.
        Returns: {"success": bool, "message_id": str, "error": str}
        """
        payload = {
            "key": self.api_key,
            "message": {
                "html":       body.replace("\n", "<br>"),
                "text":       body,
                "subject":    subject,
                "from_email": self.from_email,
                "from_name":  self.from_name,
                "to": [{"email": to_email, "name": to_name, "type": "to"}],
                "track_opens":  True,
                "track_clicks": False,
                "metadata": {
                    "abm_contact_id": str(contact_id),
                    "abm_touch_num":  str(touch_num),
                },
            }
        }

        try:
            with httpx.Client(timeout=20) as client:
                r = client.post(f"{self.base_url}/messages/send.json", json=payload)
            r.raise_for_status()
            result = r.json()
            if isinstance(result, list) and result:
                item     = result[0]
                msg_id   = item.get("_id","")
                status   = item.get("status","")
                if status in ("sent","queued"):
                    logger.info("Mailchimp sent to {} (touch {}) id={}", to_email, touch_num, msg_id)
                    return {"success": True, "message_id": msg_id, "error": None}
                else:
                    error = f"status={status} reject_reason={item.get('reject_reason','')}"
                    logger.warning("Mailchimp rejected: {}", error)
                    return {"success": False, "message_id": None, "error": error}
            return {"success": False, "message_id": None, "error": "Unexpected response"}
        except Exception as e:
            logger.error("Mailchimp error for {}: {}", to_email, e)
            return {"success": False, "message_id": None, "error": str(e)}


class MailchimpChannelMock:
    """Mock — logs instead of sending. Use when no API key yet."""

    def send(self, to_email, to_name, subject, body, contact_id, touch_num):
        logger.info("[MOCK Mailchimp] → {} | {}", to_email, subject[:50])
        return {"success": True, "message_id": "MOCK-MC-001", "error": None}
