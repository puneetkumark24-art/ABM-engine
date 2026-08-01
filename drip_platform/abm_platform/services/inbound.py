"""Inbound engine — bounce and reply capture WITHOUT a public HTTPS endpoint.

WHY THIS EXISTS
---------------
`delivery.ingest_webhook()` is the right shape for an ESP that POSTs events to
us, but it requires a publicly reachable URL. PHASE_11 flags that as the open
deployment decision (VPS vs ngrok), and it is the last thing standing between
this platform and real send/receive on the single-laptop deployment.

For the transport this platform should actually use — a real Google Workspace
or Microsoft 365 mailbox (see delivery_gmail.py for why not SES/Mandrill) —
webhooks do not exist at all. Bounces arrive as DSN emails in the sending
mailbox and replies arrive as ordinary replies. So we *poll*, outbound, on the
scheduler. No inbound port, no tunnel, no always-on host. If the laptop sleeps
for two days the messages are still sitting in the mailbox.

WHAT IT CLOSES
--------------
1. DSN bounce parsing (RFC 3464) with a heuristic fallback for the many real
   MTAs that do not conform. Hard bounce => immediate suppression, matching
   DEL-003. Three soft bounces in 30 days escalate to suppression.

2. **Email reply detection — the actual gap.** `seq_engine.pause_on_reply()`
   (ACC-001) is today reached from LinkedIn (`linkedin.register_reply`), from
   manual logging (`sales_engagement`), and from the API router. Nothing
   detects an *email* reply. So on the primary channel, the Decision Engine's
   flagship rule — "Replied => notify_sales, machine steps back" — only fires
   if a human remembers to log it. This module closes that: a detected reply
   flips the message to `replied`, pauses the person AND their whole account
   per ACC-001, and publishes `email.reply.received` so the existing
   engagement/decision chain picks it up with no changes downstream.

3. Auto-replies (out-of-office) are classified and deliberately NOT treated as
   engagement. An OOO is not interest, and scoring it as a reply would corrupt
   both the engagement rollup and the reply_rate on the rate card.

TESTABILITY
-----------
`poll_once()` takes an injectable `fetcher` returning raw RFC-822 messages, so
the whole path is exercisable with fixtures and needs neither Gmail
credentials nor a network. `gmail_fetcher()` is the production implementation.
"""
from __future__ import annotations

import email
import logging
import re
from datetime import datetime, timedelta
from email.message import Message
from email.utils import parseaddr
from typing import Callable, Iterable

from sqlalchemy.orm import Session

import models_ext as mx
import models as core_models
from abm_platform.events import Event, publish
from sequences import engine as seq_engine
from . import marketing

logger = logging.getLogger("drip.abm_platform.inbound")

# A soft bounce is only fatal if it keeps happening.
SOFT_BOUNCE_LIMIT = 3
SOFT_BOUNCE_WINDOW_DAYS = 30

# Reply attribution by sender address is a fallback only; beyond this window we
# refuse to guess which thread a bare reply belongs to.
REPLY_FALLBACK_DAYS = 90

_AUTO_REPLY_HEADERS = (
    ("auto-submitted", lambda v: v.lower() != "no"),
    ("x-autoreply", lambda v: True),
    ("x-autorespond", lambda v: True),
    ("precedence", lambda v: v.lower() in ("bulk", "auto_reply", "junk")),
    ("x-auto-response-suppress", lambda v: True),
)

_AUTO_REPLY_SUBJECT = re.compile(
    r"\b(out of (the )?office|automatic reply|auto[- ]?reply|autoreply|"
    r"on (annual |sick )?leave|vacation|away from|abwesenheit|"
    r"réponse automatique)\b",
    re.I,
)

_PERMANENT_HINTS = re.compile(
    r"(user unknown|no such user|does not exist|unknown recipient|"
    r"recipient (address )?rejected|mailbox (unavailable|not found)|"
    r"invalid (recipient|address)|address rejected|account (has been )?disabled|"
    r"no mailbox here|550[ -]5\.1\.1)",
    re.I,
)

_TRANSIENT_HINTS = re.compile(
    r"(mailbox full|over quota|quota exceeded|try again|temporarily|"
    r"greylist|deferred|timed out|too many|rate limit|service unavailable|"
    r"insufficient (system )?storage)",
    re.I,
)

_STATUS_RE = re.compile(r"\b([245])\.\d{1,3}\.\d{1,3}\b")


# ─────────────────────────────────────────────────────────────
#  Classification
# ─────────────────────────────────────────────────────────────
class InboundMessage:
    """Parsed view of one raw inbound message."""

    __slots__ = ("raw", "msg", "uid", "from_email", "subject", "kind",
                 "bounce_status", "bounce_permanent", "diagnostic",
                 "original_message_id", "in_reply_to")

    def __init__(self, raw: bytes, uid: str):
        self.raw = raw
        self.uid = uid
        self.msg: Message = email.message_from_bytes(raw)
        self.from_email = (parseaddr(self.msg.get("From", ""))[1] or "").lower()
        self.subject = self.msg.get("Subject", "") or ""
        self.in_reply_to = _header_message_id(self.msg.get("In-Reply-To"))
        self.kind = "unknown"
        self.bounce_status: str | None = None
        self.bounce_permanent = False
        self.diagnostic = ""
        self.original_message_id: str | None = None


def _header_message_id(value: str | None) -> str | None:
    if not value:
        return None
    m = re.search(r"<([^>]+)>", value)
    return (m.group(1) if m else value).strip() or None


def _is_auto_reply(msg: Message) -> bool:
    for name, test in _AUTO_REPLY_HEADERS:
        v = msg.get(name)
        if v and test(v):
            return True
    return bool(_AUTO_REPLY_SUBJECT.search(msg.get("Subject", "") or ""))


def _is_bounce(msg: Message) -> bool:
    ctype = (msg.get_content_type() or "").lower()
    if ctype == "multipart/report":
        if "delivery-status" in (msg.get_param("report-type", "") or "").lower():
            return True
        for part in msg.walk():
            if part.get_content_type() == "message/delivery-status":
                return True
    sender = (parseaddr(msg.get("From", ""))[1] or "").lower()
    if sender.startswith(("mailer-daemon", "postmaster", "no-reply@")):
        return True
    return msg.get("Return-Path", "") == "<>"


def parse_dsn(msg: Message) -> tuple[str | None, bool, str, str | None]:
    """Return (status_code, is_permanent, diagnostic, original_message_id).

    Structured RFC 3464 parse first; heuristics only where the MTA does not
    conform — which is common enough that a structured-only parser silently
    misses real bounces and keeps mailing dead addresses.
    """
    status = diagnostic = None
    original_id = None
    final_recipient = None

    for part in msg.walk():
        ctype = part.get_content_type()
        if ctype == "message/delivery-status":
            payload = part.get_payload()
            blocks = payload if isinstance(payload, list) else []
            for block in blocks:
                if not hasattr(block, "get"):
                    continue
                status = status or block.get("Status")
                diagnostic = diagnostic or block.get("Diagnostic-Code")
                final_recipient = final_recipient or block.get("Final-Recipient")
        elif ctype in ("message/rfc822", "text/rfc822-headers"):
            payload = part.get_payload()
            inner = payload[0] if isinstance(payload, list) and payload else None
            if inner is not None and hasattr(inner, "get"):
                original_id = original_id or _header_message_id(inner.get("Message-ID"))

    body_text = _flatten_text(msg)

    if not status:
        m = _STATUS_RE.search(body_text)
        if m:
            status = m.group(0)
    if not diagnostic:
        diagnostic = (final_recipient or "") + " " + body_text[:400]
    if not original_id:
        original_id = _header_message_id(msg.get("X-Original-Message-ID"))

    haystack = f"{status or ''} {diagnostic}"
    permanent = False
    if status and status.startswith("5"):
        permanent = True
    elif status and status.startswith("4"):
        permanent = False
    # Keyword hints override an absent or ambiguous status code.
    if _PERMANENT_HINTS.search(haystack):
        permanent = True
    elif _TRANSIENT_HINTS.search(haystack) and not (status or "").startswith("5"):
        permanent = False

    return status, permanent, diagnostic.strip()[:500], original_id


def _flatten_text(msg: Message) -> str:
    chunks: list[str] = []
    for part in msg.walk():
        if part.get_content_maintype() == "text":
            try:
                payload = part.get_payload(decode=True)
                if payload:
                    chunks.append(payload.decode("utf-8", errors="replace"))
            except Exception:  # malformed MIME is normal in bounces
                continue
    return "\n".join(chunks)


def classify(raw: bytes, uid: str) -> InboundMessage:
    im = InboundMessage(raw, uid)

    # Python's email parser is deliberately lenient: it will happily return a
    # Message for arbitrary bytes. Without this guard, corrupt or truncated
    # mail falls through to the `reply` branch — and a false reply is
    # expensive, because it fires the ACC-001 cascade and halts outreach to an
    # entire bank. No parseable sender => we refuse to guess.
    if not im.from_email or "@" not in im.from_email:
        im.kind = "unknown"
        return im

    if _is_bounce(im.msg):
        im.kind = "bounce"
        status, permanent, diag, orig = parse_dsn(im.msg)
        im.bounce_status, im.bounce_permanent = status, permanent
        im.diagnostic, im.original_message_id = diag, orig
    elif _is_auto_reply(im.msg):
        im.kind = "auto_reply"
    else:
        im.kind = "reply"
    return im


# ─────────────────────────────────────────────────────────────
#  Handling
# ─────────────────────────────────────────────────────────────
def _already_seen(db: Session, provider_event_id: str) -> bool:
    return db.query(mx.DeliveryEvent).filter_by(
        provider_event_id=provider_event_id).first() is not None


def _resolve_message_id(db: Session, im: InboundMessage) -> str | None:
    """Find which send this inbound message concerns.

    Header-based matching is reliable and always tried first. The
    sender-address fallback is a guess and is bounded to a recent window —
    without that bound, a reply could be attributed to a send from a year ago.
    """
    for candidate in (im.original_message_id, im.in_reply_to):
        if candidate:
            hit = db.query(mx.SendRequest).filter_by(message_id=candidate).first()
            if hit:
                return hit.message_id

    if not im.from_email:
        return None
    since = datetime.utcnow() - timedelta(days=REPLY_FALLBACK_DAYS)
    recent = (db.query(mx.SendRequest)
              .filter(mx.SendRequest.to_email.ilike(im.from_email))
              .filter(mx.SendRequest.created_at >= since)
              .order_by(mx.SendRequest.created_at.desc())
              .first())
    return recent.message_id if recent else None


def _find_person(db: Session, email_addr: str):
    """Match on both address columns — people reply from whichever address the
    mail actually reached, which is not always the one we sent to."""
    if not email_addr:
        return None
    P = core_models.Person
    return (db.query(P)
            .filter((P.primary_email.ilike(email_addr))
                    | (P.secondary_email.ilike(email_addr)))
            .first())


def _soft_bounce_count(db: Session, email_addr: str) -> int:
    since = datetime.utcnow() - timedelta(days=SOFT_BOUNCE_WINDOW_DAYS)
    return (db.query(mx.DeliveryEvent)
            .filter(mx.DeliveryEvent.event_type == "soft_bounce")
            .filter(mx.DeliveryEvent.occurred_at >= since)
            .filter(mx.DeliveryEvent.meta["to"].as_string() == email_addr.lower()
                    if hasattr(mx.DeliveryEvent.meta, "__getitem__") else True)
            .count())


def handle_bounce(db: Session, im: InboundMessage, message_id: str | None) -> dict:
    """Hard bounce => suppress now (DEL-003). Soft bounce => count, and escalate
    once it is clearly not transient."""
    recipient = _bounced_recipient(im)
    etype = "hard_bounce" if im.bounce_permanent else "soft_bounce"

    db.add(mx.DeliveryEvent(
        message_id=message_id or f"unmatched-{im.uid}",
        event_type=etype, provider="inbound_poll",
        provider_event_id=f"inbound:{im.uid}",
        meta={"to": recipient, "status": im.bounce_status,
              "diagnostic": im.diagnostic}))

    if message_id:
        msg = db.query(mx.EmailMessage).filter_by(id=message_id).first()
        if msg:
            msg.status = "bounced"

    suppressed = False
    if recipient:
        if im.bounce_permanent:
            marketing.suppress(db, recipient, reason="bounce")
            suppressed = True
        else:
            prior = (db.query(mx.DeliveryEvent)
                     .filter(mx.DeliveryEvent.event_type == "soft_bounce")
                     .filter(mx.DeliveryEvent.occurred_at
                             >= datetime.utcnow() - timedelta(days=SOFT_BOUNCE_WINDOW_DAYS))
                     .all())
            hits = sum(1 for e in prior if (e.meta or {}).get("to") == recipient)
            if hits >= SOFT_BOUNCE_LIMIT:
                marketing.suppress(db, recipient, reason="bounce")
                suppressed = True

    db.commit()
    publish(Event(f"email.event.{etype}", key=message_id,
                  payload={"to": recipient, "status": im.bounce_status}))
    return {"kind": etype, "to": recipient, "suppressed": suppressed}


def _bounced_recipient(im: InboundMessage) -> str | None:
    """Whose address actually failed — not the mailer-daemon that told us."""
    for part in im.msg.walk():
        if part.get_content_type() == "message/delivery-status":
            payload = part.get_payload()
            for block in (payload if isinstance(payload, list) else []):
                if hasattr(block, "get") and block.get("Final-Recipient"):
                    return block["Final-Recipient"].split(";")[-1].strip().lower()
        if part.get_content_type() in ("message/rfc822", "text/rfc822-headers"):
            payload = part.get_payload()
            inner = payload[0] if isinstance(payload, list) and payload else None
            if inner is not None and hasattr(inner, "get") and inner.get("To"):
                return (parseaddr(inner["To"])[1] or "").lower()
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", _flatten_text(im.msg))
    return m.group(0).lower() if m else None


def handle_reply(db: Session, im: InboundMessage, message_id: str | None) -> dict:
    """THE gap this module exists to close.

    Flips the message to `replied`, then fires ACC-001 via
    `seq_engine.pause_on_reply` — the same cascade a LinkedIn reply already
    triggers — so the account stops receiving automated touches and the
    Decision Engine's `replied => notify_sales` rule finally fires for email.
    """
    db.add(mx.DeliveryEvent(
        message_id=message_id or f"unmatched-{im.uid}",
        event_type="reply", provider="inbound_poll",
        provider_event_id=f"inbound:{im.uid}",
        meta={"from": im.from_email, "subject": im.subject[:200]}))

    if message_id:
        msg = db.query(mx.EmailMessage).filter_by(id=message_id).first()
        if msg:
            msg.status = "replied"

    person = _find_person(db, im.from_email)
    cascade = {"paused_person": 0, "paused_account": 0}
    if person is not None:
        cascade = seq_engine.pause_on_reply(db, person.id, reason="email_reply")

    db.commit()
    publish(Event("email.reply.received",
                  key=person.id if person is not None else message_id,
                  payload={"from": im.from_email, "message_id": message_id,
                           "cascade": cascade}))
    return {"kind": "reply", "from": im.from_email,
            "person_id": person.id if person is not None else None,
            "cascade": cascade}


def handle_auto_reply(db: Session, im: InboundMessage, message_id: str | None) -> dict:
    """Recorded for the audit trail, explicitly excluded from engagement.
    An out-of-office is not interest."""
    db.add(mx.DeliveryEvent(
        message_id=message_id or f"unmatched-{im.uid}",
        event_type="auto_reply", provider="inbound_poll",
        provider_event_id=f"inbound:{im.uid}",
        meta={"from": im.from_email, "subject": im.subject[:200]}))
    db.commit()
    return {"kind": "auto_reply", "from": im.from_email}


# ─────────────────────────────────────────────────────────────
#  Polling
# ─────────────────────────────────────────────────────────────
def poll_once(db: Session, fetcher: Callable[[], Iterable[tuple[str, bytes]]]) -> dict:
    """Process one batch. `fetcher` yields (uid, raw_rfc822_bytes).

    Idempotent: every event carries provider_event_id `inbound:{uid}`, so a
    message seen twice is skipped rather than double-counted — the same
    guarantee `ingest_webhook` gives for replayed webhooks.
    """
    counts = {"bounce": 0, "reply": 0, "auto_reply": 0, "unknown": 0,
              "duplicates": 0, "suppressed": 0, "errors": 0}

    for uid, raw in fetcher():
        if _already_seen(db, f"inbound:{uid}"):
            counts["duplicates"] += 1
            continue
        try:
            im = classify(raw, uid)
            if im.kind == "unknown":
                logger.warning("inbound uid=%s unparseable sender — skipped", uid)
                counts["unknown"] += 1
                continue
            message_id = _resolve_message_id(db, im)
            if im.kind == "bounce":
                r = handle_bounce(db, im, message_id)
                counts["bounce"] += 1
                counts["suppressed"] += 1 if r.get("suppressed") else 0
            elif im.kind == "auto_reply":
                handle_auto_reply(db, im, message_id)
                counts["auto_reply"] += 1
            else:
                handle_reply(db, im, message_id)
                counts["reply"] += 1
        except Exception as exc:  # one malformed message must not stop the batch
            logger.exception("inbound uid=%s failed: %s", uid, exc)
            db.rollback()
            counts["errors"] += 1

    return counts


def gmail_fetcher(user_email: str, credentials_path: str | None = None,
                  max_results: int = 100, label: str = "INBOX"):
    """Production fetcher: reads unread messages via the Gmail API.

    Outbound HTTPS only — works from the laptop, behind NAT, with no inbound
    port. Requires google-api-python-client and either domain-wide delegation
    or a per-user OAuth token; see delivery_gmail.py.
    """
    def _fetch() -> Iterable[tuple[str, bytes]]:
        import base64
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        scopes = ["https://www.googleapis.com/auth/gmail.modify"]
        creds = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=scopes).with_subject(user_email)
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)

        listing = svc.users().messages().list(
            userId="me", q="is:unread", labelIds=[label],
            maxResults=max_results).execute()
        for ref in listing.get("messages", []):
            full = svc.users().messages().get(
                userId="me", id=ref["id"], format="raw").execute()
            yield ref["id"], base64.urlsafe_b64decode(full["raw"])
            svc.users().messages().modify(
                userId="me", id=ref["id"],
                body={"removeLabelIds": ["UNREAD"]}).execute()

    return _fetch
