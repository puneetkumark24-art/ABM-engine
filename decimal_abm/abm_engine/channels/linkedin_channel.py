"""
abm_engine/channels/linkedin_channel.py
─────────────────────────────────────────
Sends LinkedIn messages via Heyreach API.
Touch 1 = connection request note (280 chars)
Touch 2-5 = InMail / DM after connected
"""
from __future__ import annotations
import os
import httpx
from loguru import logger


HEYREACH_BASE = "https://api.heyreach.io/api/public"


class LinkedInChannel:
    """
    Wraps the Heyreach API for LinkedIn outreach automation.
    Requires a Heyreach account with a LinkedIn profile connected.
    """

    def __init__(self, api_key: str, campaign_id: str):
        self.api_key     = api_key
        self.campaign_id = campaign_id
        self.headers     = {
            "X-API-KEY":    api_key,
            "Content-Type": "application/json",
        }

    def add_to_campaign(
        self,
        linkedin_url: str,
        contact_name: str,
        message:      str,
        touch_num:    int,
    ) -> dict:
        """
        Add a contact to a Heyreach campaign.
        Touch 1 → connection request with note
        Touch 2+ → follow-up DM
        Returns: {"success": bool, "heyreach_id": str, "error": str}
        """
        if not linkedin_url:
            return {"success": False, "heyreach_id": None, "error": "No LinkedIn URL"}

        endpoint = f"{HEYREACH_BASE}/campaign/{self.campaign_id}/add-leads"

        payload = {
            "leads": [
                {
                    "linkedinUrl":       linkedin_url,
                    "firstName":         contact_name.split()[0],
                    "customVariables":   {"message": message},
                    "connectionMessage": message if touch_num == 1 else "",
                }
            ]
        }

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    endpoint,
                    json    = payload,
                    headers = self.headers,
                )

            if response.status_code in (200, 201):
                data = response.json()
                lead_id = data.get("leads", [{}])[0].get("id", "")
                logger.info(
                    "LinkedIn touch {} queued for {} | id: {}",
                    touch_num, contact_name, lead_id
                )
                return {"success": True, "heyreach_id": str(lead_id), "error": None}
            else:
                error = f"HTTP {response.status_code}: {response.text[:200]}"
                logger.error("Heyreach error for {}: {}", contact_name, error)
                return {"success": False, "heyreach_id": None, "error": error}

        except Exception as e:
            logger.error("Heyreach exception for {}: {}", contact_name, e)
            return {"success": False, "heyreach_id": None, "error": str(e)}

    def send_followup_dm(
        self,
        linkedin_url: str,
        contact_name: str,
        message:      str,
    ) -> dict:
        """
        Send a direct message to an already-connected contact via Heyreach.
        Used for touch 2–5 if they connected but didn't reply.
        """
        endpoint = f"{HEYREACH_BASE}/message/send"
        payload  = {
            "linkedinUrl": linkedin_url,
            "message":     message,
        }

        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    endpoint,
                    json    = payload,
                    headers = self.headers,
                )

            if response.status_code in (200, 201):
                logger.info("LinkedIn DM sent to {}", contact_name)
                return {"success": True, "heyreach_id": None, "error": None}
            else:
                error = f"HTTP {response.status_code}: {response.text[:200]}"
                return {"success": False, "heyreach_id": None, "error": error}

        except Exception as e:
            return {"success": False, "heyreach_id": None, "error": str(e)}


# ─── Mock for development (no Heyreach key yet) ───────────────────────────────

class LinkedInChannelMock:
    """
    Use this when you don't have a Heyreach key yet.
    Logs the message instead of sending — so you can review all output.
    """

    def add_to_campaign(self, linkedin_url, contact_name, message, touch_num):
        logger.info(
            "[MOCK LinkedIn T{}] {} | {}\n{}",
            touch_num, contact_name, linkedin_url, message
        )
        return {"success": True, "heyreach_id": "MOCK-001", "error": None}

    def send_followup_dm(self, linkedin_url, contact_name, message):
        logger.info("[MOCK LinkedIn DM] {} | {}\n{}", contact_name, linkedin_url, message)
        return {"success": True, "heyreach_id": None, "error": None}
