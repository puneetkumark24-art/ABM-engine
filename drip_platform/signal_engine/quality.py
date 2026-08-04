from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import html

STOPWORDS = {"a", "an", "and", "in", "of", "on", "the", "to", "with", "for", "its", "from", "saudi", "arabia", "bank"}
MULTIPART_SUFFIXES = {"com.sa", "org.sa", "gov.sa", "edu.sa", "co.uk", "org.uk", "com.au", "co.in", "com.cn", "com.sg", "com.br"}


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def headline_tokens(value: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", normalize_text(value).casefold()) if len(w) > 2 and w not in STOPWORDS}


NEGATION_TERMS = {
    "cancelled": "contradicts", "canceled": "contradicts", "withdrawn": "retracts",
    "withdrew": "retracts", "terminated": "contradicts", "suspended": "contradicts",
    "denies": "corrects", "denied": "corrects", "incorrect": "corrects",
    "not proceeding": "contradicts", "no longer": "contradicts",
}

MATERIALITY_BASE = {
    "tender": .90, "regulatory": .85, "executive": .75, "partnership": .70,
    "hiring": .55, "financial": .45, "news": .25,
}


@dataclass(frozen=True)
class QualityAssessment:
    subject: str | None
    action: str
    object_text: str | None
    event_date: str | None
    location: str | None
    source_family: str
    independence_key: str
    completeness: float
    materiality: float
    decision: str
    missing_fields: list[str]
    reasons: list[str]
    correction_type: str | None


def _source_family(source_id: str, url: str | None) -> tuple[str, str]:
    host = (urlsplit(url).hostname or "").casefold().removeprefix("www.") if url else ""
    if host.endswith("news.google.com"):
        return "aggregator:google-news", "aggregator:google-news"
    if host:
        labels = host.split(".")
        suffix2 = ".".join(labels[-2:])
        root = ".".join(labels[-3:]) if suffix2 in MULTIPART_SUFFIXES and len(labels) >= 3 else suffix2
        return f"domain:{root}", f"domain:{root}"
    return f"source:{source_id}", f"source:{source_id}"


def assess_quality(*, source_id: str, title: str, body: str, url: str | None,
                   published: datetime | None, account_name: str | None,
                   signal_type: str, product_match: str | None,
                   attribution_confidence: float) -> QualityAssessment:
    text = normalize_text(f"{title} {body}")
    folded = text.casefold()
    family, independence = _source_family(source_id, url)
    correction_type = next((relation for term, relation in NEGATION_TERMS.items()
                            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", folded)), None)
    # "not only" is additive, not a denial. Do not contest an existing claim.
    if re.search(r"\bnot only\b", folded):
        correction_type = None
    subject = account_name
    action = signal_type
    counterparty = None
    patterns = [
        r"(?:with|and|selects|selected|appoints|appointed)\s+([A-Z][A-Za-z0-9& .-]{2,50})",
        r"(?:for|on)\s+((?:digital|open|core|loan|payment)[A-Za-z0-9& .-]{2,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            counterparty = normalize_text(match.group(1)).rstrip(" .,-")
            break
    object_text = product_match or counterparty
    location = "KSA" if re.search(r"\b(saudi|ksa|kingdom)\b", folded) else None
    fields = {
        "subject": bool(subject), "action": signal_type != "news",
        "object": bool(object_text), "event_date": published is not None,
        "source": bool(url or source_id),
    }
    weights = {"subject": .30, "action": .20, "object": .20, "event_date": .20, "source": .10}
    completeness = sum(weights[name] for name, present in fields.items() if present)
    missing = [name for name, present in fields.items() if not present]
    materiality = MATERIALITY_BASE.get(signal_type, .25)
    if product_match:
        materiality += .10
    if attribution_confidence >= .80:
        materiality += .05
    materiality = min(1.0, materiality)
    reasons = [f"complete:{name}" for name, present in fields.items() if present]
    reasons.extend(f"missing:{name}" for name in missing)
    if correction_type:
        decision = correction_type
        reasons.append(f"claim_relation:{correction_type}")
    elif subject and signal_type != "news" and completeness < .85:
        decision = "review_incomplete"
    elif subject and materiality < .45:
        decision = "informational"
    else:
        decision = "pass"
    return QualityAssessment(subject, action, object_text, published.isoformat() if published else None,
                             location, family, independence, completeness, materiality,
                             decision, missing, reasons, correction_type)


def claim_similarity(title_a: str, title_b: str) -> float:
    a, b = headline_tokens(title_a), headline_tokens(title_b)
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def is_plausible_relation(title: str, prior_title: str, signal_type: str, prior_type: str,
                          event_date: datetime, prior_date: datetime) -> bool:
    """Conservative relation gate: same event class, near in time, and strong lexical overlap."""
    if signal_type != prior_type or abs((event_date.date() - prior_date.date()).days) > 120:
        return False
    a, b = headline_tokens(title), headline_tokens(prior_title)
    shared = a & b
    return len(shared) >= 3 and claim_similarity(title, prior_title) >= .30
