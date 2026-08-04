# DRIP Signal v2 integration kit

This folder is an additive overlay for `decimal_abm`. It reuses DRIP's Flask
dashboard and APScheduler shell without importing any outreach or delivery
module. Keep the `signal_engine/` package beside DRIP's `abm_engine/` package.

## Safety model

- Signal evidence remains in a separate SQLite database (`SIGNAL_V2_DB`).
- Signal review approval only promotes evidence inside that signal database.
- The bridge exports only `scoring_eligible=1` records.
- Export writes only DRIP `signals`, `news_items`, and `signal_v2_exports`.
- No draft is generated, approved, or sent by this integration package.
- The signal scheduler hook registers collection only.

## Files to copy

Copy the complete standalone `signal_engine/` directory to the DRIP repository
root. Then copy:

```text
drip_integration/abm_engine/signal_integration/
```

to:

```text
decimal_abm/abm_engine/signal_integration/
```

## Dashboard registration

In `abm_engine/dashboard/app.py`, immediately after creating `app`, add:

```python
from abm_engine.signal_integration.blueprint import register_signal_blueprint
register_signal_blueprint(app, os.environ.get("SIGNAL_V2_DB", "signal_engine.db"))
```

This adds `/signal-review` and its signal-review API. It does not replace or
alter DRIP's existing `/intelligence` page or draft APIs.

Add a navigation link to `dashboard/templates/base.html`:

```html
<a href="/signal-review">Signal Review</a>
```

## Environment setting

Add only this non-secret path setting:

```text
SIGNAL_V2_DB=signal_engine.db
```

## Signal-only scheduler registration

In `abm_engine/scheduler/runner.py`, after creating `scheduler`, add:

```python
from ..signal_integration.scheduler_job import register_signal_jobs
register_signal_jobs(scheduler)
```

Do not use DRIP's full scheduler during shadow validation if delivery jobs are
configured. The safest initial option is to call `job_signal_v2_collect()` from
a separate signal-only process or Windows Task Scheduler.

## One-way export

Preview without modifying DRIP:

```powershell
python -m abm_engine.signal_integration.export_cli --signal-db signal_engine.db --drip-db abm_engine.db
```

Apply after review:

```powershell
python -m abm_engine.signal_integration.export_cli --signal-db signal_engine.db --drip-db abm_engine.db --apply
```

The export is idempotent; rerunning it does not duplicate previously exported
signal UUIDs.

## Rollout order

1. Back up the DRIP database.
2. Copy the packages and register the Flask blueprint only.
3. Point `SIGNAL_V2_DB` to the validated shadow database.
4. Verify `/signal-review` while delivery processes remain stopped.
5. Run export preview and inspect eligible UUIDs.
6. Apply export and verify the existing Intelligence page.
7. Only then register the collection schedule.

Do not enable automatic export or outreach during the initial seven-day shadow
trial.
