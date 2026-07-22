"""
graph_query.py — the bounded knowledge-graph query layer (Phase 7 of
transformation/AI_Intelligence_Layer_Architecture.md).

Per the architecture doc: "no vector store, embeddings, or graph database
exists — and the recommendation is deliberately NOT to bolt on Neo4j for
v1." The graph is relational, living entirely in tables that already
shipped (Organization/OrgRelationship/Person/PersonRelationship/
VendorIntelligence/BuyingCommitteeMember). What was missing was a query
layer so agents ask graph-shaped questions ("who's on the buying
committee, and who has a warm path to Decimal") without hand-rolling
recursive CTEs inside every agent's prompt-construction code — and,
critically, so agents NEVER get raw SQL access. Every function here is a
parameterized, indexed, read-only query returning a compact JSON-safe
dict — this is the `tool_binding` shape Module 26 (Copilot) already
specifies, reused for Tiers A-D uniformly rather than inventing a second
tool-calling convention for agents vs. Copilot.

No function in this module writes to the database.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

import models


def get_buying_committee(db: Session, org_id: str) -> dict:
    """Who's on the buying committee for this account, with their role,
    engagement level, and reporting line where known."""
    rows = (
        db.query(models.BuyingCommitteeMember)
        .filter(models.BuyingCommitteeMember.org_id == org_id)
        .all()
    )
    members = []
    for r in rows:
        person = db.query(models.Person).filter(models.Person.id == r.person_id).first()
        if not person:
            continue
        manager = None
        if person.reporting_manager_id:
            mgr = db.query(models.Person).filter(models.Person.id == person.reporting_manager_id).first()
            manager = mgr.full_name if mgr else None
        members.append({
            "person_id": person.id,
            "name": person.full_name,
            "title": person.current_title,
            "seniority_level": person.seniority_level,
            "committee_role": r.committee_role,
            "engagement": r.engagement,
            "reports_to": manager,
            "product_id": r.product_id,
        })
    return {"org_id": org_id, "buying_committee": members, "count": len(members)}


def get_warm_paths(db: Session, org_id: str) -> dict:
    """Which people at this account have a person-to-person relationship
    (knows/introduced_by/worked_with/referred_by) back to someone at
    Decimal or a known contact elsewhere in the graph — i.e. a path that
    isn't cold outreach."""
    persons = db.query(models.Person).filter(models.Person.current_org_id == org_id).all()
    person_ids = {p.id for p in persons}
    if not person_ids:
        return {"org_id": org_id, "warm_paths": [], "count": 0}

    rels = (
        db.query(models.PersonRelationship)
        .filter(models.PersonRelationship.to_person_id.in_(person_ids))
        .all()
    )
    paths = []
    for r in rels:
        if r.from_type == "decimal" or (r.from_person_id and r.from_person_id not in person_ids):
            to_person = next((p for p in persons if p.id == r.to_person_id), None)
            if not to_person:
                continue
            paths.append({
                "to_person": to_person.full_name,
                "to_person_id": to_person.id,
                "from_name": r.from_name,
                "from_type": r.from_type,
                "relationship_type": r.relationship_type,
                "strength": r.strength,
                "context": r.context,
            })
    return {"org_id": org_id, "warm_paths": paths, "count": len(paths)}


def get_subsidiary_tree(db: Session, org_id: str, max_depth: int = 3) -> dict:
    """Walks OrgRelationship edges of type subsidiary_of/parent_of outward
    from org_id, bounded by max_depth to avoid runaway recursion on a
    malformed/cyclic edge set (defensive — the org graph is small today,
    but this must not become an unbounded query as it grows)."""
    visited = {org_id}
    frontier = [org_id]
    tree = []
    for _depth in range(max_depth):
        if not frontier:
            break
        rels = (
            db.query(models.OrgRelationship)
            .filter(
                models.OrgRelationship.relationship_type.in_(["subsidiary_of", "parent_of"]),
                (models.OrgRelationship.from_org_id.in_(frontier))
                | (models.OrgRelationship.to_org_id.in_(frontier)),
            )
            .all()
        )
        next_frontier = []
        for r in rels:
            other = r.to_org_id if r.from_org_id in frontier else r.from_org_id
            if other in visited:
                continue
            visited.add(other)
            next_frontier.append(other)
            org = db.query(models.Organization).filter(models.Organization.id == other).first()
            tree.append({
                "org_id": other,
                "name": org.canonical_name if org else None,
                "relationship_type": r.relationship_type,
                "strength": r.strength,
                "confidence": r.confidence,
            })
        frontier = next_frontier
    return {"org_id": org_id, "subsidiaries": tree, "count": len(tree)}


def get_vendor_relationships(db: Session, org_id: str) -> dict:
    """Known vendors/competitors/partners for this account — combines the
    org-level relationship edges (vendor_of/competitor_of/partner_of) with
    the VendorIntelligence row for the account itself, if it happens to
    also be tracked as a vendor (rare, but the query stays correct either
    way rather than assuming an account can't also be a vendor node)."""
    rels = (
        db.query(models.OrgRelationship)
        .filter(
            models.OrgRelationship.relationship_type.in_(["vendor_of", "competitor_of", "partner_of", "serves"]),
            (models.OrgRelationship.from_org_id == org_id) | (models.OrgRelationship.to_org_id == org_id),
        )
        .all()
    )
    out = []
    for r in rels:
        other_id = r.to_org_id if r.from_org_id == org_id else r.from_org_id
        org = db.query(models.Organization).filter(models.Organization.id == other_id).first()
        vi = db.query(models.VendorIntelligence).filter(models.VendorIntelligence.org_id == other_id).first()
        out.append({
            "org_id": other_id,
            "name": org.canonical_name if org else None,
            "relationship_type": r.relationship_type,
            "strength": r.strength,
            "products": vi.products if vi else [],
            "technologies": vi.technologies if vi else [],
        })
    return {"org_id": org_id, "vendor_relationships": out, "count": len(out)}


def build_context_block(db: Session, org_id: str) -> dict:
    """Convenience wrapper — the single call the Bank Intelligence Agent
    (Tier B) actually makes. Bundles all four graph reads into one bounded
    context block, matching Phase 8's Context Engine contract: agents ask
    for 'context for account X', not four separate tool calls each time."""
    return {
        "buying_committee": get_buying_committee(db, org_id)["buying_committee"],
        "warm_paths": get_warm_paths(db, org_id)["warm_paths"],
        "subsidiaries": get_subsidiary_tree(db, org_id)["subsidiaries"],
        "vendor_relationships": get_vendor_relationships(db, org_id)["vendor_relationships"],
    }
