"""
abm_engine/__main__.py
───────────────────────
CLI entry point for the complete 7-layer ABM engine.

Commands:
  setup      Load contacts from Excel + run initial scoring
  run        Run one outreach cycle now
  signals    Run signal detection now (all sources)
  score      Re-score all contacts now
  report     Generate this week's KPI report
  start      Start the full automatic scheduler (keep terminal open)
  webhook    Start reply detection server
  status     Full pipeline status dashboard
  test       Test full pipeline on 1 contact (no sends)
"""
from __future__ import annotations
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Explicit path — plain load_dotenv() only searches cwd and its ancestors, so it
# never finds .env when invoked as `python -m abm_engine` from the parent directory
# (which is required for -m to resolve this package at all).
load_dotenv(Path(__file__).resolve().parent / ".env")

# The CLI prints emoji (✅ ❌ 🔍 etc.) — Windows consoles default to cp1252, which
# can't encode them and crashes the whole command. Force UTF-8 stdout/stderr.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from loguru import logger
logger.remove()
logger.add(sys.stderr,
    format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    level=os.environ.get("LOG_LEVEL", "INFO"))
logger.add("logs/engine.log", rotation="10 MB", retention="30 days", level="DEBUG")

from .database.db import init_db


def cmd_setup():
    init_db()
    from .core.loader import load_contacts_from_excel
    from .scoring.engine import ScoringEngine

    excel = os.environ.get("CONTACTS_EXCEL_PATH", "./data/abm_contacts.xlsx")
    if not __import__("pathlib").Path(excel).exists():
        print(f"\n❌  Excel not found: {excel}\n    Set CONTACTS_EXCEL_PATH in .env\n")
        sys.exit(1)

    n = load_contacts_from_excel(excel)
    print(f"\n✅  Loaded {n} contacts")

    print("   Running initial scoring...")
    engine = ScoringEngine()
    result = engine.run()
    print(f"   Scored: {result['contacts_scored']} contacts | HOT upgrades: {result['upgraded']}\n")


def cmd_run():
    init_db()
    from .core.orchestrator import Orchestrator
    print("\n▶  Running outreach cycle...")
    result = Orchestrator().run()
    print(f"\n✅  Done: {result}\n")


def cmd_signals():
    init_db()
    from .signals.monitor import SignalMonitor
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    print("\n🔍  Running signal detection...")
    result = SignalMonitor(api_key=api_key).run_full()
    print(f"\n✅  Signals detected: {result}\n")


def cmd_score():
    init_db()
    from .scoring.engine import ScoringEngine
    print("\n📊  Running scoring engine...")
    result = ScoringEngine().run()
    print(f"\n✅  {result}\n")


def cmd_report():
    init_db()
    from .reporting.kpi import KPIReporter
    print("\n📈  Generating KPI report...")
    result = KPIReporter().run()
    print(f"\n✅  Report sent: {result}\n")


def cmd_start():
    from .scheduler.runner import start_scheduler
    start_scheduler()


def cmd_webhook():
    from .channels.webhook_server import start_webhook_server
    start_webhook_server()


def cmd_status():
    init_db()
    from .database.db import get_conn
    conn = get_conn()

    print("\n" + "═" * 65)
    print("  DECIMAL ABM ENGINE — FULL PIPELINE STATUS")
    print("═" * 65)

    # Contact pipeline
    tiers = conn.execute("""
        SELECT tier,
            COUNT(*) total,
            SUM(CASE WHEN current_touch=0 THEN 1 ELSE 0 END) not_started,
            SUM(CASE WHEN current_touch>0 AND current_touch<5 THEN 1 ELSE 0 END) in_progress,
            SUM(CASE WHEN current_touch>=5 THEN 1 ELSE 0 END) completed,
            SUM(CASE WHEN replied=1 THEN 1 ELSE 0 END) replied
        FROM contacts WHERE is_active=1
        GROUP BY tier
        ORDER BY CASE tier WHEN 'HOT' THEN 1 WHEN 'WARM' THEN 2 ELSE 3 END
    """).fetchall()

    print(f"\n{'TIER':<8} {'TOTAL':>6} {'NOT STARTED':>12} {'IN PROGRESS':>12} {'DONE':>6} {'REPLIED':>8}")
    print("-" * 55)
    for r in tiers:
        print(f"{r['tier']:<8} {r['total']:>6} {r['not_started']:>12} {r['in_progress']:>12} {r['completed']:>6} {r['replied']:>8}")

    # Signals
    sig_counts = conn.execute("""
        SELECT priority, COUNT(*) n FROM signals
        WHERE detected_at > datetime('now', '-7 days')
        GROUP BY priority ORDER BY priority
    """).fetchall()
    print(f"\nSIGNALS (last 7 days):")
    for r in sig_counts:
        print(f"  {r['priority']}: {r['n']}")

    # Touch status
    touch_counts = conn.execute("""
        SELECT status, COUNT(*) n FROM touch_records GROUP BY status
    """).fetchall()
    print(f"\nTOUCH RECORDS:")
    for r in touch_counts:
        print(f"  {r['status']:<12}: {r['n']}")

    # Recent KPIs
    kpi = conn.execute("""
        SELECT * FROM kpi_snapshots ORDER BY week_start DESC LIMIT 1
    """).fetchone()
    if kpi:
        print(f"\nLAST KPI WEEK ({kpi['week_start']}):")
        print(f"  Sent: {kpi['touches_sent']} | Replies: {kpi['replies_received']} | Eng rate: {kpi['engagement_rate_pct']}%")
        print(f"  Meetings: {kpi['meetings_booked']} | Pipeline: ${kpi['pipeline_value_usd']:,}")

    print("\n" + "═" * 65 + "\n")


def cmd_test():
    init_db()
    from .database.db import get_conn
    conn = get_conn()
    row  = conn.execute(
        "SELECT * FROM contacts WHERE is_active=1 ORDER BY priority_score DESC LIMIT 1"
    ).fetchone()

    if not row:
        print("\n❌  No contacts found. Run `setup` first.\n")
        sys.exit(1)

    from .core.orchestrator import Orchestrator
    contact = Orchestrator._row_to_contact(dict(row))

    print(f"\n🔬  Test run: {contact.full_name} @ {contact.institution}")
    print(f"    Tier: {contact.tier} | Score: {contact.priority_score}")
    print(f"    Persona: {contact.persona} | Segment: {contact.segment}")
    print(f"    KSA National: {contact.is_ksa_national} | Warm: {contact.has_warm_relationship}\n")

    from .agents.researcher import ResearchAgent
    from .agents.writer     import WriterAgent
    from .scoring.engine    import ScoringEngine

    api_key = os.environ["ANTHROPIC_API_KEY"]

    # Show score breakdown
    scorer    = ScoringEngine()
    breakdown = scorer.score_one(dict(row))
    print("  SCORE BREAKDOWN:")
    print(f"    Signal Strength:       {breakdown['signal_strength']:>3}/35")
    print(f"    Regulatory Pressure:   {breakdown['regulatory_pressure']:>3}/30")
    print(f"    Persona Reachability:  {breakdown['persona_reachability']:>3}/20")
    print(f"    Existing Relationship: {breakdown['existing_relationship']:>3}/15")
    print(f"    ─────────────────────────────")
    print(f"    COMPOSITE SCORE:       {breakdown['composite_score']:>3}/100  [{breakdown['tier']}]\n")

    print("  [1/2] Researching...")
    researcher = ResearchAgent(api_key=api_key)
    research   = researcher.research_contact(contact)
    print(f"  Hook: {research.recommended_hook}\n")

    print("  [2/2] Generating email T1...")
    writer = WriterAgent(api_key=api_key)
    email  = writer.generate_email(contact, research, touch=1)
    print(f"\n  Subject: {email.subject}")
    print(f"  ({'EN+AR' if contact.needs_arabic else 'EN only'})")
    print(f"  {'─'*50}")
    print(f"  {email.body}\n")

    print("  LinkedIn T1 connection note:")
    dm = writer.generate_linkedin_dm(contact, research, touch=1)
    print(f"  ({len(dm.body)} chars)\n  {dm.body}\n")
    print("✅  Test complete.\n")


COMMANDS = {
    "setup":   cmd_setup,
    "run":     cmd_run,
    "signals": cmd_signals,
    "score":   cmd_score,
    "report":  cmd_report,
    "start":   cmd_start,
    "webhook": cmd_webhook,
    "status":  cmd_status,
    "test":    cmd_test,
}

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd not in COMMANDS:
        print(__doc__)
        sys.exit(0)
    COMMANDS[cmd]()


def cmd_dashboard():
    """Start the web dashboard on http://localhost:5000"""
    from .dashboard.app import app
    port = int(os.environ.get("DASHBOARD_PORT", 5000))
    print(f"\n  Decimal ABM Dashboard → http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)

COMMANDS["dashboard"] = cmd_dashboard
