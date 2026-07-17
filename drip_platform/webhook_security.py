"""
webhook_security.py — inbound webhook signature verification (P0-A, BOMB 2).

The delivery webhook currently trusts any POST — a forged bounce/complaint would
suppress a real contact. Providers sign their payloads; verify before acting.

- verify_hmac_sha256: generic (Mandrill-style) HMAC over the raw body.
- verify_ses_sns: placeholder for AWS SNS message signature (cert-based) — the
  real SES/SNS path validates the X-Amz signature against the SNS signing cert;
  wired when SES is enabled.

Timing-safe comparison throughout.
"""
from __future__ import annotations
import base64
import hashlib
import hmac
import os

_MANDRILL_KEY = os.environ.get("MANDRILL_WEBHOOK_KEY", "")


def verify_hmac_sha256(raw_body: bytes, signature: str, secret: str | None = None) -> bool:
    """Generic HMAC-SHA256 body signature (base64). Provider posts the signature
    in a header (e.g. X-Mandrill-Signature); we recompute and compare."""
    secret = secret if secret is not None else _MANDRILL_KEY
    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    try:
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


def verify_mandrill(raw_body: bytes, url: str, params: dict, signature: str,
                    secret: str | None = None) -> bool:
    """Mandrill's exact scheme: HMAC-SHA1 over url + sorted(key+value) of POST
    params. Implemented for correctness when Mandrill is the ESP."""
    secret = secret if secret is not None else _MANDRILL_KEY
    if not secret:
        return False
    signed = url
    for k in sorted(params.keys()):
        signed += k + params[k]
    digest = hmac.new(secret.encode(), signed.encode(), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature or "")


def verify_ses_sns(headers: dict, body: dict) -> bool:
    """AWS SNS delivers SES events; real validation fetches the SigningCertURL
    (must be an amazonaws.com host) and verifies the RSA signature over the
    canonical message. Stubbed True-gate is intentionally NOT provided — returns
    False until the cert-verification path is wired, so nothing is trusted by
    default."""
    return False
