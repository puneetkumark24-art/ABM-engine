"""Module 16 — Workflow Engine (n8n-style, durable).
WFL-001: runs are durable — status/cursor persisted; a waiting run resumes
from its cursor after restart. WFL-005: node configs validated at activation.
Node types: start, condition, delay, email (dry-run via delivery), notify,
approval (suspends until resume), end."""
from __future__ import annotations
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
import models_ext as mx

NODE_TYPES = {"start", "condition", "delay", "email", "notify", "approval", "end"}


def create(db: Session, name: str, nodes: list[dict], edges: list[dict]) -> mx.WorkflowDef:
    wf = mx.WorkflowDef(name=name, nodes=nodes, edges=edges, status="draft")
    _validate(wf)
    db.add(wf); db.commit()
    return wf


def _validate(wf: mx.WorkflowDef) -> None:
    ids = {n["id"] for n in wf.nodes}
    types = {n["id"]: n.get("type") for n in wf.nodes}
    if not any(t == "start" for t in types.values()):
        raise ValueError("workflow needs a start node")
    if not any(t == "end" for t in types.values()):
        raise ValueError("workflow needs an end node")
    for n in wf.nodes:
        if n.get("type") not in NODE_TYPES:
            raise ValueError(f"unknown node type {n.get('type')}")
    for e in wf.edges:
        if e["from"] not in ids or e["to"] not in ids:
            raise ValueError(f"edge references unknown node: {e}")


def activate(db: Session, workflow_id: str) -> mx.WorkflowDef:
    wf = db.get(mx.WorkflowDef, workflow_id)
    _validate(wf)
    wf.status = "active"; db.commit()
    return wf


def start_run(db: Session, workflow_id: str, ctx: dict | None = None) -> mx.WorkflowRun:
    wf = db.get(mx.WorkflowDef, workflow_id)
    start = next(n for n in wf.nodes if n["type"] == "start")
    run = mx.WorkflowRun(workflow_id=workflow_id, ctx=ctx or {}, cursor=start["id"], status="running")
    db.add(run); db.commit()
    return advance_run(db, run.id)


def _next_node(wf: mx.WorkflowDef, node_id: str, branch: str | None = None) -> str | None:
    for e in wf.edges:
        if e["from"] == node_id and (branch is None or e.get("when") in (None, branch)):
            return e["to"]
    return None


def advance_run(db: Session, run_id: str, now: datetime | None = None) -> mx.WorkflowRun:
    """Execute nodes from the cursor until the run finishes or suspends
    (delay not yet elapsed / approval pending). Durable: every step persists."""
    now = now or datetime.utcnow()
    run = db.get(mx.WorkflowRun, run_id)
    if run is None or run.status in ("succeeded", "failed", "cancelled"):
        return run
    wf = db.get(mx.WorkflowDef, run.workflow_id)
    nodes = {n["id"]: n for n in wf.nodes}

    # a waiting run only proceeds if its wait elapsed / approval granted
    if run.status == "waiting" and run.wait_until and run.wait_until > now:
        return run
    run.status = "running"

    guard = 0
    while guard < 100:                                    # loop bound (WFL-005 spirit)
        guard += 1
        node = nodes.get(run.cursor)
        if node is None:
            run.status = "failed"; break
        ntype = node["type"]; cfg = node.get("config", {})

        if ntype == "start":
            _exec(db, run, node, {"started": True})
            run.cursor = _next_node(wf, node["id"])
        elif ntype == "end":
            _exec(db, run, node, {"ended": True})
            run.status = "succeeded"; run.finished_at = now
            break
        elif ntype == "condition":
            field, op, value = cfg.get("field"), cfg.get("op", "eq"), cfg.get("value")
            a = (run.ctx or {}).get(field)
            result = {"eq": a == value, "ne": a != value,
                      "gt": (a or 0) > value, "lt": (a or 0) < value,
                      "exists": a is not None}.get(op, False)
            _exec(db, run, node, {"result": result})
            run.cursor = _next_node(wf, node["id"], branch="true" if result else "false")
        elif ntype == "delay":
            executed = (db.query(mx.NodeExecution)
                        .filter_by(run_id=run.id, node_id=node["id"], status="done").first())
            if executed:
                run.cursor = _next_node(wf, node["id"])
            else:
                until = now + timedelta(minutes=cfg.get("minutes", 0))
                if cfg.get("minutes", 0) <= 0 or until <= now:
                    _exec(db, run, node, {"skipped_delay": True})
                    run.cursor = _next_node(wf, node["id"])
                else:
                    run.status = "waiting"; run.wait_until = until
                    _exec(db, run, node, {"waiting_until": str(until)}, status="waiting")
                    break
        elif ntype == "email":
            from . import delivery
            req = delivery.enqueue(db, message_id=f"wf-{run.id}-{node['id']}",
                                   to_email=(run.ctx or {}).get("email", "demo@example.invalid"),
                                   subject=cfg.get("subject", "(workflow)"),
                                   body=cfg.get("body", ""), transport="dry_run")
            _exec(db, run, node, {"send_request": req.id, "status": req.status})
            run.cursor = _next_node(wf, node["id"])
        elif ntype == "notify":
            from . import notification
            n = notification.send(db, user=cfg.get("user", "Puneet"), kind="workflow",
                                  payload={"run": run.id, "note": cfg.get("note")})
            _exec(db, run, node, {"notification": n.id})
            run.cursor = _next_node(wf, node["id"])
        elif ntype == "approval":
            approved = (run.ctx or {}).get(f"approved:{node['id']}")
            if approved:
                _exec(db, run, node, {"approved": True})
                run.cursor = _next_node(wf, node["id"])
            else:
                run.status = "waiting"; run.wait_until = None
                _exec(db, run, node, {"awaiting_approval": True}, status="waiting")
                break
    db.commit()
    return run


def approve(db: Session, run_id: str, node_id: str) -> mx.WorkflowRun:
    run = db.get(mx.WorkflowRun, run_id)
    ctx = dict(run.ctx or {}); ctx[f"approved:{node_id}"] = True
    run.ctx = ctx
    db.commit()
    return advance_run(db, run_id)


def _exec(db: Session, run: mx.WorkflowRun, node: dict, output: dict, status: str = "done") -> None:
    db.add(mx.NodeExecution(run_id=run.id, node_id=node["id"], status=status, output=output))
