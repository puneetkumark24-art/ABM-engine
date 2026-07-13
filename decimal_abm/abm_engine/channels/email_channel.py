"""
abm_engine/channels/email_channel.py
──────────────────────────────────────
Sends emails via SendGrid. Tracks opens + replies.
SendGrid is better than Mailchimp for transactional 1:1 outreach.
"""
from __future__ import annotations
import os
from loguru import logger
import sendgrid
from sendgrid.helpers.mail import Mail, Email, To, Content


class EmailChannel:
    """
    Sends a single email via SendGrid transactional API.
    Returns the SendGrid message ID for tracking.
    """

    def __init__(self, api_key: str, from_email: str, from_name: str):
        self.sg         = sendgrid.SendGridAPIClient(api_key=api_key)
        self.from_email = from_email
        self.from_name  = from_name

    def send(
        self,
        to_email:   str,
        to_name:    str,
        subject:    str,
        body:       str,
        contact_id: int,
        touch_num:  int,
    ) -> dict:
        """
        Send email. Returns:
          {"success": True,  "message_id": "...", "error": None}
          {"success": False, "message_id": None,  "error": "..."}
        """
        message = Mail(
            from_email = Email(self.from_email, self.from_name),
            to_emails  = To(to_email, to_name),
            subject    = subject,
        )

        # Plain text content
        message.content = [Content("text/plain", body)]

        # Custom args for webhook tracking (SendGrid Event Webhook)
        message.custom_args = {
            "abm_contact_id": str(contact_id),
            "abm_touch_num":  str(touch_num),
        }

        # Enable open tracking
        message.tracking_settings = {
            "click_tracking":    {"enable": False},
            "open_tracking":     {"enable": True},
        }

        try:
            response = self.sg.send(message)
            msg_id   = response.headers.get("X-Message-Id", "")
            logger.info(
                "Email sent to {} (touch {}) | status: {} | id: {}",
                to_email, touch_num, response.status_code, msg_id
            )
            return {"success": True, "message_id": msg_id, "error": None}

        except Exception as e:
            logger.error("SendGrid error for {}: {}", to_email, e)
            return {"success": False, "message_id": None, "error": str(e)}


# ─── SendGrid Webhook Handler ─────────────────────────────────────────────────
# Add this to a simple Flask/FastAPI server to receive open + reply events.
# See channels/webhook_server.py for the full implementation.

SENDGRID_EVENTS = {
    "open":       "email_open",
    "click":      "email_click",
    "bounce":     "email_bounce",
    "spamreport": "email_spam",
    # "inbound_parse" for replies — configure in SendGrid dashboard:
    # Settings → Inbound Parse → add your domain's MX record
}
