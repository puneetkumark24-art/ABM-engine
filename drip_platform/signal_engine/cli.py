from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from html import escape

from .db import connect, initialize
from .pipeline import Pipeline
from .catalog import ACCOUNTS, SOURCES
from .capture import CaptureService, initialize_capture, read_text


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "work" / "signal_engine.db"


def seed(pipe: Pipeline) -> None:
    for a in ACCOUNTS:
        pipe.add_account(a["id"], a["name"], a["aliases"], a["domains"], a["tickers"])
    for s in SOURCES:
        pipe.add_source(s["id"], s["name"], s.get("kind", "rss"), s["language"], s["endpoint"],
                        s["e"], s["p"], s["i"], s["s"], s["bias"], s["interval"])
    # A dedicated fixture-only source keeps the demo deterministic and never
    # pretends that a local XML file was a successful live SAMA collection.
    pipe.add_source("demo_sama", "Demo SAMA Fixture", "rss", "en", "fixture://sama",
                    0.95, 0.90, 0.95, 0.80, 0.10, 240)


def fetch_public_feed(url: str, timeout: int = 25, max_bytes: int = 5_000_000) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": "DRIP-SignalEngine-Shadow/0.1 (+local-evaluation; no-crawl)",
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9,*/*;q=0.1",
    })
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError(f"feed exceeds safety limit of {max_bytes} bytes")
        return data


def rows(con, sql: str) -> list[dict]:
    return [dict(r) for r in con.execute(sql).fetchall()]


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Standalone DRIP signal engine")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("demo")
    ingest = sub.add_parser("ingest-file")
    ingest.add_argument("--source", required=True)
    ingest.add_argument("--file", required=True)
    live = sub.add_parser("collect-live")
    live.add_argument("--source", help="one source id; omit to collect all enabled public RSS sources")
    sub.add_parser("status")
    sub.add_parser("signals")
    reviews_parser = sub.add_parser("reviews")
    reviews_parser.add_argument("--limit", type=int, default=100)
    reviews_parser.add_argument("--reason")
    sub.add_parser("coverage")
    sub.add_parser("source-runs")
    sub.add_parser("validate")
    sub.add_parser("quality-audit")
    sub.add_parser("quality-backfill")
    capture_init = sub.add_parser("capture-init")
    capture_config = sub.add_parser("capture-configure")
    capture_config.add_argument("--channel", required=True)
    capture_config.add_argument("--disabled", action="store_true")
    capture_ingest = sub.add_parser("capture-ingest")
    capture_ingest.add_argument("--channel", required=True)
    capture_ingest.add_argument("--file", required=True)
    capture_ingest.add_argument("--format", choices=["json", "jsonl"], default="json")
    linkedin_import = sub.add_parser("linkedin-import")
    linkedin_import.add_argument("--file", required=True)
    linkedin_import.add_argument("--channel", choices=["linkedin_company", "linkedin_people", "linkedin_jobs"], default="linkedin_company")
    hubspot_import = sub.add_parser("hubspot-import")
    hubspot_import.add_argument("--file", required=True)
    watch_add = sub.add_parser("watch-add")
    watch_add.add_argument("--id", required=True); watch_add.add_argument("--channel", required=True)
    watch_add.add_argument("--url", required=True); watch_add.add_argument("--label", required=True); watch_add.add_argument("--account")
    watch_import = sub.add_parser("watch-import")
    watch_import.add_argument("--file", required=True)
    watch_check = sub.add_parser("watch-check")
    watch_check.add_argument("--id", required=True)
    sub.add_parser("watch-seed-official")
    sub.add_parser("watch-check-all")
    sub.add_parser("capture-coverage")
    sub.add_parser("capture-audit")
    review = sub.add_parser("resolve-review")
    review.add_argument("--id", required=True)
    review.add_argument("--resolution", required=True, choices=["approve", "reject"])
    review.add_argument("--account")
    report = sub.add_parser("daily-report")
    report.add_argument("--output", default=str(ROOT / "reports" / "daily_report.html"))
    args = parser.parse_args(argv)

    con = connect(args.db)
    initialize(con)
    pipe = Pipeline(con)
    if args.command == "init":
        seed(pipe)
        initialize_capture(con)
        print(json.dumps({"ok": True, "db": str(Path(args.db).resolve()), **pipe.status()}, indent=2))
    elif args.command == "demo":
        seed(pipe)
        fixture = ROOT / "examples" / "sama_feed.xml"
        result = pipe.ingest_feed("demo_sama", fixture.read_bytes())
        print(json.dumps({"ingestion": result, "status": pipe.status()}, indent=2))
    elif args.command == "ingest-file":
        print(json.dumps(pipe.ingest_feed(args.source, Path(args.file).read_bytes()), indent=2))
    elif args.command == "collect-live":
        seed(pipe)
        capture = CaptureService(con)
        if args.source:
            selected = con.execute("SELECT id,name,kind,endpoint FROM sources WHERE id=? AND enabled=1", (args.source,)).fetchall()
            if not selected:
                raise SystemExit(f"Unknown or disabled source: {args.source}")
        else:
            selected = con.execute("SELECT id,name,kind,endpoint FROM sources WHERE enabled=1 AND endpoint LIKE 'http%' ORDER BY id").fetchall()
        results = []
        for source in selected:
            try:
                raw = fetch_public_feed(source["endpoint"])
                counts = pipe.ingest_official_page(source["id"], raw) if source["kind"] == "html" else pipe.ingest_feed(source["id"], raw)
                results.append({"source": source["id"], "name": source["name"], "ok": True, **counts})
                channel = "regulator" if source["id"] in {"official_sama_news", "gnews_sama"} else "exchange" if source["id"] == "official_saudi_exchange" else "official_site" if source["id"] == "official_target_banks" else "public_news"
                capture.mark_channel_success(channel)
            except Exception as exc:
                results.append({"source": source["id"], "name": source["name"], "ok": False, "error": str(exc)})
        print(json.dumps({"shadow_mode": True, "results": results, "status": pipe.status()}, indent=2, ensure_ascii=False))
    elif args.command == "status":
        print(json.dumps(pipe.status(), indent=2))
    elif args.command == "signals":
        print(json.dumps(rows(con, "SELECT * FROM signals ORDER BY event_at DESC"), indent=2, ensure_ascii=False))
    elif args.command == "reviews":
        sql = """SELECT reviews.*,observations.title,observations.canonical_url FROM reviews
                 JOIN observations ON observations.id=reviews.observation_id WHERE reviews.status='open'"""
        params = []
        if args.reason:
            sql += " AND reviews.reason_code=?"; params.append(args.reason)
        sql += " ORDER BY reviews.created_at DESC LIMIT ?"; params.append(max(1, min(args.limit, 500)))
        print(json.dumps([dict(r) for r in con.execute(sql, params).fetchall()], indent=2, ensure_ascii=False))
    elif args.command == "coverage":
        print(json.dumps(rows(con, "SELECT id,name,enabled,last_success_at,last_error,consecutive_errors,observations_total FROM sources ORDER BY id"), indent=2))
    elif args.command == "source-runs":
        print(json.dumps(rows(con, """SELECT source_id,started_at,finished_at,status,fetched_count,accepted_count,
                         corroborating_count,review_count,market_count,rejected_count,duplicate_count,error
                         FROM source_runs ORDER BY started_at DESC LIMIT 100"""), indent=2))
    elif args.command == "validate":
        status = pipe.status()
        enabled = con.execute("SELECT COUNT(*) FROM sources WHERE enabled=1 AND endpoint LIKE 'http%'").fetchone()[0]
        successful = con.execute("SELECT COUNT(*) FROM sources WHERE enabled=1 AND endpoint LIKE 'http%' AND last_success_at IS NOT NULL AND last_error IS NULL").fetchone()[0]
        expired_active = con.execute("SELECT COUNT(*) FROM signals WHERE status='active' AND datetime(expires_at)<=datetime('now')").fetchone()[0]
        evidence = con.execute("SELECT COUNT(*) FROM signal_evidence").fetchone()[0]
        confidence_cap_violations = con.execute("SELECT COUNT(*) FROM signals WHERE confidence>coverage_cap+0.000001").fetchone()[0]
        generic_reviews = con.execute("""SELECT COUNT(*) FROM reviews r JOIN observations o ON o.id=r.observation_id
            WHERE r.status='open' AND (lower(o.title) LIKE '%market size%' OR lower(o.title) LIKE '%growth outlook%' OR lower(o.title) LIKE 'top %')""").fetchone()[0]
        open_reviews = status["open_reviews"]
        checks = {
            "source_success_ratio": (successful / enabled if enabled else 0) >= .75,
            "no_expired_active_signals": expired_active == 0,
            "evidence_links_complete": evidence >= status["promoted_signals"],
            "confidence_respects_coverage_cap": confidence_cap_violations == 0,
            "generic_review_noise_below_10pct": (generic_reviews / open_reviews if open_reviews else 0) <= .10,
            "no_action_execution": status["action_eligible"] == 0,
        }
        result = {"migration_ready": all(checks.values()), "checks": checks, "metrics": {
            **status, "live_sources_enabled": enabled, "live_sources_successful": successful,
            "expired_active": expired_active, "evidence_links": evidence, "generic_open_reviews": generic_reviews,
            "confidence_cap_violations": confidence_cap_violations,
        }}
        print(json.dumps(result, indent=2))
    elif args.command == "quality-audit":
        print(json.dumps(pipe.quality_audit(), indent=2))
    elif args.command == "quality-backfill":
        print(json.dumps(pipe.backfill_quality(), indent=2))
    elif args.command == "capture-init":
        seed(pipe); initialize_capture(con)
        print(json.dumps({"ok": True, "channels": con.execute("SELECT COUNT(*) FROM capture_channels").fetchone()[0], "targets": con.execute("SELECT COUNT(*) FROM capture_targets").fetchone()[0]}, indent=2))
    elif args.command == "capture-configure":
        capture = CaptureService(con); capture.configure_channel(args.channel, not args.disabled)
        print(json.dumps({"ok": True, "channel": args.channel, "enabled": not args.disabled}, indent=2))
    elif args.command == "capture-ingest":
        capture = CaptureService(con); payload = read_text(args.file)
        result = capture.ingest_jsonl(args.channel, payload) if args.format == "jsonl" else capture.ingest_json(args.channel, payload)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif args.command == "linkedin-import":
        capture = CaptureService(con)
        print(json.dumps(capture.ingest_linkedin_csv(read_text(args.file), args.channel), indent=2, ensure_ascii=False))
    elif args.command == "hubspot-import":
        capture = CaptureService(con)
        print(json.dumps(capture.ingest_hubspot(read_text(args.file)), indent=2, ensure_ascii=False))
    elif args.command == "watch-add":
        capture = CaptureService(con); capture.add_watch(args.id, args.channel, args.url, args.label, args.account)
        print(json.dumps({"ok": True, "watch": args.id}, indent=2))
    elif args.command == "watch-import":
        capture = CaptureService(con)
        print(json.dumps(capture.ingest_watch_csv(read_text(args.file)), indent=2, ensure_ascii=False))
    elif args.command == "watch-check":
        capture = CaptureService(con)
        target = con.execute("SELECT url FROM page_watch_targets WHERE id=?", (args.id,)).fetchone()
        if not target: raise SystemExit("Unknown watch target")
        print(json.dumps(capture.record_page(args.id, fetch_public_feed(target["url"])), indent=2))
    elif args.command == "watch-seed-official":
        capture = CaptureService(con)
        print(json.dumps(capture.seed_official_watches(), indent=2))
    elif args.command == "watch-check-all":
        capture = CaptureService(con); results = []
        targets = [dict(r) for r in con.execute("SELECT id,url FROM page_watch_targets WHERE enabled=1 ORDER BY id").fetchall()]
        fetched = {}
        with ThreadPoolExecutor(max_workers=min(8, max(1, len(targets)))) as pool:
            futures = {pool.submit(fetch_public_feed, target["url"]): target for target in targets}
            for future in as_completed(futures):
                target = futures[future]
                try:
                    fetched[target["id"]] = (future.result(), None)
                except Exception as exc:
                    fetched[target["id"]] = (None, exc)
        for target in targets:
            raw, error = fetched[target["id"]]
            if error is None:
                try:
                    results.append({"id": target["id"], "ok": True, **capture.record_page(target["id"], raw)})
                except Exception as exc:
                    con.execute("UPDATE page_watch_targets SET last_error=? WHERE id=?", (str(exc)[:500], target["id"])); con.commit()
                    results.append({"id": target["id"], "ok": False, "error": str(exc)})
            else:
                con.execute("UPDATE page_watch_targets SET last_error=? WHERE id=?", (str(error)[:500], target["id"])); con.commit()
                results.append({"id": target["id"], "ok": False, "error": str(error)})
        print(json.dumps({"checked": len(results), "results": results}, indent=2, ensure_ascii=False))
    elif args.command == "capture-coverage":
        capture = CaptureService(con)
        print(json.dumps(capture.coverage(), indent=2, ensure_ascii=False))
    elif args.command == "capture-audit":
        capture = CaptureService(con)
        print(json.dumps(capture.refresh_gap_alerts(), indent=2))
    elif args.command == "resolve-review":
        try:
            print(json.dumps(pipe.resolve_review(args.id, args.resolution, args.account), indent=2))
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc), "hint": "Use an actual open review UUID from the reviews command."}, indent=2))
            con.close()
            return 2
    elif args.command == "daily-report":
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        signals = rows(con, "SELECT s.*,a.canonical_name FROM signals s JOIN accounts a ON a.id=s.account_id WHERE s.status='active' ORDER BY s.event_at DESC")
        review_total = con.execute("SELECT COUNT(*) FROM reviews WHERE status='open'").fetchone()[0]
        reviews = rows(con, "SELECT r.id,r.reason_code,o.title FROM reviews r JOIN observations o ON o.id=r.observation_id WHERE r.status='open' ORDER BY r.created_at DESC LIMIT 50")
        sources = rows(con, "SELECT name,last_success_at,last_error,observations_total FROM sources ORDER BY name")
        market = rows(con, "SELECT title,published_at,canonical_url FROM observations WHERE status='market' ORDER BY published_at DESC LIMIT 50")
        capture_report = CaptureService(con).coverage()
        quality_report = pipe.quality_audit()
        gap_rows = [x for x in capture_report["matrix"] if x["required"] and not x["covered"]][:100]
        def table(items, columns):
            head = ''.join(f'<th>{escape(label)}</th>' for _, label in columns)
            body = ''.join('<tr>' + ''.join(f'<td>{escape(str(row.get(key) if row.get(key) is not None else ""))}</td>' for key, _ in columns) + '</tr>' for row in items)
            return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'
        html_doc = f'''<!doctype html><meta charset="utf-8"><title>DRIP Signal Daily Report</title>
<style>body{{font:14px Arial;margin:32px;color:#17202a}}h1{{color:#145a32}}table{{border-collapse:collapse;width:100%;margin-bottom:28px}}th,td{{border:1px solid #ddd;padding:8px;text-align:left}}th{{background:#eaf2f8}}.kpi{{display:inline-block;padding:12px 18px;margin:0 10px 20px 0;background:#e8f8f5;border-radius:8px}}</style>
<h1>DRIP Signal Engine — Daily Shadow Report</h1><p>Generated {escape(datetime.now(timezone.utc).isoformat())}. No outreach actions are performed.</p>
<div class="kpi">Active signals: {len(signals)}</div><div class="kpi">Scoring eligible: {sum(x['scoring_eligible'] for x in signals)}</div><div class="kpi">Open reviews: {review_total}</div><div class="kpi">Market intelligence: {len(market)}</div><div class="kpi">360 coverage: {capture_report['required_coverage_ratio']:.0%}</div><div class="kpi">Quality assessed: {quality_report['assessed_observations']}</div><div class="kpi">Avg completeness: {quality_report['average_completeness']:.0%}</div>
<h2>Signals</h2>{table(signals, [('canonical_name','Account'),('signal_type','Type'),('title','Signal'),('confidence','Confidence'),('scoring_eligible','Score?'),('expires_at','Expires')])}
<h2>Market intelligence</h2>{table(market, [('published_at','Published'),('title','Item'),('canonical_url','Evidence URL')])}
<h2>Review queue</h2>{table(reviews, [('id','Review ID'),('reason_code','Reason'),('title','Title')])}
<h2>Source health</h2>{table(sources, [('name','Source'),('last_success_at','Last success'),('last_error','Last error'),('observations_total','Promoted')])}'''
        html_doc += '<h2>360 capture gaps</h2>' + table(gap_rows, [('account','Account'),('channel','Channel'),('gap','Gap')])
        html_doc += '<h2>Signal quality audit</h2>' + table([quality_report], [('quality_gate_ready','Calibrated?'),('assessed_observations','Assessed'),('average_completeness','Avg completeness'),('average_materiality','Avg materiality'),('incomplete_reviews','Incomplete reviews'),('contested_signals','Contested'),('independent_source_families','Independent families')])
        destination.write_text(html_doc, encoding="utf-8")
        print(json.dumps({"ok": True, "report": str(destination.resolve()), "signals": len(signals), "open_reviews": review_total, "reviews_shown": len(reviews)}, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
