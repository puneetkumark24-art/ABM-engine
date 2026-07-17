"""Landing-page renderer (Phase 12) — pages stop being database rows and start
being actual served pages: blocks -> HTML, embedded consent-enforcing form,
tracking.js included, submission wired to the CRM pipeline, gated-asset
delivery via signed expiring link on the thank-you page."""
from __future__ import annotations
import html as html_mod
from sqlalchemy.orm import Session
import models_ext as mx
from . import landing, assets as assets_svc

_PAGE_SHELL = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
 body{{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#17222e;background:#f6f8fa}}
 .wrap{{max-width:760px;margin:0 auto;padding:40px 24px}}
 .hero{{background:linear-gradient(135deg,#0b1f38,#1c4a6e);color:#fff;border-radius:12px;padding:44px 36px;margin-bottom:24px}}
 .hero h1{{margin:0 0 10px;font-size:30px}} .hero p{{color:#cfe6f2;margin:0;font-size:16px}}
 .block{{background:#fff;border:1px solid #dbe3ea;border-radius:12px;padding:26px 28px;margin-bottom:18px;line-height:1.6}}
 .cta{{display:inline-block;background:#0e8390;color:#fff;text-decoration:none;padding:12px 26px;border-radius:8px;font-weight:700}}
 form label{{display:block;font-size:13px;font-weight:600;margin:12px 0 4px}}
 form input[type=text],form input[type=email]{{width:100%;padding:10px;border:1px solid #c6d2dc;border-radius:8px;font-size:14px;box-sizing:border-box}}
 .consent{{font-size:12.5px;color:#54636f;margin:14px 0}} button{{background:#0b1f38;color:#fff;border:none;border-radius:8px;padding:12px 28px;font-size:15px;font-weight:700;cursor:pointer}}
 .err{{color:#b3382f;font-size:13px}} .ok{{background:#eafaf0;border:1px solid #159a52;border-radius:8px;padding:14px 16px}}
</style></head><body><div class="wrap">{body}</div>
<script src="/t/js"></script></body></html>"""


def _render_block(b: dict) -> str:
    t = b.get("type", "text")
    if t == "hero":
        return (f'<div class="hero"><h1>{html_mod.escape(b.get("title",""))}</h1>'
                f'<p>{html_mod.escape(b.get("subtitle",""))}</p></div>')
    if t == "text":
        return f'<div class="block">{b.get("html") or html_mod.escape(b.get("text",""))}</div>'
    if t == "cta":
        return (f'<div class="block" style="text-align:center">'
                f'<a class="cta" href="{html_mod.escape(b.get("href","#"))}">'
                f'{html_mod.escape(b.get("label","Learn more"))}</a></div>')
    if t == "bullets":
        lis = "".join(f"<li>{html_mod.escape(x)}</li>" for x in b.get("items", []))
        return f'<div class="block"><ul>{lis}</ul></div>'
    return ""


def _render_form(form: "mx.FormDef", slug: str) -> str:
    fields = ""
    for f in (form.fields or []):
        key = f["key"]; label = f.get("label", key.title())
        typ = "email" if key == "email" else "text"
        req = "required" if f.get("required") else ""
        fields += (f'<label for="{key}">{html_mod.escape(label)}'
                   f'{" *" if f.get("required") else ""}</label>'
                   f'<input type="{typ}" id="{key}" name="{key}" {req}>')
    consent = ""
    if form.consent_required:
        consent = ('<div class="consent"><label>'
                   '<input type="checkbox" name="consent_given" value="true" required> '
                   'I consent to Decimal Technologies contacting me about relevant '
                   'products and services. (PDPL)</label></div>')
    return (f'<div class="block"><form method="post" action="/p/{slug}/submit">'
            f'{fields}{consent}<div style="margin-top:14px">'
            f'<button type="submit">Download</button></div></form></div>')


def render_page(db: Session, slug: str) -> str | None:
    page = db.query(mx.LandingPage).filter_by(slug=slug, status="published").first()
    if page is None:
        return None
    body = "".join(_render_block(b) for b in (page.blocks or []))
    if page.form_id:
        form = db.get(mx.FormDef, page.form_id)
        if form is not None:
            body += _render_form(form, slug)
    return _PAGE_SHELL.format(title=html_mod.escape(page.title or slug), body=body)


def handle_submit(db: Session, slug: str, data: dict, utm: dict | None = None,
                  visitor_id: str | None = None) -> tuple[str, bool]:
    """Process a public submission: CRM upsert + consent + gated-asset link +
    visitor identification. Returns (thank-you HTML, success)."""
    page = db.query(mx.LandingPage).filter_by(slug=slug, status="published").first()
    if page is None or not page.form_id:
        return _PAGE_SHELL.format(title="Not found",
                                  body='<div class="block err">Page not found.</div>'), False
    consent = str(data.pop("consent_given", "")).lower() in ("true", "on", "1")
    sub, reason = landing.submit(db, page.form_id, data, utm=utm, consent_given=consent)
    if sub is None:
        return _PAGE_SHELL.format(title=page.title or slug,
                                  body=f'<div class="block err">Submission failed: '
                                       f'{html_mod.escape(reason)}</div>'), False
    # identify web visitor -> person (joins anonymous history to CRM)
    if visitor_id and sub.person_id:
        from . import tracking
        tracking.identify_visitor(db, visitor_id, sub.person_id)
    # gated asset -> signed expiring link
    dl = ""
    if page.asset_id:
        token = assets_svc.sign_link(page.asset_id, ttl_seconds=3600)
        dl = (f'<p><a class="cta" href="/px/assets/download/{token}">'
              f'Download your document</a> <br>'
              f'<span class="consent">(link valid for 1 hour)</span></p>')
    body = (f'<div class="block ok"><h2>Thank you!</h2>'
            f'<p>Your submission has been received.</p>{dl}</div>')
    return _PAGE_SHELL.format(title="Thank you", body=body), True
