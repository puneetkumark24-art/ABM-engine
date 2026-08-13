"""Mailchimp-style campaign authoring workspace, provider-neutral and send-safe."""
from __future__ import annotations
import html
import re
from urllib.parse import urlparse
from datetime import datetime
from sqlalchemy.orm import Session
import models
import models_ext as mx
from . import marketing, marketing_ext

ALLOWED_BLOCKS = {"heading", "text", "button", "image", "divider", "spacer", "html"}
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
UNSAFE_HTML = re.compile(r"<(script|iframe|object|embed|form|meta|base)\b|\bon\w+\s*=|javascript:|data:text/html", re.I)


def _safe_url(value: str, *, allow_mailto=False) -> str:
    parsed=urlparse((value or "").strip())
    allowed={"http","https"}|({"mailto"} if allow_mailto else set())
    if parsed.scheme.lower() not in allowed or (parsed.scheme!="mailto" and not parsed.netloc):
        raise ValueError("URL must be an absolute http(s) URL")
    return value.strip()


def create_brand(db: Session, **data) -> mx.EmailBrandProfile:
    for key in ("primary_color", "accent_color"):
        if data.get(key) and not COLOR.match(data[key]):
            raise ValueError(f"{key} must be #RRGGBB")
    brand = mx.EmailBrandProfile(**data); db.add(brand); db.commit(); return brand


def _render_blocks(blocks: list[dict], brand: mx.EmailBrandProfile | None) -> str:
    out = []
    for block in blocks or []:
        kind = block.get("type")
        if kind not in ALLOWED_BLOCKS: raise ValueError(f"unsupported block type: {kind}")
        text = html.escape(str(block.get("text", "")))
        if kind == "heading": out.append(f'<h2 style="margin:0 0 16px">{text}</h2>')
        elif kind == "text": out.append(f'<p style="line-height:1.6">{text}</p>')
        elif kind == "button":
            url = html.escape(_safe_url(str(block.get("url", "")),allow_mailto=True), quote=True)
            color = brand.accent_color if brand else "#2563eb"
            out.append(f'<p><a href="{url}" style="background:{color};color:#fff;padding:12px 18px;text-decoration:none;border-radius:6px">{text}</a></p>')
        elif kind == "image": out.append(f'<img src="{html.escape(_safe_url(str(block.get("url", ""))), quote=True)}" alt="{text}" style="max-width:100%;height:auto">')
        elif kind == "divider": out.append("<hr>")
        elif kind == "spacer": out.append(f'<div style="height:{max(4,min(int(block.get("height",24)),100))}px"></div>')
        elif kind == "html":
            raw=str(block.get("html", ""))
            if UNSAFE_HTML.search(raw): raise ValueError("unsafe custom HTML")
            out.append(raw)
    return "".join(out)


def render_campaign(db: Session, campaign: mx.EmailCampaign, person=None) -> dict:
    brand = db.get(mx.EmailBrandProfile, campaign.brand_profile_id) if campaign.brand_profile_id else None
    body = _render_blocks(campaign.content_blocks or [], brand) if campaign.content_blocks else (campaign.body or "")
    footer = brand.footer_html if brand else ""
    styled = f'<div style="font-family:{brand.font_family if brand else "Arial,sans-serif"};max-width:640px;margin:auto">{body}{footer}</div>'
    return {"subject": marketing_ext.render_merge(db, campaign.subject or "", person),
            "html": marketing_ext.render_merge(db, styled, person)}


def save_campaign(db: Session, campaign_id: str, changes: dict, actor="operator", note="autosave"):
    c = db.get(mx.EmailCampaign, campaign_id)
    if not c: raise ValueError("campaign not found")
    allowed = {"name", "audience_id", "subject", "body", "content_blocks", "brand_profile_id", "ab_config"}
    for k, v in changes.items():
        if k in allowed: setattr(c, k, v)
    c.version = (c.version or 1) + 1; c.approval_status = "draft"; c.updated_at = datetime.utcnow()
    snap = {k: getattr(c, k) for k in allowed}
    db.add(mx.EmailCampaignRevision(campaign_id=c.id, version=c.version, snapshot=snap, actor=actor, note=note))
    db.commit(); return c


def duplicate(db: Session, campaign_id: str, name: str | None = None):
    src = db.get(mx.EmailCampaign, campaign_id)
    if not src: raise ValueError("campaign not found")
    c = marketing.create_campaign(db, name or f"{src.name} (copy)", src.audience_id, src.subject, src.body, src.ab_config)
    c.content_blocks=list(src.content_blocks or []); c.brand_profile_id=src.brand_profile_id; db.commit(); return c


def preview(db: Session, campaign_id: str, person_id: str | None = None):
    c=db.get(mx.EmailCampaign,campaign_id)
    if not c: raise ValueError("campaign not found")
    p=db.get(models.Person,person_id) if person_id else db.query(models.Person).filter_by(is_active=True).first()
    rendered=render_campaign(db,c,p)
    return {**rendered,"person_id":p.id if p else None,"desktop_width":640,"mobile_width":375,
            "preflight":marketing.campaign_preflight(db,campaign_id)}


def approve(db:Session,campaign_id:str,actor:str,decision:str,note:str=""):
    c=db.get(mx.EmailCampaign,campaign_id)
    if not c: raise ValueError("campaign not found")
    if decision not in {"approve","reject"}: raise ValueError("decision must be approve or reject")
    check=marketing.campaign_preflight(db,campaign_id)
    if decision=="approve" and not check["ready_for_live"]: raise ValueError("preflight must pass before approval")
    c.approval_status="approved" if decision=="approve" else "rejected"
    c.version=(c.version or 1)+1
    db.add(mx.EmailCampaignRevision(campaign_id=c.id,version=c.version,
        snapshot={"approval_status":c.approval_status},actor=actor,note=note or decision))
    db.commit();return c


def restore(db:Session,campaign_id:str,version:int,actor="operator"):
    rev=db.query(mx.EmailCampaignRevision).filter_by(campaign_id=campaign_id,version=version).first()
    if not rev: raise ValueError("revision not found")
    return save_campaign(db,campaign_id,rev.snapshot,actor,f"restored version {version}")


def create_template(db:Session,name:str,subject:str,body:str,persona_target:str|None=None):
    t=models.Template(name=name,channel="email",subject=subject,body=body,
                      persona_target=persona_target,is_active=True)
    db.add(t);db.commit();return t
