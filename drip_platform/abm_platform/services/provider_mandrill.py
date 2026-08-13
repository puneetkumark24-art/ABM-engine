"""Superseded by `mandrill_events.py`.

Two Mandrill translators is one too many -- they would drift, and the wrong one
would eventually get wired into the webhook. `mandrill_events.translate()` is
the surviving implementation; signature verification lives in
`webhook_security.verify_mandrill()`.

Kept as a redirect rather than deleted because this repository is on a mount
that refuses file removal; delete it from Windows when convenient.
"""
from .mandrill_events import translate  # noqa: F401
from webhook_security import verify_mandrill  # noqa: F401
