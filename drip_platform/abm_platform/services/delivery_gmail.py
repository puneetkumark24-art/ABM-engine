"""Google Workspace / Microsoft 365 transport adapters.

WHY THIS EXISTS — please read before enabling SES
--------------------------------------------------
`deliverability.py` currently encodes Amazon SES as "the intended first
adapter (cost + deliverability)", and `delivery_ext.py` ships SES and Mandrill
adapters. For *transactional* mail that recommendation is sound. For the cold
1:1 B2B outreach this platform actually runs, it is an acceptable-use problem:

    Amazon SES, Mandrill/Mailchimp Transactional, SendGrid, Mailgun, Postmark
    and Resend all prohibit unsolicited/cold outreach in their AUPs.

The reason is structural, not bureaucratic: they route through shared IP pools
where one tenant's complaint rate degrades every other tenant's reputation, so
they police it hard. SendGrid was already flagged as an AUP violation earlier
in this project's history. Enabling SES for cold KSA bank outreach invites the
same outcome — account termination, usually mid-campaign, taking the sending
domain's reputation with it.

The sanctioned path for 1:1 cold outreach is a real mailbox on a real domain:
Google Workspace or Microsoft 365. It is also the better-performing one for
B2B recipients, because the mail is genuinely person-to-person rather than
bulk-shaped.

WHAT THIS CHANGES ELSEWHERE: nothing. Same `register_transport()` seam, same
`can_send()` volume gate, same warmup ladder, same suppression checks. The
deliverability engine does not care which adapter is registered.

TRADE-OFF YOU ARE ACCEPTING
---------------------------
Workspace gives no webhooks and no feedback loops. Bounces arrive as DSN mail
and replies arrive as replies — which is why `inbound.py` polls the mailbox
instead of waiting for a callback. That also removes the public-HTTPS
dependency PHASE_11 flagged as the open deployment decision, at least for
bounce and reply capture. The `/t/*` pixel and click endpoints still need a
public host if you want open/click tracking.

VOLUME REALITY
--------------
Workspace's technical ceiling is ~2,000 recipients/day. Do not aim near it.
The `WARMUP_CAPS` ladder in deliverability.py tops out at 100,000/day, which is
right for SES and wrong for a Workspace mailbox doing cold outreach — cap the
domain at a stage appropriate to ~40-50/day/mailbox and let reputation, not
the ceiling, govern.
"""
from __future__ import annotations

import base64
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import models_ext as mx
from . import delivery

GMAIL_ENV_FLAG = "ENABLE_GMAIL_TRANSPORT"      # must be "true"
GMAIL_USER_ENV = "GMAIL_SEND_AS"               # e.g. puneet@outreach.example.com
GMAIL_CREDS_ENV = "GMAIL_CREDENTIALS_FILE"     # service-account JSON, DWD-enabled

M365_ENV_FLAG = "ENABLE_M365_TRANSPORT"
M365_USER_ENV = "M365_SEND_AS"
M365_TENANT_ENV = "M365_TENANT_ID"
M365_CLIENT_ENV = "M365_CLIENT_ID"
M365_SECRET_ENV = "M365_CLIENT_SECRET"


def _build_mime(req: "mx.SendRequest", from_addr: str) -> MIMEMultipart:
    """multipart/alternative with a real text/plain part.

    An HTML-only body is itself a spam signal, and the plain-text part is what
    several filters actually score. No tracking pixel and no link rewriting are
    added here: on 1:1 cold outreach both make a personal email look like bulk.
    Open/click tracking, if wanted, is applied upstream by
    `tracking.prepare_email()` — that is a deliberate per-campaign choice, not
    a transport default.
    """
    outer = MIMEMultipart("alternative")
    outer["Subject"] = req.subject or ""
    outer["From"] = from_addr
    outer["To"] = req.to_email
    outer["Message-ID"] = f"<{req.message_id}@{from_addr.split('@')[-1]}>"

    body = req.body or ""
    looks_html = "<" in body and ">" in body
    text_part = _to_plain(body) if looks_html else body

    outer.attach(MIMEText(text_part, "plain", "utf-8"))
    if looks_html:
        outer.attach(MIMEText(body, "html", "utf-8"))
    return outer


def _to_plain(html: str) -> str:
    import re
    text = re.sub(r"<br\s*/?>|</p>", "\n", html, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ── Google Workspace ──────────────────────────────────────────
def try_register_gmail() -> tuple[bool, str]:
    """Registers only with explicit opt-in AND credentials present, matching
    the fail-closed convention in delivery_ext.try_register_ses()."""
    if os.environ.get(GMAIL_ENV_FLAG, "").lower() != "true":
        return False, f"{GMAIL_ENV_FLAG} not set — staying dry-run (deliberate)"
    try:
        from google.oauth2 import service_account  # noqa: F401
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError:
        return False, "google-api-python-client / google-auth not installed"

    send_as = os.environ.get(GMAIL_USER_ENV)
    creds_file = os.environ.get(GMAIL_CREDS_ENV)
    if not send_as or not creds_file:
        return False, f"{GMAIL_USER_ENV} and {GMAIL_CREDS_ENV} both required"
    if not os.path.exists(creds_file):
        return False, f"credentials file not found: {creds_file}"

    def _gmail_transport(req: "mx.SendRequest") -> str:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            creds_file,
            scopes=["https://www.googleapis.com/auth/gmail.send"],
        ).with_subject(send_as)
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        mime = _build_mime(req, send_as)
        raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
        sent = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        # threadId is what lets a follow-up land in the same conversation.
        return sent.get("id", f"gmail-{req.message_id}")

    delivery.register_transport("gmail", _gmail_transport)
    return True, f"Gmail Workspace transport registered (send-as {send_as})"


# ── Microsoft 365 ─────────────────────────────────────────────
def try_register_m365() -> tuple[bool, str]:
    """Second production provider behind the identical seam — proof the
    abstraction is real rather than a single-vendor wrapper wearing an
    interface."""
    if os.environ.get(M365_ENV_FLAG, "").lower() != "true":
        return False, f"{M365_ENV_FLAG} not set — staying dry-run (deliberate)"
    try:
        import msal  # noqa: F401
        import requests  # noqa: F401
    except ImportError:
        return False, "msal / requests not installed"

    send_as = os.environ.get(M365_USER_ENV)
    tenant = os.environ.get(M365_TENANT_ENV)
    client = os.environ.get(M365_CLIENT_ENV)
    secret = os.environ.get(M365_SECRET_ENV)
    if not all([send_as, tenant, client, secret]):
        return False, "M365_SEND_AS / TENANT_ID / CLIENT_ID / CLIENT_SECRET required"

    def _m365_transport(req: "mx.SendRequest") -> str:
        import msal
        import requests

        app = msal.ConfidentialClientApplication(
            client, authority=f"https://login.microsoftonline.com/{tenant}",
            client_credential=secret)
        token = app.acquire_token_for_client(
            scopes=["https://graph.microsoft.com/.default"])
        if "access_token" not in token:
            raise RuntimeError(f"M365 auth failed: {token.get('error_description')}")

        body = req.body or ""
        resp = requests.post(
            f"https://graph.microsoft.com/v1.0/users/{send_as}/sendMail",
            headers={"Authorization": f"Bearer {token['access_token']}"},
            json={"message": {
                "subject": req.subject or "",
                "body": {"contentType": "HTML" if "<" in body else "Text",
                         "content": body},
                "toRecipients": [{"emailAddress": {"address": req.to_email}}],
            }, "saveToSentItems": True},
            timeout=30)
        if resp.status_code >= 400:
            raise RuntimeError(f"Graph sendMail {resp.status_code}: {resp.text[:300]}")
        return f"m365-{req.message_id}"

    delivery.register_transport("microsoft_365", _m365_transport)
    return True, f"Microsoft 365 transport registered (send-as {send_as})"


def register_all() -> dict[str, str]:
    """Call at startup. Everything stays dry-run unless explicitly opted in."""
    results = {}
    for name, fn in (("gmail", try_register_gmail), ("microsoft_365", try_register_m365)):
        ok, detail = fn()
        results[name] = ("registered: " if ok else "skipped: ") + detail
    return results
