"""
abm_engine/channels/webhook_server.py
───────────────────────────────────────
Lightweight HTTP server that receives SendGrid event webhooks.
Handles: email opens, bounces, and REPLIES (via Inbound Parse).

Run this alongside the scheduler:
    python -m abm_engine.channels.webhook_server

Expose to internet via ngrok on laptop:
    ngrok http 8080

Then set in SendGrid:
    Settings → Mail Settings → Event Webhook → https://YOUR-NGROK-URL/webhook/sendgrid
    Settings → Inbound Parse → https://YOUR-NGROK-URL/webhook/inbound
"""
from __future__ import annotations
import os
import json
import hmac
import hashlib
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from loguru import logger
from dotenv import load_dotenv

load_dotenv()

from ..database.db    import save_engagement, mark_contact_replied
from ..core.models    import EngagementEvent
from ..workflow import sequence_engine


PORT = int(os.environ.get("WEBHOOK_PORT", 8080))


class WebhookHandler(BaseHTTPRequestHandler):
    """Handles incoming HTTP POST requests from SendGrid."""

    def log_message(self, fmt, *args):
        logger.debug("HTTP: " + fmt % args)

    def do_POST(self):
        path = urlparse(self.path).path

        # Read body
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length) if length else b""

        if path == "/webhook/sendgrid":
            self._handle_sendgrid_events(body)
        elif path == "/webhook/inbound":
            self._handle_inbound_email(body)
        elif path == "/health":
            self._ok("ok")
        else:
            self._ok("ignored")

    def _handle_sendgrid_events(self, body: bytes) -> None:
        """Process SendGrid event webhook (opens, bounces, clicks)."""
        try:
            events = json.loads(body)
            for ev in events:
                contact_id = ev.get("abm_contact_id")
                touch_num  = ev.get("abm_touch_num")
                event_type = ev.get("event", "")

                if not contact_id:
                    continue

                mapped = {
                    "open":       "email_open",
                    "bounce":     "email_bounce",
                    "spamreport": "email_spam",
                }.get(event_type)

                if mapped:
                    save_engagement(EngagementEvent(
                        contact_id  = int(contact_id),
                        event_type  = mapped,
                        raw_content = json.dumps(ev)[:500],
                        received_at = datetime.utcnow(),
                    ))
                    logger.info("Event: {} for contact {}", mapped, contact_id)

            self._ok("ok")
        except Exception as e:
            logger.error("SendGrid event webhook error: {}", e)
            self._ok("error")

    def _handle_inbound_email(self, body: bytes) -> None:
        """
        Process inbound email replies via SendGrid Inbound Parse.
        This is the HUMAN HANDOFF TRIGGER — a prospect replied.
        """
        try:
            # SendGrid Inbound Parse sends form-encoded data
            from urllib.parse import parse_qs
            data = parse_qs(body.decode("utf-8", errors="ignore"))

            sender     = data.get("from", [""])[0]
            subject    = data.get("subject", [""])[0]
            text_body  = data.get("text", [""])[0]
            headers    = data.get("headers", [""])[0]

            # Try to match sender email to a contact
            contact_id = self._find_contact_by_email(sender)

            if contact_id:
                # Record the reply
                save_engagement(EngagementEvent(
                    contact_id  = contact_id,
                    event_type  = "email_reply",
                    raw_content = text_body[:1000],
                    received_at = datetime.utcnow(),
                ))
                # Stop future outreach to this contact
                mark_contact_replied(contact_id)
                try:
                    sequence_engine.pause(contact_id, reason="replied")
                except Exception as e:
                    logger.warning("Sequence pause failed for contact {} (non-fatal): {}", contact_id, e)
                logger.info("REPLY received from {} (contact_id={})", sender, contact_id)
            else:
                logger.warning("Reply from unknown sender: {}", sender)

            self._ok("ok")
        except Exception as e:
            logger.error("Inbound email handler error: {}", e)
            self._ok("error")

    def _find_contact_by_email(self, sender_raw: str) -> int | None:
        """Extract email and look up contact in DB."""
        import re
        from ..database.db import get_conn
        # Extract email from "Name <email@domain.com>"
        match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", sender_raw)
        if not match:
            return None
        email = match.group(0).lower()
        conn  = get_conn()
        row   = conn.execute(
            "SELECT id FROM contacts WHERE LOWER(email) = ?", (email,)
        ).fetchone()
        return row["id"] if row else None

    def _ok(self, msg: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": msg}).encode())


def start_webhook_server() -> None:
    """Start the webhook receiver. Run alongside the scheduler."""
    server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
    logger.info("Webhook server listening on port {}", PORT)
    logger.info("On laptop, expose with: ngrok http {}", PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Webhook server stopped.")
