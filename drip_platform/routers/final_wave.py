"""routers/final_wave.py — Final wave surface: meetings (+ICS), the PUBLIC
preference center (/p/prefs — signed links, no login), and the generic report
builder."""
from __future__ import annotations
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from sqlalchemy.orm import Session

from database import get_db
from abm_platform.services import meetings as mt, preferences as pf, reporting

router = APIRouter(tags=["final-wave"])


# ── meetings ─────────────────────────────────────────────────
class MeetingReq(BaseModel):
    title: str
    starts_at: datetime
    duration_minutes: int = 30
    org_id: Optional[str] = None
    person_id: Optional[str] = None
    owner: str = "unassigned"
    location: str = ""
    agenda: str = ""


@router.post("/crm/meetings", status_code=201)
def schedule(req: MeetingReq, db: Session = Depends(get_db)):
    try:
        m = mt.schedule(db, req.title, req.starts_at, req.duration_minutes,
                        req.org_id, req.person_id, req.owner, req.location, req.agenda)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"id": m.id, "title": m.title, "starts_at": m.starts_at,
            "ends_at": m.ends_at, "status": m.status}


@router.get("/crm/meetings/upcoming")
def upcoming(owner: Optional[str] = None, days: int = 14,
             db: Session = Depends(get_db)):
    return [{"id": m.id, "title": m.title, "starts_at": m.starts_at,
             "owner": m.owner, "org_id": m.org_id, "location": m.location}
            for m in mt.upcoming(db, owner, days)]


class StatusReq(BaseModel):
    status: str
    outcome_notes: str = ""


@router.post("/crm/meetings/{meeting_id}/status")
def set_status(meeting_id: str, req: StatusReq, db: Session = Depends(get_db)):
    try:
        m = mt.set_status(db, meeting_id, req.status, req.outcome_notes)
    except ValueError as e:
        code = 404 if "not found" in str(e) else 422
        raise HTTPException(status_code=code, detail=str(e))
    return {"id": m.id, "status": m.status}


@router.get("/crm/meetings/{meeting_id}/ics", response_class=PlainTextResponse)
def ics(meeting_id: str, db: Session = Depends(get_db)):
    import models_final as mf
    m = db.get(mf.Meeting, meeting_id)
    if m is None:
        raise HTTPException(status_code=404, detail="meeting not found")
    return PlainTextResponse(mt.to_ics(m), media_type="text/calendar")


# ── PUBLIC preference center ─────────────────────────────────
_PREF_PAGE = """<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Email preferences</title>
<style>body{{font-family:Inter,system-ui,sans-serif;background:#f4f6f5;margin:0;
display:flex;justify-content:center;padding:40px 16px}}
.card{{background:#fff;border-radius:14px;box-shadow:0 2px 14px rgba(0,0,0,.08);
max-width:440px;width:100%;padding:28px}}
h1{{font-size:19px;color:#143d2b}}p{{color:#5a6e64;font-size:14px}}
label{{display:flex;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid #eef2f0;font-size:14.5px;color:#22332b}}
button{{margin-top:18px;width:100%;padding:11px;border:0;border-radius:9px;cursor:pointer;font-size:14.5px}}
.save{{background:#2f9e6e;color:#fff}}.unsub{{background:#fff;color:#c65454;border:1px solid #e5c9c9;margin-top:8px}}
.ok{{color:#2f9e6e;font-size:13.5px;margin-top:10px;display:none}}</style></head><body>
<div class="card"><h1>Communication preferences</h1>
<p>Hi {name} — choose what you'd like to receive from Decimal.</p>
<form method="post">
{boxes}
<button class="save" name="action" value="save">Save preferences</button>
<button class="unsub" name="action" value="unsubscribe_all"
 onclick="return confirm('Unsubscribe from ALL communications?')">Unsubscribe from everything</button>
</form>
{msg}
</div></body></html>"""


def _render_prefs(profile: dict, msg: str = "") -> str:
    labels = {"product_updates": "Product updates", "insights": "Banking insights",
              "events": "Events & webinars", "partnership": "Partnership news"}
    boxes = "\n".join(
        f'<label><input type="checkbox" name="{c}" {"checked" if on and not profile["unsubscribed_all"] else ""}> {labels[c]}</label>'
        for c, on in profile["categories"].items())
    m = f'<p style="color:#2f9e6e">{msg}</p>' if msg else ""
    return _PREF_PAGE.format(name=profile.get("name") or "there", boxes=boxes, msg=m)


@router.get("/p/prefs/{person_id}/{token}", response_class=HTMLResponse)
def pref_page(person_id: str, token: str, db: Session = Depends(get_db)):
    if not pf.verify_token(person_id, token):
        raise HTTPException(status_code=403, detail="invalid link")
    try:
        return HTMLResponse(_render_prefs(pf.get_profile(db, person_id)))
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")


@router.post("/p/prefs/{person_id}/{token}", response_class=HTMLResponse)
async def pref_submit(person_id: str, token: str, request: Request,
                      db: Session = Depends(get_db)):
    if not pf.verify_token(person_id, token):
        raise HTTPException(status_code=403, detail="invalid link")
    form = dict(await request.form())
    if form.get("action") == "unsubscribe_all":
        prof = pf.update_profile(db, person_id, unsubscribe_all=True)
        return HTMLResponse(_render_prefs(prof, "You are unsubscribed from all communications."))
    cats = {c: (c in form) for c in pf.CATEGORIES}
    prof = pf.update_profile(db, person_id, categories=cats)
    return HTMLResponse(_render_prefs(prof, "Preferences saved."))


@router.get("/crm/persons/{person_id}/pref-link")
def pref_link(person_id: str):
    """Generate the signed preference-center link for a person (for templates)."""
    return {"path": f"/p/prefs/{person_id}/{pf.token_for(person_id)}"}


# ── BD outreach tracking (absorbs the Flask dashboard's core edit flow) ──
class OutreachReq(BaseModel):
    connection_sent: Optional[bool] = None
    connection_accepted: Optional[bool] = None
    messaged: Optional[bool] = None
    response_notes: Optional[str] = None
    next_step: Optional[str] = None
    bd_flow_column: Optional[str] = None
    updated_by: str = "OS"


@router.patch("/crm/persons/{person_id}/outreach")
def update_outreach(person_id: str, req: OutreachReq, db: Session = Depends(get_db)):
    import models
    p = db.get(models.Person, person_id)
    if p is None:
        raise HTTPException(status_code=404, detail="person not found")
    if req.connection_sent is not None:
        p.outreach_connection_sent = req.connection_sent
        if req.connection_sent and not p.outreach_connection_sent_date:
            p.outreach_connection_sent_date = datetime.utcnow()
    if req.connection_accepted is not None:
        p.outreach_connection_accepted = req.connection_accepted
    if req.messaged is not None:
        p.outreach_messaged = req.messaged
    if req.response_notes is not None:
        p.outreach_response_notes = req.response_notes
    if req.next_step is not None:
        p.next_step = req.next_step
    if req.bd_flow_column is not None:
        p.bd_flow_column = req.bd_flow_column
    p.outreach_updated_by = req.updated_by
    p.outreach_updated_at = datetime.utcnow()
    db.commit()
    return {"person_id": person_id,
            "connection_sent": p.outreach_connection_sent,
            "connection_accepted": p.outreach_connection_accepted,
            "messaged": p.outreach_messaged,
            "next_step": p.next_step,
            "updated_by": p.outreach_updated_by}


# ── report builder ───────────────────────────────────────────
class ReportRunReq(BaseModel):
    entity: str = "persons"
    filters: list[dict] = []
    group_by: Optional[str] = None
    metric: str = "count"
    metric_field: Optional[str] = None


@router.post("/reports/run")
def run_report(req: ReportRunReq, db: Session = Depends(get_db)):
    try:
        return reporting.run_definition(db, req.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class ReportSaveReq(ReportRunReq):
    name: str
    viz: str = "table"


@router.post("/reports", status_code=201)
def save_report(req: ReportSaveReq, db: Session = Depends(get_db)):
    d = req.model_dump(); name = d.pop("name"); viz = d.pop("viz")
    r = reporting.create_report(db, name, d, viz)
    return {"id": r.id, "name": r.name}


@router.get("/reports/{report_id}/run")
def run_saved(report_id: str, db: Session = Depends(get_db)):
    import models_ext as mx
    r = db.get(mx.ReportDef, report_id)
    if r is None:
        raise HTTPException(status_code=404, detail="report not found")
    d = r.definition or {}
    if "entity" in d:
        return {"report": r.name, **reporting.run_definition(db, d)}
    return reporting.render(db, report_id)
