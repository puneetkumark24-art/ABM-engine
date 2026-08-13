"""The gate between "we simulated an email" and "a real message left the building".

Every send path in the platform asks `resolve_transport()` what it is allowed
to use. It returns `dry_run` unless EVERY condition below is satisfied, and it
fails closed on anything it cannot verify — a missing variable, an unparseable
value, an unregistered transport, an exception. There is deliberately no
"assume yes" branch anywhere in this file.

Conditions for real delivery:
  1. EMAIL_LIVE_SENDING_ENABLED=true          — explicit human activation
  2. EMAIL_TRANSPORT names a REGISTERED       — not merely configured
     transport in delivery._TRANSPORTS
  3. credentials for that transport present
  4. PUBLIC_BASE_URL is absolute HTTPS        — tracking links must resolve,
                                                and must not be plaintext
  5. EMAIL_WEBHOOK_SECRET set                 — otherwise delivery receipts
                                                cannot be trusted, so
                                                "delivered" would be a guess
  6. sending domain passes SPF, DKIM, DMARC, has a return-path, and the
     campaign carries a working unsubscribe path
  7. inside the KSA send window                — applied to every real path

`activation_report()` returns the same checks as a list for the UI, so an
operator can see exactly which condition is blocking rather than a bare "no".
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

DRY_RUN = "dry_run"

LIVE_FLAG = "EMAIL_LIVE_SENDING_ENABLED"
TRANSPORT_VAR = "EMAIL_TRANSPORT"
WEBHOOK_SECRET_VAR = "EMAIL_WEBHOOK_SECRET"
BASE_URL_VAR = "PUBLIC_BASE_URL"

# Credentials each live transport needs before it may be selected.
TRANSPORT_CREDENTIALS = {
    "mandrill": ("MANDRILL_API_KEY",),
    # IAM task/instance roles are preferred; static access keys are not a
    # prerequisite. These are the adapter's required non-secret settings.
    "ses": ("AWS_SES_REGION", "SES_FROM", "SES_CONFIGURATION_SET"),
    "gmail": ("GMAIL_SERVICE_ACCOUNT_JSON", "GMAIL_SEND_AS"),
    "microsoft_365": ("M365_TENANT_ID", "M365_CLIENT_ID", "M365_CLIENT_SECRET"),
}


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Activation:
    live: bool
    transport: str
    checks: list[Check] = field(default_factory=list)

    @property
    def blockers(self) -> list[str]:
        return [f"{c.name}: {c.detail}" for c in self.checks if not c.ok]

    def as_dict(self) -> dict:
        return {"live_sending": self.live, "transport": self.transport,
                "mode": "live" if self.live else "dry_run",
                "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail}
                           for c in self.checks],
                "blockers": self.blockers}


def _flag(name: str) -> bool:
    return (os.environ.get(name, "") or "").strip().lower() == "true"


def _https_base_url() -> tuple[bool, str]:
    base = (os.environ.get(BASE_URL_VAR) or "").strip()
    if not base:
        return False, f"{BASE_URL_VAR} is not set — tracking links cannot resolve"
    if base.startswith("http://"):
        return False, (f"{BASE_URL_VAR} is plaintext http — click redirects and the "
                       "open pixel would be sent unencrypted")
    if not base.startswith("https://"):
        return False, f"{BASE_URL_VAR} must be an absolute https URL (got {base!r})"
    return True, base


def domain_auth_checks(db: Session | None, domain: str | None) -> list[Check]:
    """SPF / DKIM / DMARC / return-path for the sending domain.

    Read from the DomainHealth record the deliverability service maintains.
    Absence is a FAILURE, not an unknown: an unverified sending domain is how
    a first campaign lands in spam and the domain's reputation never recovers.
    """
    out: list[Check] = []
    if not domain:
        return [Check("sending_domain", False,
                      "EMAIL_SENDING_DOMAIN is not set")]
    if db is None:
        return [Check("domain_authentication", False,
                      "no database session available to read domain health")]
    try:
        import models_p11 as p11
        row = db.query(p11.DomainHealth).filter_by(domain=domain).first()
    except Exception as exc:  # noqa: BLE001
        return [Check("domain_authentication", False,
                      f"could not read domain health: {type(exc).__name__}")]
    if row is None:
        return [Check("domain_authentication", False,
                      f"no DomainHealth record for {domain} — run authentication setup")]
    for label, value in (("spf", row.spf_ok), ("dkim", row.dkim_ok), ("dmarc", row.dmarc_ok)):
        out.append(Check(f"dns_{label}", bool(value),
                         "" if value else f"{label.upper()} not verified for {domain}"))
    out.append(Check("return_path", bool(os.environ.get("EMAIL_RETURN_PATH")),
                     "" if os.environ.get("EMAIL_RETURN_PATH")
                     else "EMAIL_RETURN_PATH not set — bounces cannot be attributed"))
    out.append(Check("unsubscribe_url", bool(os.environ.get("EMAIL_UNSUBSCRIBE_URL")),
                     "" if os.environ.get("EMAIL_UNSUBSCRIBE_URL")
                     else "EMAIL_UNSUBSCRIBE_URL not set — required by CAN-SPAM/GDPR "
                          "and by every major inbox provider"))
    return out


def activation_report(db: Session | None = None) -> Activation:
    """Evaluate every precondition. Never raises — an error is a failed check."""
    checks: list[Check] = []
    requested = (os.environ.get(TRANSPORT_VAR) or DRY_RUN).strip().lower()

    live_flag = _flag(LIVE_FLAG)
    checks.append(Check("explicit_activation", live_flag,
                        "" if live_flag else
                        f"{LIVE_FLAG} is not true — real delivery is switched off"))

    checks.append(Check("transport_selected", requested != DRY_RUN,
                        "" if requested != DRY_RUN else
                        f"{TRANSPORT_VAR} is dry_run"))

    registered = False
    try:
        from . import delivery
        registered = requested in delivery._TRANSPORTS and requested != DRY_RUN
    except Exception as exc:  # noqa: BLE001
        checks.append(Check("transport_registered", False,
                            f"could not inspect transports: {type(exc).__name__}"))
    else:
        checks.append(Check("transport_registered", registered,
                            "" if registered else
                            f"transport {requested!r} is not registered — its adapter "
                            "never called register_transport()"))

    needed = TRANSPORT_CREDENTIALS.get(requested, ())
    missing = [v for v in needed if not os.environ.get(v)]
    checks.append(Check("credentials", requested != DRY_RUN and not missing,
                        "" if requested != DRY_RUN and not missing else
                        (f"missing: {', '.join(missing)}" if missing
                         else "no credentials required for dry_run")))

    ok_url, url_detail = _https_base_url()
    checks.append(Check("public_base_url", ok_url, "" if ok_url else url_detail))

    if requested == "ses":
        queue = bool(os.environ.get("SES_EVENT_QUEUE_URL"))
        topic = bool(os.environ.get("SES_EVENT_TOPIC_ARN"))
        checks.append(Check("ses_receipt_channel", queue and topic,
                            "" if queue and topic else
                            "SES_EVENT_QUEUE_URL and SES_EVENT_TOPIC_ARN are required"))
    else:
        has_secret = bool(os.environ.get(WEBHOOK_SECRET_VAR))
        checks.append(Check("webhook_secret", has_secret,
                            "" if has_secret else
                            f"{WEBHOOK_SECRET_VAR} not set — provider receipts could not be "
                            "verified, so 'delivered' would never be trustworthy"))

    checks.extend(domain_auth_checks(db, os.environ.get("EMAIL_SENDING_DOMAIN")))

    live = all(c.ok for c in checks)
    return Activation(live=live, transport=requested if live else DRY_RUN, checks=checks)


def resolve_transport(db: Session | None = None, requested: str | None = None) -> str:
    """The single source of truth for what a send path may use.

    Returns the configured live transport only when every activation check
    passes; otherwise `dry_run`. Callers pass the result straight to
    delivery.enqueue(), so a misconfiguration downgrades to simulation rather
    than failing the send or, worse, sending anyway.
    """
    if requested == DRY_RUN:
        return DRY_RUN
    try:
        report = activation_report(db)
    except Exception:  # noqa: BLE001 — fail closed on anything unexpected
        return DRY_RUN
    return report.transport if report.live else DRY_RUN


def send_window_ok(now=None) -> tuple[bool, str]:
    """KSA business-hours window, applied to every REAL path.

    Kept here rather than in each caller so campaigns, journeys, workflows and
    approved drafts cannot each grow their own interpretation of it.
    """
    try:
        from sequences.send_window import is_within_send_window
        return is_within_send_window(now) if now else is_within_send_window()
    except Exception as exc:  # noqa: BLE001
        return False, f"send-window check failed: {type(exc).__name__}"


def guard_real_send(db: Session | None = None, requested: str | None = None) -> tuple[str, str]:
    """(transport, reason). Combines activation with the KSA send window.

    A live transport outside the send window is downgraded to dry_run rather
    than queued, so a misfiring scheduler cannot deliver to Saudi executives at
    3am and burn the domain's reputation on a timing bug.
    """
    transport = resolve_transport(db, requested)
    if transport == DRY_RUN:
        return DRY_RUN, "live sending not activated"
    ok, why = send_window_ok()
    if not ok:
        return DRY_RUN, f"outside KSA send window: {why}"
    return transport, "activated"
