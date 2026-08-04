"""Local catalog derived from the uploaded signal scanner and source registry.

Only public, credential-free Google News RSS queries are enabled for the first
live shadow run. SAMA and bank-page adapters require separate HTML/RSS parser
verification and are deliberately not guessed here.
"""
from __future__ import annotations

from urllib.parse import quote_plus


ACCOUNTS = [
    {"id": "snb", "name": "Saudi National Bank", "aliases": ["SNB", "Alahli", "The Saudi National Bank", "البنك الأهلي السعودي", "الاهلي"], "domains": ["alahli.com"], "tickers": ["1180"]},
    {"id": "al_rajhi", "name": "Al Rajhi Bank", "aliases": ["Al Rajhi", "مصرف الراجحي", "الراجحي"], "domains": ["alrajhibank.com.sa"], "tickers": ["1120"]},
    {"id": "riyad", "name": "Riyad Bank", "aliases": ["Riyad Bank", "بنك الرياض"], "domains": ["riyadbank.com"], "tickers": ["1010"]},
    {"id": "sab", "name": "Saudi Awwal Bank", "aliases": ["SAB", "SABB", "Saudi British Bank", "البنك السعودي الأول"], "domains": ["sab.com"], "tickers": ["1060"]},
    {"id": "alinma", "name": "Alinma Bank", "aliases": ["Alinma", "مصرف الإنماء", "الانماء"], "domains": ["alinma.com"], "tickers": ["1150"]},
    {"id": "anb", "name": "Arab National Bank", "aliases": ["ANB", "البنك العربي الوطني"], "domains": ["anb.com.sa"], "tickers": ["1080"]},
    {"id": "baj", "name": "Bank AlJazira", "aliases": ["Bank Al Jazira", "BAJ", "بنك الجزيرة"], "domains": ["aljazirabank.com.sa"], "tickers": ["1020"]},
    {"id": "albilad", "name": "Bank Albilad", "aliases": ["Bank Al Bilad", "بنك البلاد"], "domains": ["bankalbilad.com"], "tickers": ["1140"]},
    {"id": "bsf", "name": "Banque Saudi Fransi", "aliases": ["BSF", "Saudi Fransi Bank", "البنك السعودي الفرنسي"], "domains": ["bsf.sa"], "tickers": ["1050"]},
    {"id": "stc_bank", "name": "STC Bank", "aliases": ["STC Pay", "stc pay", "بنك اس تي سي"], "domains": ["stcbank.com.sa"], "tickers": []},
    {"id": "d360", "name": "D360 Bank", "aliases": ["D360", "بنك D360", "بنك دي 360"], "domains": ["d360bank.com"], "tickers": []},
]


def google_news_url(query: str, language: str = "en") -> str:
    if language == "ar":
        return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=ar&gl=SA&ceid=SA:ar"
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&hl=en&gl=SA&ceid=SA:en"


SOURCES = [
    {
        "id": "official_sama_news", "name": "Official SAMA News",
        "kind": "rss", "language": "en", "endpoint": google_news_url('site:sama.gov.sa (regulation OR fintech OR banking OR payments OR licensing)'),
        "e": .92, "p": .90, "i": .75, "s": .90, "bias": .08, "interval": 360,
    },
    {
        "id": "official_saudi_exchange", "name": "Official Saudi Exchange Announcements",
        "kind": "rss", "language": "en", "endpoint": google_news_url('site:saudiexchange.sa (1010 OR 1020 OR 1050 OR 1060 OR 1080 OR 1120 OR 1140 OR 1150 OR 1180)'),
        "e": .92, "p": .90, "i": .80, "s": .90, "bias": .08, "interval": 180,
    },
    {
        "id": "gnews_saudi_banking", "name": "Google News - Saudi Banking",
        "kind": "rss",
        "language": "en", "endpoint": google_news_url('Saudi Arabia banking "digital transformation"'),
        "e": .70, "p": .50, "i": .70, "s": .60, "bias": .25, "interval": 240,
    },
    {
        "id": "gnews_sama", "name": "Google News - SAMA Regulations",
        "kind": "rss",
        "language": "en", "endpoint": google_news_url('SAMA "Saudi Central Bank" fintech regulation'),
        "e": .70, "p": .50, "i": .70, "s": .70, "bias": .20, "interval": 240,
    },
    {
        "id": "gnews_ksa_fintech", "name": "Google News - KSA Fintech",
        "kind": "rss",
        "language": "en", "endpoint": google_news_url('Saudi fintech lending "open banking"'),
        "e": .70, "p": .50, "i": .70, "s": .60, "bias": .25, "interval": 240,
    },
    {
        "id": "gnews_target_banks", "name": "Google News - Target Banks",
        "kind": "rss",
        "language": "en", "endpoint": google_news_url('("Saudi National Bank" OR "Al Rajhi Bank" OR "Riyad Bank" OR "Saudi Awwal Bank" OR "Alinma Bank" OR "Arab National Bank" OR "Bank AlJazira" OR "Bank Albilad" OR "Banque Saudi Fransi" OR "STC Bank" OR "D360 Bank")'),
        "e": .70, "p": .50, "i": .70, "s": .75, "bias": .25, "interval": 120,
    },
    {
        "id": "official_target_banks", "name": "Official Target Bank Domains",
        "kind": "rss", "language": "en", "endpoint": google_news_url('(site:alahli.com OR site:alrajhibank.com.sa OR site:riyadbank.com OR site:sab.com OR site:alinma.com OR site:anb.com.sa OR site:aljazirabank.com.sa OR site:bankalbilad.com OR site:bsf.sa OR site:stcbank.com.sa OR site:d360bank.com)'),
        "e": .90, "p": .88, "i": .72, "s": .92, "bias": .10, "interval": 360,
    },
    {
        "id": "gnews_digital_lending", "name": "Google News - KSA Digital Lending",
        "kind": "rss",
        "language": "en", "endpoint": google_news_url('Saudi "digital lending" "loan origination"'),
        "e": .70, "p": .50, "i": .70, "s": .75, "bias": .25, "interval": 240,
    },
    {
        "id": "gnews_banking_ar", "name": "Google News - Saudi Banking Arabic",
        "kind": "rss",
        "language": "ar", "endpoint": google_news_url('البنوك السعودية التحول الرقمي المصرفية المفتوحة', "ar"),
        "e": .70, "p": .55, "i": .70, "s": .70, "bias": .25, "interval": 240,
    },
]
