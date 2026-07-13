"""
abm_engine/signals/monitor.py
──────────────────────────────
Intelligence engine — monitors 6 sources continuously.
Saves everything to news_items + signals tables.
Dashboard shows the intelligence feed in real time.
"""
from __future__ import annotations
import os, json, time
from datetime import datetime
from loguru import logger
import httpx
import anthropic

from ..database.db import (
    save_signal, save_news_item, get_all_accounts, get_all_contacts
)

# ── Target institutions ───────────────────────────────────────────────────────
BANK_TARGETS = [
    "Al Rajhi Bank","Bank Albilad","Alinma Bank","SNB","Saudi National Bank",
    "Riyad Bank","SABB","Banque Saudi Fransi","Arab National Bank",
    "STC Bank","STC Pay","D360 Bank","Vision Bank","Bank AlJazira",
    "Gulf International Bank",
]
FI_TARGETS = [
    "Tamara","Tabby","Hala","Lendo","Erad","Lean Technologies",
    "Funding Souq","Geidea","HyperPay","Abdul Latif Jameel Finance",
    "Saudi Real Estate Refinance","Manafa","Scopeer",
]
VENDOR_TARGETS = [
    "Mambu","Efigence","audax","Ripple","Backbase","ITC Infotech",
    "Tarabut","KPMG",
]
ALL_TARGETS = BANK_TARGETS + FI_TARGETS + VENDOR_TARGETS

SAMA_FEEDS = [
    "https://www.sama.gov.sa/en-US/News/Pages/NewsListRSS.aspx",
    "https://www.sama.gov.sa/en-US/Laws/Pages/LawsAndRegulationsRSS.aspx",
]


class SAMAMonitor:
    """Polls SAMA RSS for regulatory announcements."""

    def run(self) -> int:
        try:
            import feedparser
        except ImportError:
            return 0

        saved = 0
        for url in SAMA_FEEDS:
            try:
                feed = feedparser.parse(url)
                for entry in feed.entries[:20]:
                    title   = entry.get("title","")
                    summary = entry.get("summary","")
                    link    = entry.get("link","")
                    text    = (title+" "+summary).lower()

                    if any(k in text for k in ["license","licensed","digital bank","رخصة","بنك رقمي"]):
                        priority, impact, stype = "P1", 25, "NEW_LICENSE"
                    elif any(k in text for k in ["circular","regulation","framework","open banking","تعميم"]):
                        priority, impact, stype = "P2", 15, "SAMA_DEADLINE"
                    else:
                        priority, impact, stype = "P3", 5, "NEWS"

                    save_signal("ALL_BANKS", stype, priority, title[:200],
                                summary[:500], link, "SAMA", impact)
                    save_news_item("SAMA", title[:200], summary[:400] or title,
                                   institution="SAMA", source_url=link,
                                   source_name="SAMA", relevance_score=8)
                    saved += 1
            except Exception as e:
                logger.debug("SAMA feed error: {}", e)

        return saved


class NewsMonitor:
    """Uses Claude web search for institution and vendor news."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def _search(self, institution: str, category: str) -> list[dict]:
        cat_desc = {
            "BANK_FI": "banking/fintech news: leadership hires, digital initiatives, funding, SAMA actions",
            "VENDOR":  "company news: partnerships, product launches, leadership changes, financial results",
        }.get(category, "recent news")

        prompt = f"""Search for recent news (last 60 days) about "{institution}".
Focus on: {cat_desc}

Return ONLY a JSON array. Each item:
- "headline": title (max 100 chars)
- "summary": 1-2 sentences
- "signal_type": LEADERSHIP_HIRE | FUNDING_ROUND | DIGITAL_INITIATIVE | PARTNERSHIP | PRODUCT_LAUNCH | NEWS
- "priority": P1 (leadership hire/license) | P2 (funding/digital/partnership) | P3 (other)
- "source": publication name
- "relevance": 1-10 (how relevant to a B2B fintech platform selling to this company)

If nothing found, return [].
Return ONLY the JSON array."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6", max_tokens=1024,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}]
            )
            text = "".join(b.text for b in response.content if hasattr(b, "text"))
            text = text.strip()
            if "[" in text:
                text = text[text.index("["):text.rindex("]")+1]
            return json.loads(text)
        except Exception as e:
            logger.debug("News search error for {}: {}", institution, e)
            return []

    def run(self, batch_size=5) -> int:
        saved = 0
        banks_and_fis = BANK_TARGETS + FI_TARGETS
        vendors = VENDOR_TARGETS

        for i, institution in enumerate(banks_and_fis):
            if i > 0 and i % batch_size == 0:
                time.sleep(8)
            items = self._search(institution, "BANK_FI")
            for item in items:
                p_map = {"P1": 25, "P2": 15, "P3": 5}
                save_signal(institution,
                    item.get("signal_type","NEWS"), item.get("priority","P3"),
                    item.get("headline","")[:200], item.get("summary","")[:500],
                    source_name=item.get("source",""),
                    score_impact=p_map.get(item.get("priority","P3"),5))
                save_news_item("BANK_FI",
                    item.get("headline","")[:200], item.get("summary","") or item.get("headline",""),
                    institution=institution, source_name=item.get("source",""),
                    relevance_score=int(item.get("relevance",5)))
                saved += 1

        for i, institution in enumerate(vendors):
            if i > 0 and i % batch_size == 0:
                time.sleep(8)
            items = self._search(institution, "VENDOR")
            for item in items:
                save_news_item("VENDOR",
                    item.get("headline","")[:200], item.get("summary","") or item.get("headline",""),
                    institution=institution, source_name=item.get("source",""),
                    relevance_score=int(item.get("relevance",4)))
                saved += 1

        return saved


class LeadershipMonitor:
    """Detects leadership changes at target orgs."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)

    def run(self) -> int:
        saved = 0
        orgs = ALL_TARGETS[:10]  # top 10 most important per run

        prompt = f"""Search LinkedIn and news for recent leadership changes (last 90 days) at these organizations: {", ".join(orgs)}.

Focus on: new CTO, CDO, CEO, Head of Digital, Head of Retail appointed.

Return ONLY JSON array. Each item:
- "institution": org name
- "person_name": full name
- "new_role": their new title
- "headline": one sentence
- "source": where found

Return [] if nothing found."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-6", max_tokens=1024,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                messages=[{"role": "user", "content": prompt}]
            )
            text = "".join(b.text for b in response.content if hasattr(b, "text"))
            if "[" in text:
                text = text[text.index("["):text.rindex("]")+1]
            items = json.loads(text)
            for item in items:
                save_signal(
                    item.get("institution",""), "LEADERSHIP_HIRE", "P1",
                    item.get("headline","")[:200],
                    f"{item.get('person_name','')} appointed as {item.get('new_role','')}",
                    source_name=item.get("source",""), score_impact=25
                )
                save_news_item("LEADERSHIP",
                    item.get("headline","")[:200],
                    f"{item.get('person_name','')} appointed as {item.get('new_role','')} at {item.get('institution','')}",
                    institution=item.get("institution",""),
                    contact_name=item.get("person_name",""),
                    source_name=item.get("source",""),
                    relevance_score=9)
                saved += 1
        except Exception as e:
            logger.debug("Leadership monitor error: {}", e)

        return saved


class HubSpotCRMMonitor:
    """Monitors HubSpot for deal stage changes and contact updates."""

    def __init__(self, hubspot_api_key: str):
        self.api_key = hubspot_api_key
        self.headers = {"Authorization": f"Bearer {hubspot_api_key}"}

    def run(self) -> int:
        if not self.api_key:
            return 0
        saved = 0
        try:
            with httpx.Client(timeout=15) as client:
                # Get recently modified deals
                r = client.get(
                    "https://api.hubapi.com/crm/v3/objects/deals",
                    params={"limit": 20, "properties": "dealname,dealstage,amount,closedate"},
                    headers=self.headers
                )
                if r.status_code == 200:
                    for deal in r.json().get("results", []):
                        props = deal.get("properties", {})
                        stage = props.get("dealstage","")
                        name  = props.get("dealname","")
                        if stage and name:
                            save_news_item("INTERNAL",
                                f"Deal stage update: {name}",
                                f"HubSpot deal '{name}' moved to stage: {stage}",
                                source_name="HubSpot CRM",
                                relevance_score=7)
                            saved += 1
        except Exception as e:
            logger.debug("HubSpot CRM monitor error: {}", e)
        return saved


class SignalMonitor:
    """Master monitor — runs all sub-monitors."""

    def __init__(self, api_key: str):
        self.sama       = SAMAMonitor()
        self.news       = NewsMonitor(api_key=api_key)
        self.leadership = LeadershipMonitor(api_key=api_key)
        self.hubspot    = HubSpotCRMMonitor(
            hubspot_api_key=os.environ.get("HUBSPOT_API_KEY","")
        )

    def run_full(self) -> dict:
        logger.info("═══ Intelligence Monitor Started ═══")
        s = self.sama.run()
        n = self.news.run()
        l = self.leadership.run()
        h = self.hubspot.run()
        result = {"sama": s, "news": n, "leadership": l, "hubspot": h,
                  "total": s+n+l+h}
        logger.info("═══ Monitor Complete: {} ═══", result)
        return result

    def run_quick(self) -> dict:
        """Quick run — SAMA + leadership only (every hour)."""
        s = self.sama.run()
        l = self.leadership.run()
        return {"sama": s, "leadership": l, "total": s+l}
