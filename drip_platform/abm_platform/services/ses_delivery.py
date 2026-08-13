"""Amazon SES v2 adapter. Inert unless explicitly registered from the environment.

Uses the normal AWS credential provider chain (task/instance roles preferred),
configuration-set event publishing, and opaque DRIP message tags. Importing this
module performs no network call and never registers a live transport.
"""
from __future__ import annotations
from dataclasses import dataclass
import os
import re

from . import delivery

_TAG_VALUE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")


@dataclass(frozen=True)
class SesConfig:
    region: str
    from_email: str
    configuration_set: str
    reply_to: str | None = None


def config_from_env() -> SesConfig:
    required = {
        "AWS_SES_REGION": os.environ.get("AWS_SES_REGION", "").strip(),
        "SES_FROM": os.environ.get("SES_FROM", "").strip(),
        "SES_CONFIGURATION_SET": os.environ.get("SES_CONFIGURATION_SET", "").strip(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise ValueError("missing SES configuration: " + ", ".join(missing))
    if "@" not in required["SES_FROM"]:
        raise ValueError("SES_FROM must be an email address")
    return SesConfig(required["AWS_SES_REGION"], required["SES_FROM"],
                     required["SES_CONFIGURATION_SET"],
                     os.environ.get("SES_REPLY_TO", "").strip() or None)


def build_transport(client, config: SesConfig):
    """Build an injectable adapter; tests use a fake client, production boto3."""
    def send(req) -> str:
        if not _TAG_VALUE.fullmatch(req.message_id or ""):
            raise ValueError("message_id cannot be represented as an SES tag")
        kwargs = {
            "FromEmailAddress": config.from_email,
            "Destination": {"ToAddresses": [req.to_email]},
            "Content": {"Simple": {
                "Subject": {"Data": req.subject or "", "Charset": "UTF-8"},
                "Body": {"Html": {"Data": req.body or "", "Charset": "UTF-8"}},
            }},
            "ConfigurationSetName": config.configuration_set,
            "EmailTags": [{"Name": "drip_message_id", "Value": req.message_id}],
        }
        if config.reply_to:
            kwargs["ReplyToAddresses"] = [config.reply_to]
        try:
            response = client.send_email(**kwargs)
        except Exception as exc:
            # A timeout/closed connection after request transmission has an
            # unknowable outcome. Never put it on the automatic retry path.
            if type(exc).__name__ in {"ReadTimeoutError", "ConnectTimeoutError",
                                      "ConnectionClosedError", "HTTPClientError"}:
                raise delivery.AmbiguousDeliveryError(
                    f"SES outcome unknown after {type(exc).__name__}; reconcile events before retry") from exc
            raise
        provider_id = response.get("MessageId") if isinstance(response, dict) else None
        if not provider_id:
            raise RuntimeError("SES accepted no provider message id")
        return str(provider_id)
    return send


def try_register() -> tuple[bool, str]:
    """Register only after explicit opt-in and complete local configuration.

    Client construction is local; AWS validates identity, configuration set,
    credentials and sandbox permissions only on the first controlled send.
    """
    if os.environ.get("ENABLE_SES_TRANSPORT", "").strip().lower() != "true":
        return False, "ENABLE_SES_TRANSPORT is not true — staying dry-run; SES remains disabled"
    try:
        config = config_from_env()
        import boto3
        client = boto3.client("sesv2", region_name=config.region)
    except Exception as exc:  # credential-chain/config/client failures stay closed
        return False, str(exc)
    delivery.register_transport("ses", build_transport(client, config))
    return True, f"SES registered in {config.region} with configuration set {config.configuration_set}"
