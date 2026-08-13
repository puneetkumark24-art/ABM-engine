import os
import tempfile
import uuid

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.gettempdir(), "drip_campaign_dispatch.db")
os.environ["PUBLIC_BASE_URL"] = "https://track.example.invalid"

from database import Base, engine, SessionLocal
import models
import models_ext as mx
import models_jobs  # noqa: F401 - registers queue tables
from abm_platform.services import campaign_dispatch, jobs, marketing, pipeline_jobs
from datetime import datetime, timedelta

Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)


def _fixture(db, count=5):
    suffix = uuid.uuid4().hex[:8]
    org = models.Organization(canonical_name=f"Dispatch Bank {suffix}")
    db.add(org); db.flush()
    people = []
    for i in range(count):
        p = models.Person(full_name=f"Person {i}", primary_email=f"p{i}@example.invalid",
                          current_org_id=org.id, is_active=True, consent_status="opted_in")
        db.add(p); people.append(p)
    db.flush()
    audience = marketing.create_audience(db, f"Dispatch audience {suffix}")
    marketing.add_members(db, audience.id, [p.id for p in people])
    campaign = marketing.create_campaign(
        db, f"Durable dispatch {suffix}", audience.id, "Hello {name}",
        '<a href="https://example.invalid/unsubscribe">Unsubscribe</a>')
    campaign.approval_status = "approved"; db.commit()
    return campaign


def test_dispatch_runs_in_restart_safe_batches():
    db = SessionLocal()
    campaign = _fixture(db)
    pipeline_jobs.register_pipeline_handlers()
    started = campaign_dispatch.start(db, campaign.id, batch_size=2)
    assert started["total"] == 5 and started["status"] == "queued"
    for _ in range(5):
        jobs.run_once(db, limit=1)
    result = campaign_dispatch.get(db, started["id"])
    assert result["status"] == "completed"
    assert result["processed"] == 5 and result["sent"] == 5
    assert db.query(mx.EmailMessage).filter_by(campaign_id=campaign.id).count() == 5
    # Reprocessing a completed run and starting again cannot duplicate messages.
    campaign_dispatch.process_batch(db, started["id"])
    again = campaign_dispatch.start(db, campaign.id, batch_size=10)
    jobs.run_once(db, limit=1)
    assert campaign_dispatch.get(db, again["id"])["existing_skipped"] == 5
    assert db.query(mx.EmailMessage).filter_by(campaign_id=campaign.id).count() == 5
    db.close()


def test_dispatch_can_cancel_before_first_batch():
    db = SessionLocal()
    campaign = _fixture(db, 3)
    run = campaign_dispatch.start(db, campaign.id, batch_size=1)
    campaign_dispatch.cancel(db, run["id"])
    pipeline_jobs.register_pipeline_handlers()
    jobs.run_once(db, limit=1)
    result = campaign_dispatch.get(db, run["id"])
    assert result["status"] == "cancelled" and result["processed"] == 0
    db.close()


def test_worker_recovers_expired_job_lease():
    db = SessionLocal()
    campaign = _fixture(db, 1)
    run = campaign_dispatch.start(db, campaign.id, batch_size=1)
    job = db.query(models_jobs.Job).filter_by(kind="campaign_dispatch_batch").order_by(
        models_jobs.Job.created_at.desc()).first()
    job.status = "running"; job.locked_at = datetime.utcnow() - timedelta(minutes=20)
    db.commit()
    pipeline_jobs.register_pipeline_handlers()
    result = jobs.run_once(db, limit=1)
    assert result["recovered"] == 1
    assert campaign_dispatch.get(db, run["id"])["status"] == "completed"
    db.close()


def test_live_dispatch_fails_closed_when_ses_is_not_activated():
    import os
    db = SessionLocal()
    campaign = _fixture(db, 1)
    os.environ.pop("EMAIL_LIVE_SENDING_ENABLED", None)
    try:
        campaign_dispatch.start(db, campaign.id, requested_transport="configured")
        assert False
    except ValueError as exc:
        assert "live dispatch blocked" in str(exc)
    assert db.query(mx.CampaignDispatchRun).filter_by(campaign_id=campaign.id).count() == 0
    db.close()
