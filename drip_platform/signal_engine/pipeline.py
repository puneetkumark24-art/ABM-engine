from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import uuid
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


PARSER_VERSION = "rss-atom-v1"
PROMOTION_RULE_VERSION = "deterministic-quality-v2"
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "gclid", "fbclid"}
OUT_OF_MARKET_TERMS = {"malaysia", "jordan", "pakistan", "egypt", "kuwait", "bahrain", "uae", "dubai", "oman", "sudan", "australia"}
TITLE_STOPWORDS = {"a", "an", "and", "in", "of", "on", "the", "to", "with", "for", "its", "from", "saudi", "arabia", "bank"}
NOISE_PATTERNS = [
    r"\bmarket size\b", r"\bgrowth outlook\b", r"\bforecast(?:s|ed)?\b.*\b20\d{2}\b",
    r"\btop \d+\b", r"\bbest companies\b", r"\bconsulting companies\b", r"\bshareholder circular\b",
    r"\bconceptual framework\b",
]

PRODUCT_KEYWORDS = {
    "digital_lending": ["digital lending", "loan origination", "lending platform", "credit origination", "تمويل رقمي", "الإقراض الرقمي"],
    "onboarding_kyc": ["onboarding", "know your customer", "kyc", "re-kyc", "digital identity", "اعرف عميلك", "الهوية الرقمية"],
    "core_banking": ["core banking", "banking platform", "temenos", "finacle", "flexcube", "backbase", "النظام المصرفي الأساسي"],
    "collections": ["collections", "debt recovery", "delinquency", "تحصيل الديون"],
    "payments_open_banking": ["open banking", "payments", "payment platform", "fintech", "المصرفية المفتوحة", "المدفوعات"],
}
PRODUCT_KEYWORDS["digital_lending"].extend(["pos lending", "embedded finance"])

TYPE_RULES = [
    ("tender", ["rfp", "request for proposal", "tender", "procurement", "مناقصة", "طلب تقديم عروض"]),
    ("hiring", ["hiring", "vacancy", "career", "job opening", "appointed", "توظيف", "وظيفة", "تعيين"]),
    ("regulatory", ["sama", "central bank", "regulation", "circular", "directive", "compliance", "البنك المركزي", "تعميم", "لائحة"]),
    ("partnership", ["partnership", "memorandum", "mou", "collaboration", "partners with", "شراكة", "مذكرة تفاهم", "تعاون"]),
    ("executive", ["chief executive", "ceo", "cto", "cio", "chief digital", "board member", "الرئيس التنفيذي", "مجلس الإدارة"]),
    ("financial", ["quarter results", "annual report", "net profit", "rating", "earnings", "نتائج", "صافي الربح", "التقرير السنوي"]),
]

DECAY_DAYS = {"OPERATIONAL": 30, "TACTICAL": 90, "STRATEGIC": 365, "STRUCTURAL": 1095}
TYPE_DECAY = {"hiring": "OPERATIONAL", "tender": "TACTICAL", "regulatory": "STRATEGIC", "partnership": "STRATEGIC", "executive": "STRATEGIC", "financial": "TACTICAL", "news": "OPERATIONAL"}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


def normalize_text(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = value.replace("ـ", "")
    value = re.sub("[إأآٱ]", "ا", value)
    value = value.replace("ى", "ي").replace("ة", "ه")
    return re.sub(r"\s+", " ", value).strip()


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), urlencode(sorted(query)), ""))


def digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8", errors="replace")).hexdigest()


def headline_tokens(value: str) -> set[str]:
    tokens = set()
    for word in re.findall(r"[a-z0-9]+", normalize_text(value).casefold()):
        if len(word) <= 2 or word in TITLE_STOPWORDS:
            continue
        if word.startswith("partner"):
            word = "partner"
        tokens.add(word)
    return tokens


def parse_datetime(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    value = value.strip()
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_feed(raw: bytes) -> list[dict]:
    root = ET.fromstring(raw)
    out: list[dict] = []
    for item in root.iter("item"):
        guid = normalize_text(item.findtext("guid") or "")
        out.append({
            "native_id": guid or None,
            "title": normalize_text(item.findtext("title") or ""),
            "url": normalize_text(item.findtext("link") or ""),
            "body": normalize_text(item.findtext("description") or ""),
            "published": normalize_text(item.findtext("pubDate") or ""),
        })
    ns = "{http://www.w3.org/2005/Atom}"
    for entry in root.iter(f"{ns}entry"):
        link = entry.find(f"{ns}link")
        out.append({
            "native_id": normalize_text(entry.findtext(f"{ns}id") or "") or None,
            "title": normalize_text(entry.findtext(f"{ns}title") or ""),
            "url": (link.get("href") if link is not None else "") or "",
            "body": normalize_text(entry.findtext(f"{ns}summary") or entry.findtext(f"{ns}content") or ""),
            "published": normalize_text(entry.findtext(f"{ns}published") or entry.findtext(f"{ns}updated") or ""),
        })
    return [x for x in out if x["title"]]


class _LinkParser(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.href = None
        self.text: list[str] = []
        self.items: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag.casefold() == "a":
            self.href = dict(attrs).get("href")
            self.text = []

    def handle_data(self, data):
        if self.href is not None:
            self.text.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() != "a" or self.href is None:
            return
        title = normalize_text(" ".join(self.text))
        url = urljoin(self.base_url, self.href)
        blocked = {"read more", "more", "home", "news", "view all", "contact us"}
        if len(title) >= 25 and title.casefold() not in blocked and url.startswith("http"):
            self.items.append({"native_id": url, "title": title, "url": url, "body": title, "published": None})
        self.href = None
        self.text = []


def parse_official_page(raw: bytes, endpoint: str) -> list[dict]:
    parser = _LinkParser(endpoint)
    parser.feed(raw.decode("utf-8", errors="replace"))
    unique = {}
    for item in parser.items:
        unique.setdefault(canonical_url(item["url"]), item)
    return list(unique.values())[:100]


@dataclass
class Attribution:
    account_id: str | None
    confidence: float
    ambiguous: bool
    candidates: list[tuple[str, float, list[str]]]


class Pipeline:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def add_account(self, account_id: str, canonical_name: str, aliases=None, domains=None, tickers=None) -> None:
        self.con.execute(
            """INSERT INTO accounts(id,canonical_name,aliases_json,domains_json,tickers_json) VALUES(?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET canonical_name=excluded.canonical_name,aliases_json=excluded.aliases_json,
               domains_json=excluded.domains_json,tickers_json=excluded.tickers_json""",
            (account_id, canonical_name, json.dumps(aliases or []), json.dumps(domains or []), json.dumps(tickers or [])),
        )
        self.con.commit()

    def add_source(self, source_id: str, name: str, kind: str, language: str, endpoint: str | None,
                   evidence: float, proximity: float, independence: float, specificity: float,
                   incentive_bias: float = 0.0, expected_interval_minutes: int = 1440) -> None:
        self.con.execute(
            """INSERT INTO sources
               (id,name,kind,language,endpoint,evidence,proximity,independence,specificity,incentive_bias,expected_interval_minutes)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name,kind=excluded.kind,language=excluded.language,
               endpoint=excluded.endpoint,evidence=excluded.evidence,proximity=excluded.proximity,
               independence=excluded.independence,specificity=excluded.specificity,
               incentive_bias=excluded.incentive_bias,expected_interval_minutes=excluded.expected_interval_minutes""",
            (source_id, name, kind, language, endpoint, evidence, proximity, independence, specificity, incentive_bias, expected_interval_minutes),
        )
        self.con.commit()

    def _source(self, source_id: str) -> sqlite3.Row:
        row = self.con.execute("SELECT * FROM sources WHERE id=? AND enabled=1", (source_id,)).fetchone()
        if row is None:
            raise ValueError(f"unknown or disabled source: {source_id}")
        return row

    def _accounts(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM accounts WHERE active=1").fetchall()

    def attribute(self, title: str, body: str, url: str | None) -> Attribution:
        text = normalize_text(f"{title} {body}").casefold()
        host = (urlsplit(url).hostname or "").casefold() if url else ""
        ranked = []
        for account in self._accounts():
            score = 0.0
            reasons = []
            names = [account["canonical_name"], *json.loads(account["aliases_json"])]
            matched_names = [n for n in names if normalize_text(n).casefold() in text and len(normalize_text(n)) >= 3]
            if matched_names:
                score += min(0.82, 0.62 + 0.05 * len(matched_names))
                reasons.append("name_or_alias:" + matched_names[0])
            for domain in json.loads(account["domains_json"]):
                if domain.casefold() in host:
                    score += 0.25
                    reasons.append("source_domain:" + domain)
            for ticker in json.loads(account["tickers_json"]):
                if re.search(rf"\b{re.escape(str(ticker))}\b", text):
                    score += 0.25
                    reasons.append("ticker:" + str(ticker))
            if score:
                ranked.append((account["id"], min(score, 0.99), reasons))
        ranked.sort(key=lambda x: x[1], reverse=True)
        if not ranked:
            return Attribution(None, 0.0, False, [])
        ambiguous = len(ranked) > 1 and ranked[0][1] - ranked[1][1] < 0.15
        return Attribution(None if ambiguous else ranked[0][0], ranked[0][1], ambiguous, ranked)

    def classify(self, title: str, body: str) -> tuple[str, str, str, str | None, float]:
        text = normalize_text(f"{title} {body}").casefold()
        signal_type = "news"
        for candidate, words in TYPE_RULES:
            if any(normalize_text(w).casefold() in text for w in words):
                signal_type = candidate
                break
        if signal_type == "hiring" and not any(term in text for term in
                                               ("hiring", "vacancy", "job opening", "appointed", "توظيف", "وظيفه", "تعيين")):
            signal_type = "news"
        product_scores = {product: sum(1 for w in words if normalize_text(w).casefold() in text)
                          for product, words in PRODUCT_KEYWORDS.items()}
        product, hits = max(product_scores.items(), key=lambda x: x[1])
        product_match = product if hits else None
        relevance = min(1.0, 0.15 + hits * 0.22)
        if signal_type in {"tender", "regulatory", "partnership", "hiring"}:
            relevance = min(1.0, relevance + 0.2)
        urgency = "CRITICAL" if signal_type == "tender" else "HIGH" if signal_type in {"regulatory", "partnership"} else "MEDIUM"
        direction = "mixed" if signal_type == "partnership" else "positive" if signal_type in {"tender", "hiring"} else "neutral"
        return signal_type, urgency, direction, product_match, relevance

    @staticmethod
    def source_score(source: sqlite3.Row) -> float:
        base = 0.30 * source["evidence"] + 0.20 * source["proximity"] + 0.30 * source["independence"] + 0.20 * source["specificity"]
        return max(0.0, min(0.95, base * (1.0 - 0.25 * source["incentive_bias"])))

    def coverage_cap(self, account_id: str, now: datetime, current_source_id: str | None = None) -> float:
        enabled = self.con.execute("SELECT * FROM sources WHERE enabled=1").fetchall()
        if not enabled:
            return 0.20
        healthy = 0
        for source in enabled:
            if source["id"] == current_source_id:
                # The caller is processing a successfully parsed item from this
                # source now; do not penalize the first-ever run until its run
                # summary is committed a few lines later.
                healthy += 1
            elif source["last_success_at"]:
                last = datetime.fromisoformat(source["last_success_at"])
                allowed = timedelta(minutes=max(60, source["expected_interval_minutes"] * 2))
                if now - last <= allowed:
                    healthy += 1
        # This is a source-health proxy, explicitly conservative until stream-specific coverage exists.
        return min(0.90, 0.35 + 0.55 * healthy / len(enabled))

    def ingest_feed(self, source_id: str, raw: bytes, observed_at: datetime | None = None) -> dict:
        source = self._source(source_id)
        return self._ingest_items(source_id, source, parse_feed(raw), raw, observed_at)

    def ingest_official_page(self, source_id: str, raw: bytes, observed_at: datetime | None = None) -> dict:
        source = self._source(source_id)
        return self._ingest_items(source_id, source, parse_official_page(raw, source["endpoint"]), raw, observed_at)

    def _ingest_items(self, source_id: str, source: sqlite3.Row, items: list[dict], raw: bytes,
                      observed_at: datetime | None = None) -> dict:
        observed_at = observed_at or now_utc()
        run_id = uid()
        self.con.execute("INSERT INTO source_runs(id,source_id,started_at,status,raw_payload,payload_hash) VALUES(?,?,?,?,?,?)",
                         (run_id, source_id, iso(observed_at), "running", raw, digest(raw.decode("utf-8", errors="replace"))))
        counts = {"fetched": 0, "accepted": 0, "corroborating": 0, "duplicates": 0, "review": 0, "market": 0, "rejected": 0}
        try:
            counts["fetched"] = len(items)
            for item in items:
                result = self.ingest_item(source_id, item, json.dumps(item, ensure_ascii=False, sort_keys=True), observed_at)
                counts[result] += 1
            finished = now_utc()
            self.con.execute("""UPDATE source_runs SET finished_at=?,status='ok',fetched_count=?,accepted_count=?,duplicate_count=?,review_count=?,
                              rejected_count=?,market_count=?,corroborating_count=? WHERE id=?""",
                             (iso(finished), counts["fetched"], counts["accepted"], counts["duplicates"], counts["review"],
                              counts["rejected"], counts["market"], counts["corroborating"], run_id))
            stored = counts["accepted"] + counts["corroborating"] + counts["review"] + counts["market"] + counts["rejected"]
            self.con.execute("""UPDATE sources SET last_attempt_at=?,last_success_at=?,last_error=NULL,consecutive_errors=0,
                              observations_total=observations_total+? WHERE id=?""",
                             (iso(observed_at), iso(finished), stored, source_id))
            self.con.commit()
            return counts
        except Exception as exc:
            finished = now_utc()
            self.con.execute("UPDATE source_runs SET finished_at=?,status='error',error=? WHERE id=?", (iso(finished), str(exc), run_id))
            self.con.execute("""UPDATE sources SET last_attempt_at=?,last_error=?,consecutive_errors=consecutive_errors+1,
                              enabled=CASE WHEN consecutive_errors+1>=5 THEN 0 ELSE enabled END WHERE id=?""",
                             (iso(observed_at), str(exc), source_id))
            self.con.commit()
            raise

    def resolve_review(self, review_id: str, resolution: str, account_id: str | None = None) -> dict:
        review = self.con.execute(
            """SELECT r.*,o.source_id,o.title,o.body,o.canonical_url,o.published_at,o.observed_at
               FROM reviews r JOIN observations o ON o.id=r.observation_id
               WHERE r.id=? AND r.status='open'""", (review_id,),
        ).fetchone()
        if review is None:
            raise ValueError("unknown or already resolved review")
        predicted_row = self.con.execute(
            "SELECT quality_decision FROM observation_quality WHERE observation_id=?", (review["observation_id"],)
        ).fetchone()
        predicted = predicted_row[0] if predicted_row else "unknown"
        relation_review = review["reason_code"] in {"contradicts", "retracts", "corrects"}
        if resolution == "approve" and relation_review:
            self.con.execute("UPDATE observations SET status='correction_confirmed' WHERE id=?", (review["observation_id"],))
            self.con.execute("""UPDATE claim_relations SET status='resolved',resolved_at=?,resolution='confirmed'
                                WHERE observation_id=?""", (iso(now_utc()), review["observation_id"]))
            result = "confirmed:" + review["reason_code"]
        elif resolution == "approve":
            if not account_id or not self.con.execute("SELECT 1 FROM accounts WHERE id=? AND active=1", (account_id,)).fetchone():
                raise ValueError("approve requires a valid --account")
            source = self._source(review["source_id"])
            observed = datetime.fromisoformat(review["observed_at"])
            published = parse_datetime(review["published_at"], observed)
            signal_type, urgency, direction, product, relevance = self.classify(review["title"], review["body"])
            decay = TYPE_DECAY.get(signal_type, "OPERATIONAL")
            expires = published + timedelta(days=DECAY_DAYS[decay])
            if relevance < .35 or expires <= observed:
                raise ValueError("approved item fails relevance or expiry safety gate")
            source_score = self.source_score(source)
            coverage = self.coverage_cap(account_id, observed, review["source_id"])
            confidence = min(.95, coverage, .30 * source_score + .30 * relevance + .30 * .90 + .10)
            scoring = int(confidence >= .60 and relevance >= .50)
            action = 0  # shadow-only: no automated action may be enabled by this engine
            signal_id = uid()
            self.con.execute(
                """INSERT INTO signals(id,observation_id,account_id,signal_type,direction,urgency,title,summary,product_match,event_at,
                   decay_category,expires_at,relevance_score,source_score,confidence,coverage_cap,scoring_eligible,action_eligible,
                   promotion_rule_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (signal_id, review["observation_id"], account_id, signal_type, direction, urgency, review["title"], review["body"],
                 product, iso(published), decay, iso(expires), relevance, source_score, confidence, coverage, scoring, action,
                 PROMOTION_RULE_VERSION + "+human-review", iso(now_utc())),
            )
            self.con.execute("INSERT INTO signal_evidence(signal_id,observation_id,relationship,added_at) VALUES(?,?,?,?)",
                             (signal_id, review["observation_id"], "primary", iso(now_utc())))
            self.con.execute("UPDATE observations SET status='promoted',rejection_reason=NULL WHERE id=?", (review["observation_id"],))
            result = "approved:" + account_id
        elif resolution == "reject":
            self.con.execute("UPDATE observations SET status='rejected',rejection_reason='human_rejected' WHERE id=?", (review["observation_id"],))
            if relation_review:
                related = self.con.execute("SELECT related_signal_id FROM claim_relations WHERE observation_id=?",
                                           (review["observation_id"],)).fetchall()
                for row in related:
                    self.con.execute(
                        """UPDATE signals SET status='active',scoring_eligible=CASE WHEN confidence>=.60 AND relevance_score>=.50
                           AND expires_at>? THEN 1 ELSE 0 END WHERE id=?""", (iso(now_utc()), row[0]))
                self.con.execute("""UPDATE claim_relations SET status='resolved',resolved_at=?,resolution='rejected'
                                    WHERE observation_id=?""", (iso(now_utc()), review["observation_id"]))
            result = "rejected"
        else:
            raise ValueError("resolution must be approve or reject")
        self.con.execute("UPDATE reviews SET status='resolved',resolved_at=?,resolution=? WHERE id=?",
                         (iso(now_utc()), result, review_id))
        self.con.execute(
            "INSERT INTO quality_feedback(id,observation_id,review_id,predicted_decision,human_decision,reason,created_at) VALUES(?,?,?,?,?,?,?)",
            (uid(), review["observation_id"], review_id, predicted, resolution, review["reason_code"], iso(now_utc())),
        )
        self.con.commit()
        return {"review_id": review_id, "resolution": result}

    def quality_audit(self) -> dict:
        assessed = self.con.execute("SELECT COUNT(*) FROM observation_quality").fetchone()[0]
        incomplete = self.con.execute("SELECT COUNT(*) FROM observation_quality WHERE quality_decision='review_incomplete'").fetchone()[0]
        contested = self.con.execute("SELECT COUNT(*) FROM signals WHERE status='contested'").fetchone()[0]
        relations = self.con.execute("SELECT COUNT(*) FROM claim_relations").fetchone()[0]
        feedback = self.con.execute("SELECT predicted_decision,human_decision,COUNT(*) n FROM quality_feedback GROUP BY 1,2").fetchall()
        independent = self.con.execute("SELECT COUNT(DISTINCT independence_key) FROM observation_quality").fetchone()[0]
        average = self.con.execute(
            "SELECT COALESCE(AVG(completeness_score),0),COALESCE(AVG(materiality_score),0) FROM observation_quality"
        ).fetchone()
        reviewed = sum(row["n"] for row in feedback)
        agreements = self.con.execute(
            """SELECT COUNT(*) FROM quality_feedback WHERE
               (predicted_decision='review_incomplete' AND human_decision='reject') OR
               (predicted_decision IN ('contradicts','retracts','corrects') AND human_decision='approve')"""
        ).fetchone()[0]
        agreement_rate = agreements / reviewed if reviewed else 0.0
        return {
            "quality_gate_ready": assessed >= 100 and reviewed >= 100 and agreement_rate >= .90
                                  and independent >= 3 and contested == 0,
            "assessed_observations": assessed,
            "average_completeness": average[0], "average_materiality": average[1],
            "incomplete_reviews": incomplete, "contested_signals": contested,
            "claim_relations": relations, "independent_source_families": independent,
            "feedback_matrix": [dict(row) for row in feedback],
            "reviewed_calibration_sample": reviewed, "human_agreement_rate": agreement_rate,
            "minimum_calibration_sample": 100, "minimum_agreement_rate": .90,
        }

    def backfill_quality(self) -> dict:
        """Assess legacy observations without changing their promotion/review outcome."""
        from .quality import assess_quality
        rows = self.con.execute(
            """SELECT o.*,oa.account_id,oa.confidence attribution_confidence,a.canonical_name
               FROM observations o
               LEFT JOIN observation_accounts oa ON oa.observation_id=o.id AND oa.selected=1
               LEFT JOIN accounts a ON a.id=oa.account_id
               WHERE NOT EXISTS (SELECT 1 FROM observation_quality q WHERE q.observation_id=o.id)
               ORDER BY o.ingested_at"""
        ).fetchall()
        assessed = 0
        for row in rows:
            signal_type, _urgency, _direction, product, _relevance = self.classify(row["title"], row["body"])
            published = parse_datetime(row["published_at"], datetime.fromisoformat(row["observed_at"])) if row["published_at"] else None
            quality = assess_quality(source_id=row["source_id"], title=row["title"], body=row["body"],
                                     url=row["canonical_url"], published=published,
                                     account_name=row["canonical_name"], signal_type=signal_type,
                                     product_match=product, attribution_confidence=row["attribution_confidence"] or 0.0)
            self.con.execute(
                """INSERT OR IGNORE INTO observation_quality(observation_id,subject,action,object_text,event_date,location,
                   source_family,independence_key,completeness_score,materiality_score,quality_decision,missing_fields_json,
                   reasons_json,assessed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (row["id"], quality.subject, quality.action, quality.object_text, quality.event_date, quality.location,
                 quality.source_family, quality.independence_key, quality.completeness, quality.materiality, quality.decision,
                 json.dumps(quality.missing_fields), json.dumps(quality.reasons), iso(now_utc())),
            )
            assessed += 1
        self.con.commit()
        return {"assessed": assessed, "total_quality_rows": self.con.execute("SELECT COUNT(*) FROM observation_quality").fetchone()[0]}

    def ingest_item(self, source_id: str, item: dict, raw_payload: str, observed_at: datetime) -> str:
        from .quality import assess_quality, is_plausible_relation
        source = self._source(source_id)
        title = normalize_text(item.get("title", ""))
        body = normalize_text(item.get("body", ""))
        url = canonical_url(item.get("url"))
        published = parse_datetime(item.get("published"), observed_at)
        payload_hash = digest(source_id, item.get("native_id") or "", url or "", title, body)
        content_hash = digest(title.casefold(), body.casefold())
        duplicate = self.con.execute(
            "SELECT id FROM observations WHERE (source_id=? AND payload_hash=?) OR (? IS NOT NULL AND canonical_url=?) OR content_hash=? LIMIT 1",
            (source_id, payload_hash, url, url, content_hash),
        ).fetchone()
        if duplicate:
            return "duplicates"

        obs_id = uid()
        attribution = self.attribute(title, body, url)
        signal_type, urgency, direction, product, relevance = self.classify(title, body)
        account_name = None
        if attribution.account_id:
            row = self.con.execute("SELECT canonical_name FROM accounts WHERE id=?", (attribution.account_id,)).fetchone()
            account_name = row[0] if row else None
        quality = assess_quality(source_id=source_id, title=title, body=body, url=url, published=published,
                                 account_name=account_name, signal_type=signal_type, product_match=product,
                                 attribution_confidence=attribution.confidence)
        status = "pending"
        reason = None
        noise = any(re.search(pattern, f"{title} {body}", re.IGNORECASE) for pattern in NOISE_PATTERNS)
        if noise:
            status, reason = "rejected", "generic_market_content"
        elif relevance < 0.35:
            status, reason = "rejected", "low_relevance"
        elif attribution.ambiguous:
            status, reason = "review", "ambiguous_account"
        elif not attribution.account_id:
            review_text = f"{title} {body}".casefold()
            anonymous_target = bool(re.search(r"\b(saudi banks?|banking giant|unnamed bank)\b", review_text))
            if source_id not in {"official_sama_news", "gnews_sama"} and anonymous_target:
                status, reason = "review", "unattributed"
            else:
                status, reason = "market", "market_intelligence"

        # A target bank can have foreign subsidiaries with the same name. The
        # local engine is intentionally KSA-only, so explicit foreign-market
        # qualifiers are blocked before promotion.
        market_text = f"{title} {body}".casefold()
        foreign_context = any(re.search(rf"\b{re.escape(term)}\b", market_text) for term in OUT_OF_MARKET_TERMS)
        ksa_context = bool(re.search(r"\b(saudi|ksa|kingdom of saudi arabia)\b", market_text))
        if foreign_context and (attribution.account_id or not ksa_context):
            status, reason = "rejected", "out_of_market"

        if status == "pending" and quality.decision == "review_incomplete":
            status, reason = "review", "incomplete_signal"

        related_signal_id = None
        if attribution.account_id and quality.correction_type:
            candidates = self.con.execute(
                """SELECT id,title,signal_type,event_at FROM signals WHERE account_id=? AND status='active'
                   ORDER BY event_at DESC LIMIT 25""", (attribution.account_id,),
            ).fetchall()
            related = next((candidate for candidate in candidates if is_plausible_relation(
                title, candidate["title"], signal_type, candidate["signal_type"], published,
                datetime.fromisoformat(candidate["event_at"]))), None)
            if related:
                related_signal_id = related["id"]
                status, reason = "review", quality.correction_type

        decay = TYPE_DECAY.get(signal_type, "OPERATIONAL")
        expires = published + timedelta(days=DECAY_DAYS[decay])
        if attribution.account_id and expires <= observed_at:
            status, reason = "rejected", "expired_event"

        # Collapse syndicated aggregator coverage of the same account/event.
        # Google News commonly emits several publishers for one announcement;
        # retain one signal per account/type/event-date in this shadow engine.
        corroborates_signal_id = None
        if attribution.account_id and status == "pending":
            recent = self.con.execute(
                """SELECT s.id,s.title,s.event_at FROM signals s
                   WHERE s.account_id=? AND s.signal_type=? AND ABS(julianday(s.event_at)-julianday(?))<=2""",
                (attribution.account_id, signal_type, iso(published)),
            ).fetchall()
            current_tokens = headline_tokens(title)
            current_arabic = bool(re.search(r"[\u0600-\u06ff]", title))
            for candidate in recent:
                prior_tokens = headline_tokens(candidate["title"])
                union = current_tokens | prior_tokens
                similarity = len(current_tokens & prior_tokens) / len(union) if union else 0.0
                prior_arabic = bool(re.search(r"[\u0600-\u06ff]", candidate["title"]))
                cross_language_same_day = current_arabic != prior_arabic and published.date() == datetime.fromisoformat(candidate["event_at"]).date()
                if similarity >= .18 or cross_language_same_day:
                    status, reason = "corroborating", "corroborating_evidence"
                    corroborates_signal_id = candidate["id"]
                    break

        self.con.execute(
            """INSERT INTO observations(id,source_id,source_native_id,canonical_url,title,body,language,published_at,observed_at,ingested_at,
               raw_payload,payload_hash,content_hash,parser_version,status,rejection_reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (obs_id, source_id, item.get("native_id"), url, title, body, source["language"], iso(published), iso(observed_at), iso(now_utc()),
             raw_payload, payload_hash, content_hash, PARSER_VERSION, status, reason),
        )
        self.con.execute(
            """INSERT INTO observation_quality(observation_id,subject,action,object_text,event_date,location,source_family,
               independence_key,completeness_score,materiality_score,quality_decision,missing_fields_json,reasons_json,assessed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (obs_id, quality.subject, quality.action, quality.object_text, quality.event_date, quality.location,
             quality.source_family, quality.independence_key, quality.completeness, quality.materiality, quality.decision,
             json.dumps(quality.missing_fields), json.dumps(quality.reasons), iso(now_utc())),
        )
        if related_signal_id:
            self.con.execute(
                """INSERT INTO claim_relations(id,observation_id,related_signal_id,relation_type,confidence,created_at,status)
                   VALUES(?,?,?,?,?,?,'pending')""",
                (uid(), obs_id, related_signal_id, quality.correction_type, min(.95, quality.completeness), iso(now_utc())),
            )
            self.con.execute(
                "UPDATE signals SET status='contested',scoring_eligible=0,action_eligible=0 WHERE id=?",
                (related_signal_id,),
            )
        for account_id, confidence, reasons in attribution.candidates:
            self.con.execute("INSERT INTO observation_accounts VALUES(?,?,?,?,?)",
                             (obs_id, account_id, confidence, json.dumps(reasons), int(account_id == attribution.account_id)))

        if status == "review":
            self.con.execute("INSERT INTO reviews(id,observation_id,reason_code,detail,created_at) VALUES(?,?,?,?,?)",
                             (uid(), obs_id, reason, json.dumps(attribution.candidates), iso(now_utc())))
            self.con.commit()
            return "review"
        if status == "market":
            self.con.commit()
            return "market"
        if status == "corroborating":
            self.con.execute("INSERT INTO signal_evidence(signal_id,observation_id,relationship,added_at) VALUES(?,?,?,?)",
                             (corroborates_signal_id, obs_id, "corroborating", iso(now_utc())))
            prior_key_row = self.con.execute(
                """SELECT q.independence_key FROM signal_evidence e JOIN observation_quality q ON q.observation_id=e.observation_id
                   WHERE e.signal_id=? AND e.relationship='primary' LIMIT 1""", (corroborates_signal_id,),
            ).fetchone()
            independent = not prior_key_row or prior_key_row[0] != quality.independence_key
            increment = .05 if independent else 0.0
            self.con.execute("""UPDATE signals SET confidence=MIN(0.95,coverage_cap,confidence+?),
                              scoring_eligible=CASE WHEN MIN(0.95,coverage_cap,confidence+?)>=0.60 AND relevance_score>=0.50
                              AND expires_at>? THEN 1 ELSE scoring_eligible END WHERE id=?""",
                             (increment, increment, iso(observed_at), corroborates_signal_id))
            self.con.commit()
            return "corroborating"
        if status == "rejected":
            self.con.commit()
            return "rejected"

        source_score = self.source_score(source)
        coverage = self.coverage_cap(attribution.account_id, observed_at, source_id)
        freshness = 1.0 if published >= observed_at - timedelta(days=7) else 0.8 if published >= observed_at - timedelta(days=30) else 0.5
        confidence = min(0.95, coverage, 0.30 * attribution.confidence + 0.25 * source_score + 0.20 * relevance +
                         0.10 * freshness + 0.10 * quality.completeness + 0.05 * quality.materiality)
        scoring_eligible = int(confidence >= 0.60 and relevance >= 0.50 and quality.completeness >= .70 and
                               quality.materiality >= .45 and expires > observed_at)
        action_eligible = 0  # shadow-only fail-safe
        signal_id = uid()
        self.con.execute(
            """INSERT INTO signals(id,observation_id,account_id,signal_type,direction,urgency,title,summary,product_match,event_at,
               decay_category,expires_at,relevance_score,source_score,confidence,coverage_cap,scoring_eligible,action_eligible,
               promotion_rule_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (signal_id, obs_id, attribution.account_id, signal_type, direction, urgency, title, body, product, iso(published), decay,
             iso(expires), relevance, source_score, confidence, coverage, scoring_eligible, action_eligible, PROMOTION_RULE_VERSION, iso(now_utc())),
        )
        self.con.execute("UPDATE observations SET status='promoted' WHERE id=?", (obs_id,))
        self.con.execute("INSERT INTO signal_evidence(signal_id,observation_id,relationship,added_at) VALUES(?,?,?,?)",
                         (signal_id, obs_id, "primary", iso(now_utc())))
        self.con.commit()
        return "accepted"

    def status(self) -> dict:
        def count(table: str, where: str = "1=1") -> int:
            return self.con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]
        return {
            "accounts": count("accounts"),
            "sources": count("sources"),
            "observations": count("observations"),
            "promoted_signals": count("signals", "status='active'"),
            "open_reviews": count("reviews", "status='open'"),
            "scoring_eligible": count("signals", "scoring_eligible=1"),
            "action_eligible": count("signals", "action_eligible=1"),
            "market_intelligence": count("observations", "status='market'"),
            "corroborating_evidence": count("observations", "status='corroborating'"),
        }
