"""
scan_signals.py
────────────────
Scans KSA banking/fintech news feeds, scores relevance using Gemini,
and saves signals to the dashboard Intelligence tab.

Run from decimal_abm folder:
  python scan_signals.py
"""
import os
import sys
import sqlite3
import time
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / "abm_engine" / ".env")

DB_PATH = ROOT / "abm_engine.db"
API_KEY = os.environ.get("GEMINI_API_KEY", "")

if not API_KEY:
    print("  ERROR: No GEMINI_API_KEY found in abm_engine/.env")
    sys.exit(1)

# ── RSS feed sources ────────────────────────────────────────────────────────
FEEDS = [
    {
        "name": "Google News - Saudi Banking",
        "url": "https://news.google.com/rss/search?q=saudi+arabia+banking+digital+transformation&hl=en",
    },
    {
        "name": "Google News - SAMA Regulations",
        "url": "https://news.google.com/rss/search?q=SAMA+Saudi+Central+Bank+fintech&hl=en",
    },
    {
        "name": "Google News - KSA Fintech",
        "url": "https://news.google.com/rss/search?q=saudi+fintech+lending+open+banking&hl=en",
    },
    {
        "name": "Google News - SNB Al Rajhi Riyad Bank",
        "url": "https://news.google.com/rss/search?q=SNB+OR+%22Al+Rajhi+Bank%22+OR+%22Riyad+Bank%22+digital&hl=en",
    },
    {
        "name": "Google News - KSA Digital Lending",
        "url": "https://news.google.com/rss/search?q=saudi+digital+lending+loan+origination&hl=en",
    },
]

# Target accounts for relevance matching
TARGET_KEYWORDS = [
    "SNB", "Saudi National Bank", "Al Rajhi", "Riyad Bank", "SABB", "Alinma",
    "Bank Albilad", "Arab National Bank", "ANB", "Banque Saudi Fransi", "BSF",
    "SAMA", "Saudi Central Bank", "Vision 2030", "PDPL", "open banking",
    "digital lending", "loan origination", "fintech", "neobank", "BaaS",
    "Lendo", "Hala", "Erad", "Lean Technologies", "Funding Souq",
    "Vahana", "Decimal", "API gateway", "core banking", "Mambu", "Temenos",
]


def fetch_feeds():
    """Fetch and parse all RSS feeds."""
    import feedparser
    all_entries = []

    for feed_info in FEEDS:
        print(f"  scan  {feed_info['name']}...", end=" ", flush=True)
        try:
            feed = feedparser.parse(feed_info["url"])
            entries = feed.entries[:5]  # top 5 per feed
            for entry in entries:
                all_entries.append({
                    "source": feed_info["name"],
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "summary": entry.get("summary", entry.get("description", ""))[:500],
                    "published": entry.get("published", ""),
                })
            print(f"{len(entries)} items")
        except Exception as e:
            print(f"FAIL: {e}")
            continue

    return all_entries


def score_relevance(entries):
    """Use Gemini to score relevance of news items."""
    import google.generativeai as genai

    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("gemini-2.0-flash")

    scored = []

    # Batch entries to reduce API calls (5 at a time)
    batch_size = 5
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]

        news_list = ""
        for j, entry in enumerate(batch):
            news_list += f"\n[{j+1}] {entry['title']}\n    {entry['summary'][:200]}\n"

        prompt = f"""You are an intelligence analyst for Decimal Technologies, a fintech company 
selling digital lending (Vahana), API integration (vHub), and open banking solutions to 
Saudi Arabian banks and financial institutions.

Score these news items for business relevance. For each, respond with:
- A relevance level: HIGH, MEDIUM, or LOW
- A one-line summary of why it matters for Decimal's sales pipeline

Target accounts: SNB, Al Rajhi Bank, Riyad Bank, SABB, Alinma, Bank Albilad, ANB, BSF
Key topics: digital lending, open banking, SAMA regulations, PDPL, API integration, 
core banking modernization, Vision 2030 fintech initiatives

News items:{news_list}

Respond in this exact format for each item (one per line):
[1] HIGH | Summary of relevance
[2] LOW | Summary of relevance
... and so on"""

        try:
            print(f"  scoring batch {i//batch_size + 1}...", end=" ", flush=True)
            response = model.generate_content(prompt)
            lines = response.text.strip().split("\n")

            for j, entry in enumerate(batch):
                relevance = "LOW"
                rel_summary = ""

                # Find matching line
                for line in lines:
                    if f"[{j+1}]" in line:
                        parts = line.split("|", 1)
                        if len(parts) == 2:
                            level_part = parts[0].upper()
                            rel_summary = parts[1].strip()
                            if "HIGH" in level_part:
                                relevance = "HIGH"
                            elif "MEDIUM" in level_part:
                                relevance = "MEDIUM"
                        break

                entry["relevance"] = relevance
                entry["rel_summary"] = rel_summary
                scored.append(entry)

            print("OK")
            time.sleep(1)  # rate limit courtesy

        except Exception as e:
            print(f"FAIL: {e}")
            for entry in batch:
                entry["relevance"] = "UNKNOWN"
                entry["rel_summary"] = ""
                scored.append(entry)

    return scored


def save_signals(signals):
    """Save scored signals to database."""
    conn = sqlite3.connect(str(DB_PATH))

    # Ensure signals table exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS signals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT,
            title       TEXT,
            summary     TEXT,
            url         TEXT,
            relevance   TEXT,
            created_at  TEXT DEFAULT (datetime('now')),
            is_read     INTEGER DEFAULT 0
        )
    """)

    new_count = 0
    for s in signals:
        # Skip LOW relevance
        if s.get("relevance") == "LOW":
            continue

        # Skip duplicates (by title)
        exists = conn.execute(
            "SELECT id FROM signals WHERE title = ?", (s["title"],)
        ).fetchone()
        if exists:
            continue

        summary_text = s.get("rel_summary", "") or s.get("summary", "")
        conn.execute("""
            INSERT INTO signals (source, title, summary, url, relevance)
            VALUES (?, ?, ?, ?, ?)
        """, (s["source"], s["title"], summary_text, s["url"], s["relevance"]))
        new_count += 1

    conn.commit()
    conn.close()
    return new_count


# ── Main ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n  ╔══════════════════════════════════════════════╗")
    print("  ║  ABM Signal Scanner                          ║")
    print("  ╚══════════════════════════════════════════════╝\n")

    print("  Step 1: Fetching news feeds...\n")
    entries = fetch_feeds()
    print(f"\n  Fetched {len(entries)} total items\n")

    if not entries:
        print("  No entries found. Check your internet connection.")
        sys.exit(1)

    print("  Step 2: Scoring relevance with Gemini...\n")
    scored = score_relevance(entries)

    high = sum(1 for s in scored if s.get("relevance") == "HIGH")
    med = sum(1 for s in scored if s.get("relevance") == "MEDIUM")
    low = sum(1 for s in scored if s.get("relevance") == "LOW")
    print(f"\n  Results: {high} HIGH | {med} MEDIUM | {low} LOW\n")

    print("  Step 3: Saving to database...\n")
    saved = save_signals(scored)

    print(f"  ========================================")
    print(f"  Saved {saved} new signals (HIGH + MEDIUM only)")
    print(f"  Open http://localhost:5000/intelligence to view")
    print(f"  ========================================\n")
