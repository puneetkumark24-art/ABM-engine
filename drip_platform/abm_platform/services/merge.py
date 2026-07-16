"""Merge engine — completes the duplicate pipeline (detection existed, Phase 9).
CRM-004 discipline: merging re-points every association to the keeper, fills
the keeper's blank fields from the loser, NEVER deletes history, and
deactivates (not deletes) the loser. Fully audited."""
from __future__ import annotations
from sqlalchemy.orm import Session
import models
import models_ext as mx
import models_p10 as p10

# Person-FK re-point map: (model, attr). Unique-constrained tables handled specially.
_SIMPLE_REPOINT = [
    (models.Draft, "person_id"),
    (models.ActivityLog, "person_id"),
    (mx.EmailMessage, "person_id"),
    (mx.LiAction, "person_id"),
    (mx.FormSubmission, "person_id"),
    (mx.Touch, "person_id"),
    (mx.AiGeneration, "person_id"),
]

_FILL_FIELDS = ["primary_email", "secondary_email", "phone", "mobile", "whatsapp",
                "linkedin_url", "current_title", "department", "seniority_level",
                "persona", "city", "country", "background_notes", "pitch_notes"]


def merge_persons(db: Session, keep_id: str, lose_id: str, actor: str = "system") -> dict:
    keeper = db.get(models.Person, keep_id)
    loser = db.get(models.Person, lose_id)
    if keeper is None or loser is None:
        raise ValueError("both persons must exist")
    if keep_id == lose_id:
        raise ValueError("cannot merge a person into themselves")

    moved: dict[str, int] = {}

    # 1) simple FK re-points
    for model, attr in _SIMPLE_REPOINT:
        n = 0
        for row in db.query(model).filter(getattr(model, attr) == lose_id).all():
            setattr(row, attr, keep_id); n += 1
        if n:
            moved[model.__tablename__] = n

    # 2) unique-constrained tables: move unless keeper already has the slot
    n = 0
    for oc in db.query(models.OutreachChannel).filter_by(person_id=lose_id).all():
        clash = (db.query(models.OutreachChannel)
                 .filter_by(person_id=keep_id, channel=oc.channel).first())
        if clash is None:
            oc.person_id = keep_id; n += 1
    moved["outreach_channels"] = n

    n = 0
    for bc in db.query(models.BuyingCommitteeMember).filter_by(person_id=lose_id).all():
        clash = (db.query(models.BuyingCommitteeMember)
                 .filter_by(org_id=bc.org_id, person_id=keep_id, product_id=bc.product_id).first())
        if clash is None:
            bc.person_id = keep_id; n += 1
    moved["buying_committee_members"] = n

    n = 0
    for enr in db.query(models.SequenceEnrollment).filter_by(person_id=lose_id).all():
        clash = (db.query(models.SequenceEnrollment)
                 .filter_by(person_id=keep_id, sequence_id=enr.sequence_id).first())
        if clash is None:
            enr.person_id = keep_id
            enr.org_id = keeper.current_org_id or enr.org_id
            n += 1
        else:
            enr.status = "EXITED"; enr.pause_reason = f"merged into {keep_id}"
    moved["sequence_enrollments"] = n

    # relationships: both directions
    n = 0
    for pr in db.query(models.PersonRelationship).filter_by(to_person_id=lose_id).all():
        pr.to_person_id = keep_id; n += 1
    for pr in db.query(models.PersonRelationship).filter_by(from_person_id=lose_id).all():
        pr.from_person_id = keep_id; n += 1
    moved["person_relationships"] = n

    # engagement rollup: combine counts, keep max score; recompute later anyway
    le = db.query(p10.PersonEngagement).filter_by(person_id=lose_id).first()
    ke = db.query(p10.PersonEngagement).filter_by(person_id=keep_id).first()
    if le is not None:
        if ke is None:
            le.person_id = keep_id
        else:
            for f in ("opens", "clicks", "replies", "li_accepts", "li_replies",
                      "form_submits", "bounces"):
                setattr(ke, f, (getattr(ke, f) or 0) + (getattr(le, f) or 0))
            ke.engagement_score = max(ke.engagement_score or 0, le.engagement_score or 0)
            db.delete(le)   # rollup row, not history — raw events all preserved

    # 3) fill keeper's blanks from loser (never overwrite)
    filled = []
    for f in _FILL_FIELDS:
        if not getattr(keeper, f, None) and getattr(loser, f, None):
            setattr(keeper, f, getattr(loser, f)); filled.append(f)

    # safety flags travel with the strictest interpretation
    keeper.do_not_contact = keeper.do_not_contact or loser.do_not_contact
    if loser.consent_status == "denied":
        keeper.consent_status = "denied"
    keeper.replied = keeper.replied or loser.replied

    # 4) deactivate loser — never delete
    loser.is_active = False
    loser.background_notes = ((loser.background_notes or "")
                              + f"\n[MERGED into {keep_id} by {actor}]")

    # 5) resolve any pending merge candidate + audit
    for c in db.query(mx.MergeCandidate).filter(
            ((mx.MergeCandidate.a_id == keep_id) & (mx.MergeCandidate.b_id == lose_id)) |
            ((mx.MergeCandidate.a_id == lose_id) & (mx.MergeCandidate.b_id == keep_id))).all():
        c.status = "merged"
    db.add(models.AuditLog(action="person.merge", actor=actor,
                           details=f"kept={keep_id} lost={lose_id} moved={moved} filled={filled}"))
    db.commit()
    return {"kept": keep_id, "deactivated": lose_id, "repointed": moved, "filled": filled}
