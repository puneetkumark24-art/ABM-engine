"""Native tracking stack — the Mailchimp/Segment layer, owned.

1. Pixel tracking:   <img src="/t/o/{message_id}.gif"> → open event (approximate
                     by design: Apple Mail/Gmail prefetch inflates opens — we
                     record but weight clicks higher everywhere).
2. Link tracking:    every href rewritten to /t/c/{token} → click logged →
                     HTTP 302 to the real URL with UTM params appended.
                     Far more reliable than opens.
3. tracking.js:      landing-page script → POST /t/e web events (page views,
                     scroll, downloads, form starts, pricing views).
4. Cookies:          visitor_id links anonymous web activity; identified when a
                     form ties the visitor to a Person → activity joins the CRM.
5. UTM:              utm_source/campaign/medium/content/persona stamped on every
                     rewritten link and captured on every web event.
6. Event stream:     everything lands in delivery_events / web_events and feeds
                     engagement rollup → lead score → automation triggers.
"""
from __future__ import annotations
import hashlib
import hmac as hmac_mod
import os
import re
import uuid
from datetime import datetime
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from sqlalchemy.orm import Session
import models
import models_ext as mx
import models_p11 as p11
from abm_platform.events import Event, publish

_SECRET = os.environ.get("TRACKING_SECRET", "drip-tracking-dev-secret").encode()

# transparent 1x1 GIF bytes (served by the pixel endpoint)
PIXEL_GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!"
             b"\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00"
             b"\x00\x02\x02D\x01\x00;")

TRACKING_JS = """(function(){
  function vid(){var m=document.cookie.match(/drip_vid=([^;]+)/);if(m)return m[1];
    var v='v-'+Math.random().toString(36).slice(2)+Date.now().toString(36);
    document.cookie='drip_vid='+v+';path=/;max-age=31536000;SameSite=Lax';return v;}
  function utm(){var q=new URLSearchParams(location.search),u={};
    ['source','campaign','medium','content','persona'].forEach(function(k){
      var val=q.get('utm_'+k); if(val)u['utm_'+k]=val;});return u;}
  function send(type,props){try{navigator.sendBeacon('/t/e',JSON.stringify(
    {visitor_id:vid(),event_type:type,url:location.pathname,utm:utm(),props:props||{}}
  ));}catch(e){}}
  send('page_view',{title:document.title});
  var maxScroll=0;window.addEventListener('scroll',function(){
    var p=Math.round((scrollY+innerHeight)/document.body.scrollHeight*100);
    if(p>=90&&maxScroll<90){maxScroll=p;send('scroll',{depth:90});}});
  document.addEventListener('click',function(e){
    var a=e.target.closest('a');if(!a)return;
    if(/\\.(pdf|docx|pptx)$/i.test(a.href))send('download',{href:a.href});
    if(/pricing/i.test(a.href))send('pricing_view',{href:a.href});});
  window.dripTrack=send;
})();"""


def _sign(payload: str) -> str:
    return hmac_mod.new(_SECRET, payload.encode(), hashlib.sha256).hexdigest()[:16]


# ── link rewriting (Mailchimp-style) ─────────────────────────
_HREF_RE = re.compile(r'''href\s*=\s*(["'])(https?://.+?)\1''', re.I)


_TRACKED_HREF_RE = re.compile(r'href\s*=\s*(["\'])[^"\']*/t/c/[A-Za-z0-9]+\1', re.I)

SAFE_SCHEMES = {"http", "https"}


def is_safe_redirect(url: str | None) -> bool:
    """Reject javascript:, data:, file:, vbscript:, protocol-relative //evil,
    and anything else that would turn /t/c/<token> into an open redirect to a
    scheme the browser executes rather than navigates to."""
    if not url:
        return False
    stripped = url.strip()
    if stripped.startswith("//"):      # protocol-relative: inherits https, hides host
        return False
    try:
        parsed = urlparse(stripped)
    except ValueError:
        return False
    return parsed.scheme.lower() in SAFE_SCHEMES and bool(parsed.netloc)


def rewrite_links(db: Session, body_html: str, message_id: str,
                  utm: dict | None = None, base_url: str = "") -> str:
    """Rewrite every http(s) link to a tracked redirect. UTM params are stored
    on the TrackedLink and appended at redirect time."""
    utm = utm or {}
    body_html = body_html or ""
    # Token reuse below keeps a re-render of the ORIGINAL body stable. This
    # guard covers the other case, which is the one retries actually hit:
    # re-running over the already-instrumented OUTPUT, where the rewritten
    # href is itself an https URL and would be captured again.
    if _TRACKED_HREF_RE.search(body_html):
        return body_html

    def _sub(m):
        quote, original = m.group(1), m.group(2)
        if not is_safe_redirect(original):
            return m.group(0)              # leave untrackable links untouched
        existing = (db.query(p11.TrackedLink)
                    .filter_by(message_id=message_id, original_url=original).first())
        if existing:
            token = existing.token
            if (existing.utm or {}) != utm:
                existing.utm = utm
        else:
            token = uuid.uuid4().hex[:20] + _sign(original + message_id)[:12]
            db.add(p11.TrackedLink(token=token, message_id=message_id,
                                   original_url=original, utm=utm))
        return f'href={quote}{base_url.rstrip("/")}/t/c/{token}{quote}'

    out = _HREF_RE.sub(_sub, body_html)
    db.commit()
    return out


def inject_pixel(body_html: str, message_id: str, base_url: str = "") -> str:
    pixel_src = f"{base_url}/t/o/{message_id}.gif"
    if pixel_src in (body_html or ""):
        return body_html          # idempotent: exactly one pixel per message
    pixel = f'<img src="{pixel_src}" width="1" height="1" alt="">'
    if "</body>" in (body_html or ""):
        return body_html.replace("</body>", pixel + "</body>")
    return (body_html or "") + pixel


def prepare_email(db: Session, body_html: str, message_id: str,
                  utm: dict | None = None, base_url: str = "") -> str:
    """Full outbound preparation: rewrite links + inject open pixel."""
    return inject_pixel(rewrite_links(db, body_html, message_id, utm, base_url),
                        message_id, base_url)


# ── event recording (endpoint backends) ──────────────────────
def record_open(db: Session, message_id: str, meta: dict | None = None) -> None:
    """Pixel fired. Deduped per (message, day) so image-cache prefetch doesn't
    stack; opens are treated as approximate everywhere downstream."""
    msg = db.query(mx.EmailMessage).filter_by(id=message_id).first()
    if msg is None:
        return
    day = datetime.utcnow().strftime("%Y%m%d")
    pid = f"pixel:{message_id}:{day}"
    if db.query(mx.DeliveryEvent).filter_by(provider_event_id=pid).first():
        return
    db.add(mx.DeliveryEvent(message_id=message_id, event_type="open",
                            provider="pixel", provider_event_id=pid,
                            meta=meta or {}))
    if msg and msg.status in ("queued", "sent", "delivered"):
        msg.status = "opened"      # never downgrade clicked/replied/bounced
    db.commit()
    _rescore_message_account(db, msg)
    publish(Event("email.event.open", key=message_id, payload=meta or {}))


def record_click(db: Session, token: str, visitor_id: str | None = None,
                 meta: dict | None = None) -> str | None:
    """Click hit. Logs, links visitor cookie if present, returns the redirect
    URL with UTM appended — or None for unknown tokens."""
    link = db.query(p11.TrackedLink).filter_by(token=token).first()
    if link is None:
        return None
    # Re-validated at redirect time, not only at rewrite time: this endpoint is
    # public, and a row written by any other code path would otherwise make it a
    # working open redirect under our own sending domain.
    if not is_safe_redirect(link.original_url):
        return None
    link.clicks = (link.clicks or 0) + 1
    pid = f"click:{token}:{link.clicks}"
    db.add(mx.DeliveryEvent(message_id=link.message_id, event_type="click",
                            provider="redirect", provider_event_id=pid,
                            meta={**(meta or {}), "url": link.original_url}))
    msg = db.query(mx.EmailMessage).filter_by(id=link.message_id).first()
    person_id = msg.person_id if msg else None
    if msg:
        msg.status = "clicked"
    if visitor_id:
        _touch_visitor(db, visitor_id, person_id=person_id, utm=link.utm)
    db.commit()
    _rescore_message_account(db, msg)
    publish(Event("email.event.click", key=link.message_id,
                  payload={"url": link.original_url}))

    # append UTM to destination
    parts = list(urlparse(link.original_url))
    q = dict(parse_qsl(parts[4]))
    q.update({k: v for k, v in (link.utm or {}).items()})
    parts[4] = urlencode(q)
    return urlunparse(parts)


def _rescore_message_account(db: Session, msg: mx.EmailMessage | None) -> None:
    if not msg:
        return
    person = db.get(models.Person, msg.person_id)
    if person and person.current_org_id:
        from . import engagement
        engagement.rollup_org(db, person.current_org_id)


def _touch_visitor(db: Session, visitor_id: str, person_id: str | None = None,
                   utm: dict | None = None) -> p11.WebVisitor:
    v = db.query(p11.WebVisitor).filter_by(visitor_id=visitor_id).first()
    if v is None:
        v = p11.WebVisitor(visitor_id=visitor_id, first_utm=utm or {})
        db.add(v)
    v.last_seen = datetime.utcnow()
    if person_id and not v.person_id:
        v.person_id = person_id      # identification: cookie now joined to CRM
    return v


def record_web_event(db: Session, visitor_id: str, event_type: str,
                     url: str = "", props: dict | None = None,
                     utm: dict | None = None) -> p11.WebEvent:
    """tracking.js beacon. If the visitor is identified, the event lands on the
    person's timeline and feeds engagement."""
    v = _touch_visitor(db, visitor_id, utm=utm)
    v.pages_viewed = (v.pages_viewed or 0) + (1 if event_type == "page_view" else 0)
    ev = p11.WebEvent(visitor_id=visitor_id, person_id=v.person_id,
                      event_type=event_type, url=url, props=props or {},
                      utm=utm or {})
    db.add(ev); db.commit()
    publish(Event(f"web.{event_type}", key=v.person_id or visitor_id,
                  payload={"url": url, **(props or {})}))
    return ev


def identify_visitor(db: Session, visitor_id: str, person_id: str) -> int:
    """Form submitted with a known email: bind cookie -> person and backfill
    person_id onto the visitor's past anonymous events. Returns events linked."""
    v = _touch_visitor(db, visitor_id, person_id=person_id)
    v.person_id = person_id
    n = 0
    for ev in db.query(p11.WebEvent).filter_by(visitor_id=visitor_id,
                                               person_id=None).all():
        ev.person_id = person_id; n += 1
    db.commit()
    return n
