"""
abm_engine/reporting/kpi.py
─────────────────────────────
Layer 6: Weekly KPI reporting + feedback loop to scoring model.

Generates:
1. Weekly KPI snapshot stored to DB
2. WhatsApp + Email weekly report to BDR
3. Signal-to-meeting conversion data → feeds back into scoring weights

Benchmarks from Layer 6 doc:
  Meetings booked:     2–4 / month in months 1–3
  Pipeline value:      $300K–$800K by month 6
  Engagement rate:     15–25% for KSA banking
"""
from __future__ import annotations
import os
from datetime import datetime, timedelta
from loguru import logger

from ..database.db import compute_kpi_for_week, upsert_kpi_snapshot, get_kpi_for_week, get_conn
from ..agents.notifier import NotifierAgent


# ─── Benchmarks (from Layer 6 doc) ────────────────────────────────────────────
BENCHMARK_ENGAGEMENT_RATE = 15.0   # % minimum for KSA banking
BENCHMARK_MEETINGS_MONTH  = 2      # minimum per month


def _make_notifier() -> NotifierAgent:
    return NotifierAgent(
        twilio_account_sid    = os.environ.get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token     = os.environ.get("TWILIO_AUTH_TOKEN", ""),
        twilio_from_whatsapp  = os.environ.get("TWILIO_FROM_WHATSAPP", ""),
        alert_to_whatsapp     = os.environ.get("ALERT_TO_WHATSAPP", ""),
        sendgrid_api_key      = os.environ.get("SENDGRID_API_KEY", ""),
        alert_from_email      = os.environ.get("SENDGRID_FROM_EMAIL", ""),
        alert_to_email        = os.environ.get("ALERT_TO_EMAIL", ""),
        alert_from_name       = "Decimal ABM Engine",
    )


class KPIReporter:
    """
    Computes and sends the weekly KPI report.
    Called every Monday at 8 AM by the scheduler.
    """

    def run(self) -> dict:
        """Compute this week's KPIs, store them, and send the report."""
        # Monday of the current week
        today      = datetime.utcnow().date()
        week_start = str(today - timedelta(days=today.weekday()))

        logger.info("Computing KPIs for week starting {}", week_start)
        data = compute_kpi_for_week(week_start)
        upsert_kpi_snapshot(week_start, data)

        # Send report
        self._send_report(week_start, data)
        return data

    def _send_report(self, week_start: str, data: dict) -> None:
        notifier = _make_notifier()

        # Benchmark flags
        eng_ok   = data["engagement_rate_pct"] >= BENCHMARK_ENGAGEMENT_RATE
        eng_flag = "✅" if eng_ok else "⚠️"

        # WhatsApp — short summary
        wa_msg = (
            f"📊 ABM Weekly Report — w/c {week_start}\n\n"
            f"Touches sent: {data['touches_sent']} (email: {data['emails_sent']}, LI: {data['linkedin_sent']})\n"
            f"Opens: {data['emails_opened']} ({data['open_rate_pct']}%)\n"
            f"Replies: {data['replies_received']} ({data['reply_rate_pct']}%)\n"
            f"LI accepts: {data['linkedin_accepts']}\n"
            f"Meetings booked: {data['meetings_booked']}\n"
            f"Engagement rate: {data['engagement_rate_pct']}% {eng_flag}\n\n"
            f"HOT replies: {data['hot_replies']} | WARM: {data['warm_replies']} | COLD: {data['cold_replies']}\n"
            + ("" if eng_ok else "\n⚠️ Engagement below 15% benchmark — messaging review needed.")
        )
        notifier._send_whatsapp(
            contact_name  = "Weekly Report",
            institution   = "",
            role          = "",
            touch_number  = 0,
            channel       = "system",
            reply_snippet = wa_msg,
        )

        # Email — full report
        html = self._build_html_report(week_start, data, eng_flag)
        notifier._send_email_alert(
            contact_name  = f"ABM Weekly Report — w/c {week_start}",
            institution   = "",
            role          = "",
            touch_number  = 0,
            channel       = "system",
            reply_snippet = wa_msg,
        )
        logger.info("Weekly KPI report sent for {}", week_start)

    def _build_html_report(self, week_start: str, d: dict, eng_flag: str) -> str:
        teal    = "#0F6E56"
        ok_bg   = "#E1F5EE"
        warn_bg = "#FAEEDA"
        return f"""
<div style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;">
  <div style="background:{teal};padding:16px 24px;border-radius:8px 8px 0 0;">
    <h2 style="color:white;margin:0;font-size:18px;">ABM Weekly Report — w/c {week_start}</h2>
  </div>
  <div style="border:1px solid #e0e0e0;border-top:none;padding:24px;border-radius:0 0 8px 8px;">
    <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:24px;">
      <div style="background:#f5f5f5;padding:12px;border-radius:6px;text-align:center;">
        <div style="font-size:24px;font-weight:600;">{d['touches_sent']}</div>
        <div style="font-size:12px;color:#666;">Touches sent</div>
      </div>
      <div style="background:#f5f5f5;padding:12px;border-radius:6px;text-align:center;">
        <div style="font-size:24px;font-weight:600;">{d['replies_received']}</div>
        <div style="font-size:12px;color:#666;">Replies</div>
      </div>
      <div style="background:{'#E1F5EE' if d['engagement_rate_pct'] >= 15 else '#FAEEDA'};padding:12px;border-radius:6px;text-align:center;">
        <div style="font-size:24px;font-weight:600;">{d['engagement_rate_pct']}%</div>
        <div style="font-size:12px;color:#666;">Engagement rate {eng_flag}</div>
      </div>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:14px;margin-bottom:20px;">
      <tr style="background:{teal};color:white;">
        <th style="padding:8px;text-align:left;">Metric</th><th style="padding:8px;text-align:right;">This week</th><th style="padding:8px;text-align:right;">Benchmark</th>
      </tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;">Emails sent</td><td style="text-align:right;padding:8px;">{d['emails_sent']}</td><td style="text-align:right;padding:8px;color:#888;">—</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;">Open rate</td><td style="text-align:right;padding:8px;">{d['open_rate_pct']}%</td><td style="text-align:right;padding:8px;color:#888;">&gt;25%</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;">Reply rate</td><td style="text-align:right;padding:8px;">{d['reply_rate_pct']}%</td><td style="text-align:right;padding:8px;color:#888;">&gt;5%</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;">LinkedIn accepts</td><td style="text-align:right;padding:8px;">{d['linkedin_accepts']}</td><td style="text-align:right;padding:8px;color:#888;">—</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;">Meetings booked</td><td style="text-align:right;padding:8px;">{d['meetings_booked']}</td><td style="text-align:right;padding:8px;color:#888;">2–4/month</td></tr>
      <tr><td style="padding:8px;border-bottom:1px solid #eee;">HOT tier replies</td><td style="text-align:right;padding:8px;">{d['hot_replies']}</td><td style="text-align:right;padding:8px;color:#888;">—</td></tr>
    </table>
    {'<div style="background:#FAEEDA;border:1px solid #FFE082;padding:12px;border-radius:6px;font-size:13px;">⚠️ Engagement rate below 15% KSA banking benchmark. Review messaging angles — particularly for COLD tier contacts.</div>' if d['engagement_rate_pct'] < 15 else '<div style="background:#E1F5EE;padding:12px;border-radius:6px;font-size:13px;color:#0F6E56;">✅ Engagement rate above benchmark.</div>'}
  </div>
</div>"""


def log_meeting_booked(contact_id: int, pipeline_value_usd: int = 75000) -> None:
    """
    Call this when a human books a meeting after a prospect reply.
    Updates the KPI snapshot for the current week.
    """
    today      = datetime.utcnow().date()
    week_start = str(today - timedelta(days=today.weekday()))
    conn       = get_conn()
    with conn:
        conn.execute("""
            UPDATE kpi_snapshots
            SET meetings_booked = meetings_booked + 1,
                pipeline_value_usd = pipeline_value_usd + ?
            WHERE week_start = ?
        """, (pipeline_value_usd, week_start))
    logger.info("Meeting logged: contact_id={}, pipeline=${}", contact_id, pipeline_value_usd)
