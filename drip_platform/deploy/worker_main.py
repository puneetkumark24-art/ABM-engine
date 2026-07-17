"""
worker_main.py — the durable job worker process (P0-B runtime).

Registers all job handlers, then loops claiming + running jobs with
FOR UPDATE SKIP LOCKED. Scale horizontally by running N replicas (compose sets
2) — the SKIP LOCKED claim guarantees no job is processed twice.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from abm_platform.services import jobs, orchestrator_async, pipeline_jobs, enrichment  # noqa: E402


def register_all_handlers():
    orchestrator_async.register_handlers()          # sequence_step
    pipeline_jobs.register_pipeline_handlers()       # decision, engagement_rollup, enrichment, campaign_send
    # register at least one enrichment provider so the enrichment job is useful
    # (real Apollo/Clay adapters replace this stub at deploy time)
    enrichment.register_provider("titlefill",
        lambda p: {"current_title": p.current_title or "VP"})


def main():
    register_all_handlers()
    print(f"[worker] up ({jobs.WORKER_ID}); handlers:", list(jobs._HANDLERS.keys()), flush=True)
    jobs.run_worker(poll_seconds=float(os.environ.get("WORKER_POLL", "1.0")),
                    batch=int(os.environ.get("WORKER_BATCH", "20")))


if __name__ == "__main__":
    main()
