"""
routers/bd_parity.py — COMPLETE port of the legacy BD dashboard into the OS.

Every feature of dashboard/app.py, as API (the OS renders them):
  • Overview: Financial Institutions vs Ecosystem split (type tags), per-bank
    contact/Indian/signal counts, Decimal priority, ecosystem connection counts
  • Bank contacts: the exact legacy filters (search, priority tier, seniority,
    Indian-origin only) + pagination + priority_score ordering + the stat strip
    (tier counts, Indians, C-suite, champions)
  • Contact create with full BD fields; edit via PATCH /persons/{id} (extended);
    per-record change log via the audit trail
  • Signals per bank: create, edit, toggle read/actioned
  • Account score editing (tier/priority/readiness/digital maturity/…)
  • Org type tags (commercial_bank/islamic_bank/…/vendor/fintech) get + set
  • Connectors and Initiatives views
  • Document uploads: upload (stored in-DB, as legacy), list, download,
    process-contacts through the existing ETL
"""
from __future__ import annotations
import base64
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import get_db
import models

router = APIRouter(prefix="/bd", tags=["bd-parity"])
mkt = APIRouter(tags=["campaigns"])

# Full org taxonomy: Banks / Non-bank financial institutions / Ecosystem
BANK_TAGS = {"commercial_bank", "islamic_bank", "digital_bank"}
NBFI_TAGS = {"financial_institution", "insurance_company", "payment_bank",
             "payments_psp", "asset_management", "finance_company",
             "exchange_house", "bnpl", "microfinance"}
ECOSYSTEM_TAGS = {"vendor", "subsidiary", "fintech", "consulting", "regulator",
                  "association", "government", "telco"}
ORG_TYPE_TAG_OPTIONS = sorted(BANK_TAGS) + sorted(NBFI_TAGS) + sorted(ECOSYSTEM_TAGS)
PAGE_SIZE = 50

# Per-channel outreach tracking (the original DRIP model, verbatim)
OUTREACH_CHANNELS = ["linkedin", "email", "phone", "whatsapp"]
OUTREACH_CHANNEL_LABELS = {"linkedin": "LinkedIn", "email": "Email",
                           "phone": "Phone", "whatsapp": "WhatsApp"}
OUTREACH_STAGE_SUGGESTIONS = {
    "linkedin": ["Connection request sent", "Connection accepted", "Message sent",
                 "Replied", "Meeting booked", "No response"],
    "email": ["Email sent", "Opened", "Replied", "Auto-reply received", "Bounced",
              "No response"],
    "phone": ["Called — no answer", "Called — spoke briefly", "Full call completed",
              "Callback scheduled", "No response"],
    "whatsapp": ["Message sent", "Delivered", "Read", "Replied", "No response"],
}


# ── overview: FI vs ecosystem, with all legacy counts ────────
@router.get("/overview")
def overview(q: str = "", db: Session = Depends(get_db)):
    org_q = db.query(models.Organization).filter(models.Organization.is_active == True)  # noqa: E712
    if q.strip():
        org_q = org_q.filter(models.Organization.canonical_name.ilike(f"%{q.strip()}%"))
    orgs = org_q.all()

    pc, ic, sc, cc = {}, {}, {}, {}
    for oid, ind in (db.query(models.Person.current_org_id, models.Person.is_indian_origin)
                     .filter(models.Person.current_org_id.isnot(None)).all()):
        pc[oid] = pc.get(oid, 0) + 1
        if ind:
            ic[oid] = ic.get(oid, 0) + 1
    for oid, in db.query(models.Signal.org_id).filter(models.Signal.org_id.isnot(None)).all():
        sc[oid] = sc.get(oid, 0) + 1
    for foid, in db.query(models.OrgRelationship.from_org_id).all():
        cc[foid] = cc.get(foid, 0) + 1
    acc = {a.org_id: a for a in db.query(models.AccountIntelligence).all()}

    banks, nbfi, eco = [], [], []
    for o in orgs:
        tags = [t.type_tag for t in o.type_tags]
        row = {"id": o.id, "name": o.canonical_name, "name_ar": o.name_ar,
               "country": o.country, "tags": tags,
               "contacts": pc.get(o.id, 0), "indians": ic.get(o.id, 0),
               "signals": sc.get(o.id, 0),
               "priority": (acc.get(o.id).tier if acc.get(o.id) else None)}
        if any(t in ECOSYSTEM_TAGS for t in tags):
            row["connected_banks"] = cc.get(o.id, 0)
            eco.append(row)
        elif any(t in NBFI_TAGS for t in tags):
            nbfi.append(row)
        else:                      # untagged defaults to bank (legacy behavior)
            banks.append(row)
    banks.sort(key=lambda b: (str(b["priority"] or "z"), -b["contacts"]))
    nbfi.sort(key=lambda b: (str(b["priority"] or "z"), -b["contacts"]))
    eco.sort(key=lambda e: (-e["connected_banks"], e["name"] or ""))
    return {"banks": banks, "nbfi": nbfi, "ecosystem": eco,
            "tag_options": ORG_TYPE_TAG_OPTIONS,
            "tag_groups": {"Banks": sorted(BANK_TAGS),
                           "Non-bank FI": sorted(NBFI_TAGS),
                           "Ecosystem": sorted(ECOSYSTEM_TAGS)}}


# ── org type tags ────────────────────────────────────────────
class TagsReq(BaseModel):
    tags: list[str]


@router.post("/organizations/{org_id}/tags")
def set_tags(org_id: str, req: TagsReq, db: Session = Depends(get_db)):
    org = db.get(models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="organization not found")
    bad = [t for t in req.tags if t not in ORG_TYPE_TAG_OPTIONS]
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown tags: {bad}")
    db.query(models.OrgTypeTag).filter_by(org_id=org_id).delete()
    for t in req.tags:
        db.add(models.OrgTypeTag(org_id=org_id, type_tag=t))
    db.commit()
    return {"org_id": org_id, "tags": req.tags}


# ── bank contacts: legacy filters + stats + pagination ───────
@router.get("/banks/{org_id}/contacts")
def bank_contacts(org_id: str, q: str = "", tier: str = "", seniority: str = "",
                  indian: str = "", page: int = 1, db: Session = Depends(get_db)):
    base = db.query(models.Person).filter(models.Person.current_org_id == org_id)
    stats = {
        "total": base.count(),
        "tier_counts": {t: base.filter(models.Person.priority_tier == t).count()
                        for t in ("1", "2", "3")},
        "indians": base.filter(models.Person.is_indian_origin == True).count(),  # noqa: E712
        "c_suite": base.filter(models.Person.seniority_level == "c_suite").count(),
        "champions": base.filter(models.Person.is_influencer == True,  # noqa: E712
                                 models.Person.seniority_level != "c_suite").count(),
    }
    fq = base
    if q.strip():
        fq = fq.filter(or_(models.Person.full_name.ilike(f"%{q}%"),
                           models.Person.current_title.ilike(f"%{q}%")))
    if tier:
        fq = fq.filter(models.Person.priority_tier == tier)
    if seniority:
        fq = fq.filter(models.Person.seniority_level == seniority)
    if indian == "1":
        fq = fq.filter(models.Person.is_indian_origin == True)  # noqa: E712
    total = fq.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(1, min(page, pages))
    rows = (fq.order_by(models.Person.priority_score.desc().nullslast(),
                        models.Person.full_name)
            .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all())
    return {"stats": stats, "page": page, "pages": pages, "filtered_total": total,
            "contacts": [{
                "id": p.id, "full_name": p.full_name, "title": p.current_title,
                "seniority": p.seniority_level, "priority_tier": p.priority_tier,
                "priority_score": p.priority_score, "is_indian": bool(p.is_indian_origin),
                "is_decision_maker": bool(p.is_decision_maker),
                "is_influencer": bool(p.is_influencer),
                "is_connector": bool(p.is_connector),
                "email": p.primary_email, "phone": p.mobile or p.phone,
                "linkedin": p.linkedin_url, "warmness": p.warmness,
                "conn_sent": bool(p.outreach_connection_sent),
                "conn_accepted": bool(p.outreach_connection_accepted),
                "messaged": bool(p.outreach_messaged),
                "summary": p.last_activity_summary,
                "next_step": p.next_step} for p in rows]}


class ContactNewReq(BaseModel):
    full_name: str
    current_title: Optional[str] = None
    seniority_level: Optional[str] = None
    priority_tier: Optional[str] = None
    is_indian_origin: bool = False
    is_decision_maker: bool = False
    is_influencer: bool = False
    is_connector: bool = False
    primary_email: Optional[str] = None
    mobile: Optional[str] = None
    linkedin_url: Optional[str] = None
    background_notes: Optional[str] = None


@router.post("/banks/{org_id}/contacts", status_code=201)
def new_contact(org_id: str, req: ContactNewReq, db: Session = Depends(get_db)):
    if db.get(models.Organization, org_id) is None:
        raise HTTPException(status_code=404, detail="bank not found")
    p = models.Person(current_org_id=org_id, is_active=True, **req.model_dump())
    db.add(p); db.commit()
    return {"id": p.id, "full_name": p.full_name}


# ── FAST contact upload per bank (the original DRIP importer) ──
@router.post("/banks/{org_id}/contacts/upload")
async def upload_contacts(org_id: str, file: UploadFile = File(...),
                          db: Session = Depends(get_db)):
    """Excel (.xlsx/.xls) or CSV of contacts → the legacy high-speed upserter
    (smart header detection, LinkedIn-export aware, dedup by name+org)."""
    org = db.get(models.Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="bank not found")
    data = await file.read()
    try:
        from etl.import_incoming import import_contacts_from_bytes
        result = import_contacts_from_bytes(db, data, file.filename,
                                            institution_hint=org.canonical_name)
        db.commit()
        return {"filename": file.filename, **{k: v for k, v in result.items()
                                              if not callable(v)}}
    except Exception as e:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=422, detail=f"import failed: {str(e)[:200]}")


# ── signals per bank: create / edit / toggle ─────────────────
class SignalNewReq(BaseModel):
    title: str
    signal_type: str = "news"
    urgency: str = "MEDIUM"
    summary: Optional[str] = None
    url: Optional[str] = None
    deadline: Optional[datetime] = None
    estimated_value: Optional[str] = None
    contact_person: Optional[str] = None


@router.post("/banks/{org_id}/signals", status_code=201)
def new_signal(org_id: str, req: SignalNewReq, db: Session = Depends(get_db)):
    if db.get(models.Organization, org_id) is None:
        raise HTTPException(status_code=404, detail="bank not found")
    s = models.Signal(org_id=org_id, source="manual", **req.model_dump())
    db.add(s); db.commit()
    return {"id": s.id, "title": s.title}


class SignalEditReq(BaseModel):
    fields: dict


_SIGNAL_FIELDS = {"title", "signal_type", "urgency", "summary", "url", "deadline",
                  "estimated_value", "contact_person", "is_read", "is_actioned"}


@router.patch("/signals/{signal_id}")
def edit_signal(signal_id: str, req: SignalEditReq, db: Session = Depends(get_db)):
    s = db.get(models.Signal, signal_id)
    if s is None:
        raise HTTPException(status_code=404, detail="signal not found")
    bad = set(req.fields) - _SIGNAL_FIELDS
    if bad:
        raise HTTPException(status_code=422, detail=f"not editable: {sorted(bad)}")
    for k, v in req.fields.items():
        setattr(s, k, v)
    db.commit()
    return {"id": s.id, "updated": sorted(req.fields)}


@router.post("/signals/{signal_id}/toggle")
def toggle_signal(signal_id: str, which: str = "read", db: Session = Depends(get_db)):
    s = db.get(models.Signal, signal_id)
    if s is None:
        raise HTTPException(status_code=404, detail="signal not found")
    if which == "read":
        s.is_read = not bool(s.is_read)
    elif which == "actioned":
        s.is_actioned = not bool(s.is_actioned)
    else:
        raise HTTPException(status_code=422, detail="which must be read|actioned")
    db.commit()
    return {"id": s.id, "is_read": bool(s.is_read), "is_actioned": bool(s.is_actioned)}


# ── account score editing (legacy /bank/{id}/score/edit) ─────
_SCORE_FIELDS = {"segment", "sub_segment", "digital_maturity", "open_banking",
                 "tier", "priority", "lifecycle_status", "score", "readiness",
                 "effective_opportunity", "owner"}


@router.get("/banks/{org_id}/score")
def get_score(org_id: str, db: Session = Depends(get_db)):
    a = db.get(models.AccountIntelligence, org_id)
    if a is None:
        return {k: None for k in sorted(_SCORE_FIELDS)} | {"org_id": org_id}
    return {k: getattr(a, k, None) for k in sorted(_SCORE_FIELDS)} | {"org_id": org_id}


class ScoreReq(BaseModel):
    fields: dict


@router.patch("/banks/{org_id}/score")
def set_score(org_id: str, req: ScoreReq, db: Session = Depends(get_db)):
    if db.get(models.Organization, org_id) is None:
        raise HTTPException(status_code=404, detail="bank not found")
    bad = set(req.fields) - _SCORE_FIELDS
    if bad:
        raise HTTPException(status_code=422, detail=f"not editable: {sorted(bad)}")
    a = db.get(models.AccountIntelligence, org_id)
    if a is None:
        a = models.AccountIntelligence(org_id=org_id)
        db.add(a)
    for k, v in req.fields.items():
        setattr(a, k, v)
    db.commit()
    return {"org_id": org_id, "updated": sorted(req.fields)}


# ── connectors + initiatives (legacy screens) ────────────────
@router.get("/connectors")
def connectors(db: Session = Depends(get_db)):
    org_name = {o.id: o.canonical_name for o in db.query(models.Organization).all()}
    rows = (db.query(models.Person)
            .filter(models.Person.is_connector == True,  # noqa: E712
                    models.Person.is_active == True).all())  # noqa: E712
    return [{"id": p.id, "name": p.full_name, "title": p.current_title,
             "org": org_name.get(p.current_org_id), "paths": p.connection_paths,
             "warmness": p.warmness} for p in rows]


@router.get("/initiatives")
def initiatives(db: Session = Depends(get_db)):
    org_name = {o.id: o.canonical_name for o in db.query(models.Organization).all()}
    rows = (db.query(models.Signal).order_by(models.Signal.created_at.desc())
            .limit(200).all())
    return [{"id": s.id, "title": s.title, "url": s.url, "type": s.signal_type,
             "urgency": s.urgency, "bank": org_name.get(s.org_id),
             "deadline": str(s.deadline or ""), "value": s.estimated_value,
             "is_read": bool(s.is_read), "is_actioned": bool(s.is_actioned)}
            for s in rows]


# ── per-channel outreach (LinkedIn/Email/Phone/WhatsApp dropdowns) ──
def _summary_from_channels(rows) -> str:
    parts = [f"{OUTREACH_CHANNEL_LABELS[r.channel]}: {r.stage}"
             for r in rows if r.stage]
    return " · ".join(parts) if parts else "Not contacted yet"


@router.get("/persons/{person_id}/channels")
def person_channels(person_id: str, db: Session = Depends(get_db)):
    p = db.get(models.Person, person_id)
    if p is None:
        raise HTTPException(status_code=404, detail="person not found")
    rows = {r.channel: r for r in db.query(models.OutreachChannel)
            .filter_by(person_id=person_id).all()}
    return {"person_id": person_id, "summary": p.last_activity_summary,
            "stage_suggestions": OUTREACH_STAGE_SUGGESTIONS,
            "channels": [{
                "channel": ch, "label": OUTREACH_CHANNEL_LABELS[ch],
                "stage": rows[ch].stage if ch in rows else None,
                "notes": rows[ch].notes if ch in rows else None,
                "next_step": rows[ch].next_step if ch in rows else None,
                "updated_by": rows[ch].updated_by if ch in rows else None,
                "updated_at": str(rows[ch].updated_at) if ch in rows and rows[ch].updated_at else None,
            } for ch in OUTREACH_CHANNELS]}


class ChannelUpdateReq(BaseModel):
    channel: str
    stage: Optional[str] = None        # free text; dropdown suggests, never enforces
    notes: Optional[str] = None        # what was the response
    next_step: Optional[str] = None
    updated_by: str = "OS"


@router.post("/persons/{person_id}/channels")
def update_channel(person_id: str, req: ChannelUpdateReq, db: Session = Depends(get_db)):
    p = db.get(models.Person, person_id)
    if p is None:
        raise HTTPException(status_code=404, detail="person not found")
    if req.channel not in OUTREACH_CHANNELS:
        raise HTTPException(status_code=422, detail=f"channel must be one of {OUTREACH_CHANNELS}")
    row = (db.query(models.OutreachChannel)
           .filter_by(person_id=person_id, channel=req.channel).first())
    if row is None:
        row = models.OutreachChannel(person_id=person_id, channel=req.channel)
        db.add(row)
    for f in ("stage", "notes", "next_step"):
        v = getattr(req, f)
        if v is not None:
            setattr(row, f, v)
    row.updated_by = req.updated_by
    row.updated_at = datetime.utcnow()
    db.flush()   # session has autoflush off — make the new row visible to the query
    # keep the legacy one-line rollup + mirror key flags for filters
    all_rows = db.query(models.OutreachChannel).filter_by(person_id=person_id).all()
    p.last_activity_summary = _summary_from_channels(all_rows)
    li = next((r for r in all_rows if r.channel == "linkedin"), None)
    if li and li.stage:
        p.outreach_connection_sent = True
        p.outreach_connection_accepted = li.stage.lower().startswith(("connection accepted", "message", "replied", "meeting"))
    if any((r.stage or "").lower().startswith(("message sent", "email sent")) for r in all_rows):
        p.outreach_messaged = True
    if any("repl" in (r.stage or "").lower() for r in all_rows):
        p.replied = True
    db.commit()
    return {"person_id": person_id, "channel": req.channel, "stage": row.stage,
            "summary": p.last_activity_summary}


@router.get("/persons/{person_id}/timeline")
def person_timeline_api(person_id: str, db: Session = Depends(get_db)):
    from abm_platform.services import timeline
    try:
        return timeline.person_timeline(db, person_id)
    except Exception:  # noqa: BLE001
        return []


@router.get("/orgs/{org_id}/timeline")
def org_timeline_api(org_id: str, db: Session = Depends(get_db)):
    from abm_platform.services import timeline
    try:
        return timeline.org_timeline(db, org_id)
    except Exception:  # noqa: BLE001
        return []


# ── manual activity logging (LinkedIn touch, event, seminar, call, note…) ──
ACTIVITY_TYPES = ["linkedin", "event", "seminar", "meeting", "call", "email",
                  "whatsapp", "note", "site_visit", "webinar"]


class ActivityReq(BaseModel):
    activity_type: str = "note"
    notes: str
    outcome: Optional[str] = None
    next_action: Optional[str] = None
    owner: str = "Puneet"
    person_id: Optional[str] = None    # for org-level logging with a person
    org_id: Optional[str] = None       # for person-level logging with an org


@router.post("/persons/{person_id}/activities", status_code=201)
def log_person_activity(person_id: str, req: ActivityReq, db: Session = Depends(get_db)):
    p = db.get(models.Person, person_id)
    if p is None:
        raise HTTPException(status_code=404, detail="person not found")
    a = models.ActivityLog(person_id=person_id, org_id=req.org_id or p.current_org_id,
                           activity_type=req.activity_type, notes=req.notes,
                           outcome=req.outcome, next_action=req.next_action,
                           owner=req.owner, timestamp=datetime.utcnow())
    db.add(a); db.commit()
    return {"id": a.id, "activity_type": a.activity_type}


@router.post("/orgs/{org_id}/activities", status_code=201)
def log_org_activity(org_id: str, req: ActivityReq, db: Session = Depends(get_db)):
    if db.get(models.Organization, org_id) is None:
        raise HTTPException(status_code=404, detail="organization not found")
    a = models.ActivityLog(org_id=org_id, person_id=req.person_id,
                           activity_type=req.activity_type, notes=req.notes,
                           outcome=req.outcome, next_action=req.next_action,
                           owner=req.owner, timestamp=datetime.utcnow())
    db.add(a); db.commit()
    return {"id": a.id, "activity_type": a.activity_type}


# ── deals (HubSpot-style CRUD + kanban stage moves) ──────────
DEAL_STAGES = ["Identified", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]


class DealReq(BaseModel):
    org_id: str
    stage: str = "Identified"
    amount_sar: Optional[float] = None
    next_step: Optional[str] = None
    notes: Optional[str] = None


@router.post("/deals", status_code=201)
def new_deal(req: DealReq, db: Session = Depends(get_db)):
    if db.get(models.Organization, req.org_id) is None:
        raise HTTPException(status_code=404, detail="organization not found")
    if req.stage not in DEAL_STAGES:
        raise HTTPException(status_code=422, detail=f"stage must be one of {DEAL_STAGES}")
    o = models.Opportunity(org_id=req.org_id, stage=req.stage,
                           amount_minor=int(round((req.amount_sar or 0) * 100)) or None,
                           next_step=req.next_step, notes=req.notes)
    db.add(o); db.commit()
    return {"id": o.id, "stage": o.stage}


class DealEditReq(BaseModel):
    fields: dict


_DEAL_FIELDS = {"stage", "next_step", "notes", "amount_sar", "probability"}


@router.patch("/deals/{deal_id}")
def edit_deal(deal_id: str, req: DealEditReq, db: Session = Depends(get_db)):
    o = db.get(models.Opportunity, deal_id)
    if o is None:
        raise HTTPException(status_code=404, detail="deal not found")
    bad = set(req.fields) - _DEAL_FIELDS
    if bad:
        raise HTTPException(status_code=422, detail=f"not editable: {sorted(bad)}")
    f = dict(req.fields)
    if "amount_sar" in f:
        o.amount_minor = int(round(float(f.pop("amount_sar") or 0) * 100)) or None
    if "stage" in f and f["stage"] not in DEAL_STAGES:
        raise HTTPException(status_code=422, detail=f"stage must be one of {DEAL_STAGES}")
    for k, v in f.items():
        setattr(o, k, v)
    if o.stage in ("Won", "Lost") and o.closed_at is None:
        o.closed_at = datetime.utcnow()
    if o.stage not in ("Won", "Lost"):
        o.closed_at = None
    db.commit()
    return {"id": o.id, "stage": o.stage,
            "amount_sar": (o.amount_minor or 0) / 100}


@router.get("/deals/board")
def deals_board(db: Session = Depends(get_db)):
    org_name = {o.id: o.canonical_name for o in db.query(models.Organization).all()}
    cols = {s: [] for s in DEAL_STAGES}
    for o in db.query(models.Opportunity).all():
        st = o.stage if o.stage in DEAL_STAGES else "Identified"
        cols[st].append({"id": o.id, "org_id": o.org_id,
                         "bank": org_name.get(o.org_id, "?"),
                         "amount_sar": (o.amount_minor or 0) / 100,
                         "next_step": o.next_step, "notes": o.notes})
    totals = {s: sum(d["amount_sar"] for d in cols[s]) for s in DEAL_STAGES}
    return {"stages": DEAL_STAGES, "columns": cols, "totals_sar": totals}


# ── campaigns (Mailchimp-style build → audience → send → report) ──
class AudienceReq(BaseModel):
    name: str
    segment_id: Optional[str] = None        # build from a saved segment
    person_ids: Optional[list[str]] = None  # or explicit people
    builtin: Optional[str] = None           # all|tier1|tier2|tier3|indian|c_suite|bank:<org_id>


@mkt.post("/mkt/audiences", status_code=201)
def create_audience(req: AudienceReq, db: Session = Depends(get_db)):
    from abm_platform.services import marketing, segments as segsvc
    a = marketing.create_audience(db, req.name)
    pids = list(req.person_ids or [])
    if req.segment_id:
        pids += [p.id for p in segsvc.evaluate(db, req.segment_id)]
    if req.builtin:
        q = db.query(models.Person).filter(models.Person.is_active == True)  # noqa: E712
        b = req.builtin
        if b == "tier1":
            q = q.filter(models.Person.priority_tier == "1")
        elif b == "tier2":
            q = q.filter(models.Person.priority_tier == "2")
        elif b == "tier3":
            q = q.filter(models.Person.priority_tier == "3")
        elif b == "indian":
            q = q.filter(models.Person.is_indian_origin == True)  # noqa: E712
        elif b == "c_suite":
            q = q.filter(models.Person.seniority_level == "c_suite")
        elif b.startswith("bank:"):
            q = q.filter(models.Person.current_org_id == b.split(":", 1)[1])
        elif b != "all":
            raise HTTPException(status_code=422, detail=f"unknown builtin '{b}'")
        pids += [p.id for p in q.all()]
    n = marketing.add_members(db, a.id, list(dict.fromkeys(pids))) if pids else 0
    return {"id": a.id, "name": a.name, "members": n}


@mkt.get("/mkt/campaigns/{campaign_id}/messages")
def campaign_messages(campaign_id: str, db: Session = Depends(get_db)):
    """Recipient-level view for the campaign detail page."""
    import models_ext as mx
    person_name = {p.id: p.full_name for p in db.query(models.Person).all()}
    rows = (db.query(mx.EmailMessage).filter_by(campaign_id=campaign_id)
            .limit(500).all())
    msg_ids = {m.id for m in rows}
    events: dict[str, list] = {}
    if msg_ids:
        for e in db.query(mx.DeliveryEvent).all():
            if e.message_id in msg_ids:
                events.setdefault(e.message_id, []).append(e.event_type)
    return [{"id": m.id, "to": m.to_email,
             "person": person_name.get(m.person_id, ""),
             "variant": m.variant, "status": m.status,
             "events": events.get(m.id, [])} for m in rows]


@mkt.get("/mkt/segments-brief")
def segments_brief(db: Session = Depends(get_db)):
    import models_segments as ms
    from abm_platform.services import segments as segsvc
    out = []
    for s in db.query(ms.SegmentDef).all():
        try:
            size = len(segsvc.evaluate(db, s.id, limit=500))
        except Exception:  # noqa: BLE001
            size = 0
        out.append({"id": s.id, "name": s.name,
                    "type": "dynamic" if s.is_dynamic else "list", "size": size})
    return out


class CampaignReq(BaseModel):
    name: str
    audience_id: str
    subject: str
    body: str                              # merge tags: {first_name} etc.


@mkt.post("/mkt/campaigns", status_code=201)
def create_campaign(req: CampaignReq, db: Session = Depends(get_db)):
    from abm_platform.services import marketing
    c = marketing.create_campaign(db, req.name, req.audience_id, req.subject, req.body)
    return {"id": c.id, "name": c.name, "status": c.status}


@mkt.get("/mkt/campaigns")
def list_campaigns(db: Session = Depends(get_db)):
    import models_ext as mx
    from abm_platform.services import marketing
    out = []
    for c in (db.query(mx.EmailCampaign).order_by(mx.EmailCampaign.created_at.desc())
              .limit(50).all()):
        try:
            rep = marketing.campaign_report(db, c.id)
        except Exception:  # noqa: BLE001
            rep = {}
        out.append({"id": c.id, "name": c.name, "subject": c.subject,
                    "status": c.status, "scheduled_at": str(c.scheduled_at or ""),
                    "report": rep})
    return out


@mkt.post("/mkt/campaigns/{campaign_id}/send")
def send_campaign(campaign_id: str, db: Session = Depends(get_db)):
    """SEND-SAFE: dry-run transport — messages are built, personalized, logged
    and analytics-tracked, but nothing reaches a real inbox until SES creds
    exist. C-suite is always held for human review."""
    from abm_platform.services import marketing
    try:
        return marketing.send_campaign(db, campaign_id, transport="dry_run")
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(e)[:200])


@mkt.get("/mkt/campaigns/{campaign_id}/report")
def campaign_report(campaign_id: str, db: Session = Depends(get_db)):
    from abm_platform.services import marketing
    return marketing.campaign_report(db, campaign_id)


# ── document uploads (dossiers) ──────────────────────────────
@router.get("/uploads")
def uploads(org_id: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(models.DocumentUpload).order_by(models.DocumentUpload.created_at.desc())
    if org_id:
        q = q.filter(models.DocumentUpload.org_id == org_id)
    return [{"id": u.id, "filename": u.filename, "kind": u.import_kind,
             "org_id": u.org_id, "size": u.file_size, "status": u.status,
             "uploaded_by": u.uploaded_by, "notes": u.notes,
             "summary": (u.extracted_summary or "")[:200],
             "created_at": str(u.created_at)} for u in q.limit(100).all()]


@router.post("/uploads", status_code=201)
async def upload_doc(file: UploadFile = File(...), org_id: str = Form(None),
                     notes: str = Form(""), uploaded_by: str = Form("OS"),
                     db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="file too large (100MB max)")
    u = models.DocumentUpload(org_id=org_id or None, filename=file.filename,
                              content_type=file.content_type, file_size=len(data),
                              file_data=data, uploaded_by=uploaded_by, notes=notes,
                              import_kind="document", status="uploaded")
    db.add(u); db.commit()
    return {"id": u.id, "filename": u.filename, "size": u.file_size}


@router.get("/uploads/{upload_id}/download")
def download_doc(upload_id: str, db: Session = Depends(get_db)):
    u = db.get(models.DocumentUpload, upload_id)
    if u is None:
        raise HTTPException(status_code=404, detail="upload not found")
    return Response(content=u.file_data or b"",
                    media_type=u.content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{u.filename}"'})


@router.post("/uploads/{upload_id}/process")
def process_doc(upload_id: str, db: Session = Depends(get_db)):
    """Run the existing ETL document processor (text extraction + contact/entity
    detection) on an uploaded dossier."""
    u = db.get(models.DocumentUpload, upload_id)
    if u is None:
        raise HTTPException(status_code=404, detail="upload not found")
    try:
        from etl.document_reader import process_uploaded_document
        result = process_uploaded_document(db, u)
        db.commit()
        return {"id": u.id, "status": u.status, "result": str(result)[:400]}
    except Exception as e:  # noqa: BLE001
        db.rollback()
        u.status = "error"
        u.processing_notes = str(e)[:400]
        db.commit()
        return {"id": u.id, "status": "error", "error": str(e)[:200]}
