# Decimal ABM Engine
### Fully automatic outreach — humans only step in when a prospect replies

---

## What this does

1. **Reads** your 100-lead Excel every morning
2. **Researches** each contact (Claude web-searches for fresh signals)
3. **Writes** a personalized email + LinkedIn DM (5-touch cadence)
4. **Sends** via SendGrid (email) + Heyreach (LinkedIn)
5. **Logs** every action to HubSpot CRM
6. **Alerts** you on Slack the moment a prospect replies
7. **Stops** outreach to that contact — human takes over

No n8n. No Make.com. Claude is the brain AND the orchestrator.

---

## Setup (first time, ~20 minutes)

### 1. Install dependencies

```bash
cd abm_engine
pip install -r requirements.txt
```

### 2. Configure your .env

```bash
cp .env.example .env
# Open .env and fill in your API keys
```

**Minimum required to start (laptop test):**
- `ANTHROPIC_API_KEY` — from console.anthropic.com

**To send real emails:**
- `SENDGRID_API_KEY`, `SENDGRID_FROM_EMAIL`, `SENDGRID_FROM_NAME`

**For LinkedIn automation:**
- `HEYREACH_API_KEY`, `HEYREACH_CAMPAIGN_ID`

**For CRM logging:**
- `HUBSPOT_API_KEY`

**For reply alerts:**
- `SLACK_WEBHOOK_URL`

### 3. Load your contacts

Put your Excel file at `./data/abm_contacts.xlsx` (or set `CONTACTS_EXCEL_PATH` in .env).

```bash
python -m abm_engine setup
```

### 4. Test it (no emails sent)

```bash
python -m abm_engine test
```

This runs the full pipeline on your highest-priority contact:
- Web research ✓
- Email generated ✓
- LinkedIn DM generated ✓
- No actual sending

### 5. Check the pipeline

```bash
python -m abm_engine status
```

---

## Running the engine

> **Note:** `engine_scheduler.py` at the repo root (the Gemini/SMTP-based script) is
> **superseded**. Don't run it alongside the commands below — both write to the same
> `abm_engine.db` and would double-process signals/drafts. Use the CLI commands in this
> section as the single source of truth for running the engine.

### Option A — Run once now

```bash
python -m abm_engine run
```

Processes up to 20 contacts (set `OUTREACH_DAILY_LIMIT` in .env).

### Option B — Start the automatic scheduler (recommended)

Open **two terminals**:

**Terminal 1 — The engine:**
```bash
python -m abm_engine start
```
Runs daily at 9 AM Riyadh time. Checks for replies every 15 min.

**Terminal 2 — Reply detection server:**
```bash
python -m abm_engine webhook
# Then in another tab:
ngrok http 8080
# Copy the ngrok URL into SendGrid: Settings → Event Webhook
```

**Terminal 3 — Human review dashboard:**
```bash
python -m abm_engine dashboard
# Open http://localhost:5000 to approve/reject/edit generated drafts
```

---

## Moving to cloud (AWS / GCP)

1. Change `DATABASE_URL` in .env to a Postgres connection string
2. Run on an EC2 t3.micro or a simple VM
3. Use a process manager: `pm2 start "python -m abm_engine start" --name abm-engine`
4. Replace ngrok with a real domain for the webhook server
5. Set a cron or systemd to auto-restart on reboot

---

## The 5-touch cadence

| Touch | Email angle           | LinkedIn angle           | Gap  |
|-------|-----------------------|--------------------------|------|
| T1    | Signal hook           | Connection note (no pitch) | Day 0 |
| T2    | Value add (insight)   | Follow-up DM              | Day 4 |
| T3    | Social proof          | Share case study          | Day 8 |
| T4    | Direct meeting ask    | Direct ask                | Day 12 |
| T5    | Break-up              | Gracious exit             | Day 16 |

**Engine stops the moment a contact replies.**
Slack alert fires → human takes the conversation forward.

---

## File structure

```
abm_engine/
├── __main__.py           # CLI: setup / run / start / test / status
├── core/
│   ├── models.py         # Data models: Contact, TouchRecord, etc.
│   ├── loader.py         # Excel → database
│   └── orchestrator.py   # Main pipeline coordinator
├── agents/
│   ├── researcher.py     # Claude web research agent
│   ├── writer.py         # Claude message generation (5 touches)
│   └── notifier.py       # Slack alerts for human handoff
├── channels/
│   ├── email_channel.py     # SendGrid email sender
│   ├── linkedin_channel.py  # Heyreach LinkedIn automation
│   ├── hubspot_channel.py   # HubSpot CRM logging
│   └── webhook_server.py    # Receive SendGrid reply events
├── database/
│   └── db.py             # SQLite (swap to Postgres for cloud)
├── scheduler/
│   └── runner.py         # APScheduler — daily run + 15-min reply check
├── data/
│   └── abm_contacts.xlsx # Your lead database (put it here)
├── .env.example          # Config template
└── requirements.txt      # Dependencies
```

---

## API keys — where to get them

| Key | Where |
|-----|-------|
| `ANTHROPIC_API_KEY` | console.anthropic.com → API Keys |
| `SENDGRID_API_KEY` | app.sendgrid.com → Settings → API Keys |
| `HUBSPOT_API_KEY` | app.hubspot.com → Settings → Integrations → Private Apps |
| `HEYREACH_API_KEY` | app.heyreach.io → Settings → API |
| `SLACK_WEBHOOK_URL` | api.slack.com → Your Apps → Incoming Webhooks |

---

## Scaling up

- Increase `OUTREACH_DAILY_LIMIT` in .env (default 20)
- Add more contacts to your Excel — `python -m abm_engine setup` re-loads
- To add a new target institution, just add rows to the Excel and re-run setup
- The engine auto-prioritises by `priority_score` — highest score goes first
