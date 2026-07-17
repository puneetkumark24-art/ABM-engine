# -*- coding: utf-8 -*-
import os, html, shutil, datetime
from globals import *
from modules_part1 import MODULES_1
from modules_part2 import MODULES_2
from modules_part3 import MODULES_3
from modules_part4 import MODULES_4

MODULES = {}
for d in (MODULES_1, MODULES_2, MODULES_3, MODULES_4):
    MODULES.update(d)
MODS = sorted(MODULES.values(), key=lambda m: m["num"])

OUT = "/sessions/adoring-gifted-feynman/mnt/outputs"
REPO = "/tmp/ABM_Enterprise_Platform"
if os.path.exists(REPO): shutil.rmtree(REPO)
os.makedirs(REPO, exist_ok=True)

def w(path, text):
    full = os.path.join(REPO, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(text)

# ---------- per-module markdown ----------
def modfile(m):
    base = m['name'].split(' (')[0].replace(' ','_').replace('/','-').replace('&','and')
    return f"{m['num']}_{base}.md"

def module_md(m):
    L = []
    L.append(f"# Module {m['num']} — {m['name']}\n")
    L.append(f"> **Domain folder:** `{m['folder']}`  \n> **Replaces / equivalent to:** {m['replaces']}\n")
    L.append("## 1. Purpose\n" + m["purpose"] + "\n")
    L.append("## 2. Scope\n**In scope**\n" + "\n".join(f"- {s}" for s in m["scope_in"]) +
             "\n\n**Out of scope**\n" + "\n".join(f"- {s}" for s in m["scope_out"]) + "\n")
    L.append("## 3. Personas\n| Persona | Relationship to module |\n|---|---|\n" +
             "\n".join(f"| {p[0]} | {p[1]} |" for p in m["personas"]) + "\n")
    L.append("## 4. Data Entities & Schema\n")
    for e in m["entities"]:
        L.append(f"### `{e[0]}`\n{e[1]}\n\n```\n{e[2]}\n```\n")
    L.append("## 5. API Contracts\n| Method | Path | Purpose | Responses |\n|---|---|---|---|\n" +
             "\n".join(f"| `{a[0]}` | `{a[1]}` | {a[2]} | {a[3]} |" for a in m["apis"]) + "\n")
    L.append("## 6. Core Workflows\n" + "\n".join(f"{i+1}. {wf}" for i,wf in enumerate(m["workflows"])) + "\n")
    st = m["states"]
    L.append(f"## 7. State Machine — `{st[0]}`\n**States:** {', '.join(st[1])}\n\n**Transitions:** {st[2]}\n")
    L.append("## 8. Events\n**Publishes:** " + ", ".join(f"`{e}`" for e in m["events_pub"]) +
             "\n\n**Subscribes:** " + ", ".join(f"`{e}`" for e in m["events_sub"]) + "\n")
    L.append("## 9. Business Rules\n" + "\n".join(f"- **{r.split(':',1)[0]}:**{r.split(':',1)[1]}" if ':' in r else f"- {r}" for r in m["rules"]) + "\n")
    L.append("## 10. Permissions & RBAC\n| Permission | Roles |\n|---|---|\n" +
             "\n".join(f"| `{p[0]}` | {p[1]} |" for p in m["permissions"]) + "\n")
    L.append("## 11. Validations\n" + "\n".join(f"- {v}" for v in m["validations"]) + "\n")
    L.append("## 12. Error Scenarios\n" + "\n".join(f"- {e}" for e in m["errors"]) + "\n")
    L.append("## 13. Internal Integrations\n" + ", ".join(m["integrations_internal"]) + "\n")
    L.append("## 14. Testing Requirements\n" + "\n".join(f"- {t}" for t in m["testing"]) + "\n")
    L.append("## 15. Acceptance Criteria\n" + "\n".join(f"- [ ] {a}" for a in m["acceptance"]) + "\n")
    L.append("## 16. Edge Cases\n" + "\n".join(f"- {e}" for e in m["edge"]) + "\n")
    L.append("## 17. Implementation Checklist\n" + "\n".join(f"- [ ] {c}" for c in m["checklist"]) + "\n")
    L.append("## 18. Future Enhancements\n- Deeper AI autonomy for this module as trust tier rises.\n- Additional provider/channel adapters.\n- Arabic-first UX refinements.\n")
    return "\n".join(L)

# group modules by folder
from collections import defaultdict
byfolder = defaultdict(list)
for m in MODS:
    byfolder[m["folder"]].append(m)

# ---------- folder scaffolding ----------
for folder, desc in REPO_FOLDERS:
    mods_here = byfolder.get(folder, [])
    readme = [f"# {folder}\n", desc + "\n"]
    if mods_here:
        readme.append("## Modules in this domain\n")
        for m in mods_here:
            readme.append(f"- **{m['num']} {m['name']}** → [`{modfile(m)}`](./{modfile(m)})")
        readme.append("")
    readme.append("## Standard document set for this domain\nEach module spec in this folder covers, as numbered sections:\n")
    readme += [f"{i+1}. {d}" for i,d in enumerate(FOLDER_DOCSET)]
    readme.append("")
    w(os.path.join(folder, "README.md"), "\n".join(readme))
    for m in mods_here:
        w(os.path.join(folder, modfile(m)), module_md(m))

# ---------- 00_MASTER docs ----------
def master_readme():
    L = [f"# {TITLE}\n", f"_{SUBTITLE}_\n", f"**Compiled:** {DATE}\n", "## Vision — Zero Human Intervention\n", VISION, "\n",
         "## The pipeline (owned end-to-end)\n```\nSignal Engine\n  -> ABM Intelligence Layer\n  -> ABM CRM Engine (HubSpot replica)\n  -> ABM Marketing Engine (Mailchimp replica)\n  -> ABM Outreach Engine (Email + LinkedIn)\n  -> ABM Analytics Engine\n  (Rules + Workflow + AI orchestrate; Copilot = the human's window)\n```\n",
         "## The 26 modules\n| # | Module | Domain folder | Replaces |\n|---|---|---|---|"]
    for m in MODS:
        L.append(f"| {m['num']} | {m['name']} | `{m['folder']}` | {m['replaces'].split(' — ')[0][:60]} |")
    L.append("\n## Repository structure\n")
    for f,d in REPO_FOLDERS:
        L.append(f"- **`{f}/`** — {d}")
    L.append("\n## How to read this repo\nStart here (00_MASTER), then each domain folder holds its module specs. Every module `.md` follows the same 18-section template (purpose → scope → personas → entities → APIs → workflows → state machine → events → rules → RBAC → validations → errors → integrations → testing → acceptance → edge cases → checklist → future).\n")
    L.append("## Build it in 5 days\nSee `00_MASTER/05_BUILD_PLAN.md`.\n")
    return "\n".join(L)

def data_model_md():
    L = ["# Global Data Model & Shared Kernel\n","Every entity is tenant-scoped (`tenant_id`) with UUID primary keys, soft deletes, and audit history. Below is the shared kernel every module references; per-entity field schemas live in each module spec.\n",
         "## Shared/global entities\n| Entity | Description | Owning module |\n|---|---|---|"]
    for e in GLOBAL_ENTITIES:
        L.append(f"| `{e[0]}` | {e[1]} | {e[2]} |")
    L.append("\n## Conventions\n- **PKs:** UUID v4/v7.\n- **Tenancy:** `tenant_id` on every row; Postgres row-level security.\n- **Timestamps:** `created_at`, `updated_at`, plus domain timestamps (`occurred_at`, `expires_at`).\n- **Soft delete:** `deleted_at` nullable; never hard-delete production data.\n- **JSONB** for flexible/config fields (definitions, blocks, payloads).\n- **Partitioning:** `contacts`, `activities`, `events`, `email_message`, `delivery_event`, `metric_event` partitioned by tenant/time.\n- **Materialized views:** analytics rollups, account graph, forecast.\n")
    L.append("## ER overview (textual)\n```\ntenant 1—* account 1—* contact\naccount 1—* deal *—1 pipeline 1—* stage\naccount 1—* signal *—1 raw_capture\naccount 1—* committee_member *—1 contact\n(from)*—*(to) relationship  (org/person/vendor/tech graph)\ncontact 1—* activity ; deal 1—* activity\ncampaign 1—* campaign_member ; journey 1—* enrollment 1—* journey_event\nemail_campaign 1—* email_message 1—* delivery_event\naccount 1—* account_score ; contact 1—1 lead_score\nevent (bus) —> all consumers\n```\n")
    return "\n".join(L)

def events_md():
    L = ["# Event Architecture & Master Catalog\n","The async event bus (Module 24) is the platform's nervous system. **At-least-once** delivery, **per-key ordering** (e.g. per `account_id`), **idempotent** consumers (dedup by event id), a **schema registry** with additive versioning, and **retry -> DLQ -> replay**. Engines are decoupled producers/consumers.\n",
         "## Representative event catalog\n| Event | Producer | Key consumers |\n|---|---|---|"]
    for e in EVENT_CATALOG:
        L.append(f"| `{e[0]}` | {e[1]} | {e[2]} |")
    L.append("\n## Delivery guarantees\n- At-least-once; consumers idempotent via event-id dedup store.\n- Ordering guaranteed per partition key, not globally.\n- Failed deliveries retry with backoff, then dead-letter; ops can replay.\n- Schema changes are additive; consumers tolerate unknown new fields.\n")
    return "\n".join(L)

def cross_md():
    L = ["# Cross-Cutting Concerns\n","These apply to every module and are enforced platform-wide.\n"]
    for name, body in CROSS_CUTTING:
        L.append(f"## {name}\n{body}\n")
    L.append("## Microservice boundaries\n"+MICROSERVICE_BOUNDARIES+"\n")
    L.append("## Zero Human Intervention — how it's achieved\n"+ZERO_HUMAN+"\n")
    L.append("## Technology stack\n| Layer | Choice |\n|---|---|\n"+"\n".join(f"| {t[0]} | {t[1]} |" for t in TECH_STACK)+"\n")
    return "\n".join(L)

def build_plan_md():
    L = ["# 5-Day AI-Assisted Build Plan\n","Assumes Claude Code / Cursor / Codex building against these specs. Each day ends with a working, testable slice.\n"]
    for title, body in BUILD_PLAN:
        L.append(f"## {title}\n{body}\n")
    L.append("## Guardrails during the build\n- Never delete production data; always generate migrations.\n- Inspect before modifying; reuse existing ABM Engine + DRIP code.\n- Compliance gates (consent/suppression/hold/C-suite) are non-negotiable and built in from Day 1.\n- Every module ships with its acceptance suite from its spec.\n")
    return "\n".join(L)

w("README.md", master_readme())
w("00_MASTER/00_MASTER_ARCHITECTURE.md", master_readme())
w("00_MASTER/01_GLOBAL_DATA_MODEL.md", data_model_md())
w("00_MASTER/02_EVENT_ARCHITECTURE.md", events_md())
w("00_MASTER/03_CROSS_CUTTING.md", cross_md())
w("00_MASTER/04_MODULE_INDEX.md", "# Module Index\n\n"+"\n".join(f"- **{m['num']} {m['name']}** — `{m['folder']}`" for m in MODS))
w("00_MASTER/05_BUILD_PLAN.md", build_plan_md())

# folders that had no modules still get the standard docset note (already created above if in REPO_FOLDERS)
present = {f for f,_ in REPO_FOLDERS}

# count files
nfiles = sum(len(files) for _,_,files in os.walk(REPO))
print("Repo files:", nfiles)
print("Modules:", len(MODS))

# ---------- HTML BLUEPRINT ----------
def esc(x): return html.escape(str(x))
STATUS = ""  # blueprint is design doc
css = """
:root{--navy:#0b1f38;--navy2:#12324f;--teal:#0e8390;--teal2:#12a4b4;--tealL:#e4f5f7;--ink:#17222e;--sub:#54636f;--line:#d7e0e8;--bg:#eef2f5;--card:#fff;--amber:#c9770a;--green:#159a52;--gray:#6b7280;}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:var(--ink);background:var(--bg);font-size:13.5px;line-height:1.55}
.page{background:var(--card);max-width:1000px;margin:20px auto;padding:40px 50px;border:1px solid var(--line);border-radius:4px}
.page.cover{background:linear-gradient(150deg,var(--navy),var(--navy2));color:#fff;border:none}
@media print{body{background:#fff;font-size:10.5px}.page{margin:0 auto;max-width:none;border:none;border-radius:0;padding:24px 28px;page-break-after:always}}
h1{font-size:30px;margin:0 0 8px}h2{font-size:20px;color:var(--navy);border-bottom:3px solid var(--teal);padding-bottom:7px;margin:0 0 14px}
h3{font-size:15px;color:var(--navy2);margin:18px 0 6px}h4{font-size:12.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--teal);margin:14px 0 5px}
.kicker{font-size:12px;letter-spacing:.18em;text-transform:uppercase;color:var(--teal2);font-weight:700;margin-bottom:8px}
code{font-family:ui-monospace,Consolas,monospace;background:#eef1f4;padding:1px 5px;border-radius:3px;font-size:.86em;color:var(--navy2)}
table{width:100%;border-collapse:collapse;font-size:12px;margin:10px 0}th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
th{background:var(--navy);color:#fff;font-size:10.5px;text-transform:uppercase;letter-spacing:.03em}tr:nth-child(even) td{background:#f7fafb}
.callout{border-left:4px solid var(--teal);background:var(--tealL);border-radius:0 8px 8px 0;padding:11px 15px;margin:12px 0}
.flowbox{background:var(--navy);color:#eafcff;border-radius:8px;padding:14px 16px;font-family:ui-monospace,Consolas,monospace;font-size:12px;line-height:1.7;white-space:pre;overflow-x:auto;margin:12px 0}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px}.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
.box{border:1px solid var(--line);border-radius:8px;padding:11px 13px;background:#fff}.box h4{margin-top:0}
.mcard{border:1px solid var(--line);border-left:4px solid var(--teal);border-radius:8px;padding:12px 14px;margin:10px 0;background:#fff}
.mcard .mh{font-weight:700;font-size:14px;color:var(--navy)}.mcard .mr{font-size:11px;color:var(--sub);font-style:italic;margin:2px 0 6px}
.mcard .ml{font-size:11.5px}.mcard b{color:var(--navy2)}
.toc a{display:flex;justify-content:space-between;border-bottom:1px dotted var(--line);padding:5px 0;color:var(--navy2);text-decoration:none;font-size:12.5px}
.pillrow{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}.tag{font-size:10.5px;background:var(--tealL);color:#0a4750;border-radius:12px;padding:2px 9px}
.foot{font-size:10.5px;color:var(--sub);text-align:right;border-top:1px solid var(--line);margin-top:22px;padding-top:6px}
.num{color:var(--teal);font-weight:700;margin-right:8px}
"""

def module_card_html(m):
    return f"""<div class="mcard">
<div class="mh">{esc(m['num'])} · {esc(m['name'])}</div>
<div class="mr">Replaces: {esc(m['replaces'])}</div>
<div class="ml"><b>Purpose.</b> {esc(m['purpose'])}</div>
<div class="pillrow">{''.join(f'<span class="tag">{esc(k)}</span>' for k in m['scope_in'][:5])}</div>
<div class="ml"><b>Key entities:</b> {esc(', '.join(e[0] for e in m['entities']))}.</div>
<div class="ml"><b>Signature APIs:</b> {esc('; '.join(a[0]+' '+a[1] for a in m['apis'][:4]))}.</div>
<div class="ml"><b>Top rules:</b> {esc(' '.join(r.split(':',1)[0] for r in m['rules'][:4]))} — full set in the module spec.</div>
<div class="ml"><b>Publishes:</b> <code>{esc(', '.join(m['events_pub'][:4]))}</code></div>
</div>"""

pages = []
# cover
pages.append(f"""<div class="page cover">
<div class="kicker" style="color:#7fe3ef">Decimal Technologies · Enterprise Architecture · Confidential</div>
<h1>{esc(TITLE)}</h1>
<div style="font-size:17px;color:#cfe6f2;margin-bottom:20px">{esc(SUBTITLE)}</div>
<p style="max-width:660px;color:#d9e8f2">Master blueprint for a 26-module, zero-external-dependency ABM platform: HubSpot, Mailchimp, Apollo, Customer.io, Instantly, Smartlead and n8n rebuilt as native modules. Companion to the markdown spec repository <code>ABM_Enterprise_Platform/</code>.</p>
<div style="margin-top:36px;color:#9fc4d8;font-size:12px">Compiled {esc(DATE)} · {len(MODS)} modules · {len(REPO_FOLDERS)} domain folders</div>
</div>""")

# vision + flow
pages.append(f"""<div class="page">
<div class="kicker">Section 1</div><h2>Vision — Zero Human Intervention</h2>
<p>{esc(VISION)}</p>
<h3>From dependency chain to owned pipeline</h3>
<div class="grid2">
<div class="box"><h4>Before (rented)</h4><div class="flowbox" style="background:#33241a">Signal Engine
  -> Clay
  -> Apollo
  -> HubSpot
  -> Mailchimp
  -> Smartlead</div></div>
<div class="box"><h4>After (owned)</h4><div class="flowbox">Signal Engine
  -> ABM Intelligence Layer
  -> ABM CRM Engine (HubSpot replica)
  -> ABM Marketing Engine (Mailchimp replica)
  -> ABM Outreach Engine
  -> ABM Analytics Engine</div></div>
</div>
<div class="callout"><b>How zero-intervention is achieved.</b> {esc(ZERO_HUMAN)}</div>
<div class="foot">ABM Enterprise Platform · Vision</div></div>""")

# module map overview table
rows = "".join(f"<tr><td>{esc(m['num'])}</td><td>{esc(m['name'])}</td><td><code>{esc(m['folder'])}</code></td><td>{esc(m['replaces'].split(' — ')[0])}</td></tr>" for m in MODS)
pages.append(f"""<div class="page">
<div class="kicker">Section 2</div><h2>The 26 modules at a glance</h2>
<table><tr><th>#</th><th>Module</th><th>Domain folder</th><th>Replaces</th></tr>{rows}</table>
<div class="foot">ABM Enterprise Platform · Module map</div></div>""")

# repo structure + tech
frows = "".join(f"<tr><td><code>{esc(f)}/</code></td><td>{esc(d)}</td></tr>" for f,d in REPO_FOLDERS)
trows = "".join(f"<tr><td>{esc(t[0])}</td><td>{esc(t[1])}</td></tr>" for t in TECH_STACK)
pages.append(f"""<div class="page">
<div class="kicker">Section 3</div><h2>Repository structure &amp; technology stack</h2>
<h3>The 20-folder spec repository</h3>
<table><tr><th>Folder</th><th>Contents</th></tr>{frows}</table>
<h3>Standard document set per module</h3>
<p>{esc(', '.join(FOLDER_DOCSET))}.</p>
<h3>Technology stack</h3>
<table><tr><th>Layer</th><th>Choice</th></tr>{trows}</table>
<div class="foot">ABM Enterprise Platform · Repo &amp; stack</div></div>""")

# global data model + events
gerows = "".join(f"<tr><td><code>{esc(e[0])}</code></td><td>{esc(e[1])}</td><td>{esc(e[2])}</td></tr>" for e in GLOBAL_ENTITIES)
evrows = "".join(f"<tr><td><code>{esc(e[0])}</code></td><td>{esc(e[1])}</td><td>{esc(e[2])}</td></tr>" for e in EVENT_CATALOG)
pages.append(f"""<div class="page">
<div class="kicker">Section 4</div><h2>Global data model &amp; event architecture</h2>
<h3>Shared kernel entities</h3>
<table><tr><th>Entity</th><th>Description</th><th>Owner</th></tr>{gerows}</table>
<h3>Event bus catalog (representative)</h3>
<table><tr><th>Event</th><th>Producer</th><th>Consumers</th></tr>{evrows}</table>
<div class="callout">At-least-once delivery · per-key ordering · idempotent consumers · schema registry · retry → DLQ → replay. Engines stay decoupled through the bus (Module 24).</div>
<div class="foot">ABM Enterprise Platform · Data &amp; events</div></div>""")

# cross-cutting (2 pages)
half = (len(CROSS_CUTTING)+1)//2
cc1 = "".join(f"<h3>{esc(n)}</h3><p>{esc(b)}</p>" for n,b in CROSS_CUTTING[:half])
cc2 = "".join(f"<h3>{esc(n)}</h3><p>{esc(b)}</p>" for n,b in CROSS_CUTTING[half:])
pages.append(f"""<div class="page"><div class="kicker">Section 5</div><h2>Cross-cutting concerns (1/2)</h2>{cc1}<div class="foot">ABM Enterprise Platform · Cross-cutting 1</div></div>""")
pages.append(f"""<div class="page"><div class="kicker">Section 5</div><h2>Cross-cutting concerns (2/2)</h2>{cc2}
<h3>Microservice boundaries</h3><p>{esc(MICROSERVICE_BOUNDARIES)}</p>
<div class="foot">ABM Enterprise Platform · Cross-cutting 2</div></div>""")

# module deep cards — group ~3 per page
group = []
cur = []
for m in MODS:
    cur.append(m)
    if len(cur)==3:
        group.append(cur); cur=[]
if cur: group.append(cur)
for gi,gr in enumerate(group):
    cards = "".join(module_card_html(m) for m in gr)
    pages.append(f"""<div class="page"><div class="kicker">Section 6 · Module specifications ({gi+1}/{len(group)})</div>
<h2>{esc(gr[0]['num'])}–{esc(gr[-1]['num'])} · {esc(gr[0]['name'].split(' (')[0])} → {esc(gr[-1]['name'].split(' (')[0])}</h2>
{cards}
<div class="foot">ABM Enterprise Platform · Module specs · full detail in the markdown repo</div></div>""")

# build plan
bp = "".join(f"<h3>{esc(t)}</h3><p>{esc(b)}</p>" for t,b in BUILD_PLAN)
pages.append(f"""<div class="page"><div class="kicker">Section 7</div><h2>5-day AI-assisted build plan</h2>{bp}
<div class="callout"><b>Guardrails:</b> never delete production data; always migrate; inspect before modifying; compliance gates built in from Day 1; every module ships with its acceptance suite.</div>
<div class="foot">ABM Enterprise Platform · Build plan</div></div>""")

# closing
pages.append(f"""<div class="page"><div class="kicker">Reference</div><h2>How the blueprint &amp; repo fit together</h2>
<p>This blueprint is the spine. The companion repository <code>ABM_Enterprise_Platform/</code> contains {len(MODS)} module specifications across {len(REPO_FOLDERS)} domain folders, each following an 18-section template (purpose, scope, personas, entities/schema, API contracts, workflows, state machine, events, business rules, RBAC, validations, errors, integrations, testing, acceptance criteria, edge cases, implementation checklist, future).</p>
<p>An AI-assisted engineering team should build folder-by-folder following the 5-day plan, using each module's implementation checklist and acceptance criteria as the definition of done.</p>
<div class="callout">This redesign turns the ABM engine from an execution playbook that depends on HubSpot/Mailchimp/Apollo/Smartlead/n8n into a single enterprise platform that owns every layer natively — the precondition for true zero-human-intervention operation.</div>
<div class="foot">ABM Enterprise Platform · {esc(DATE)}</div></div>""")

doc = f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{esc(TITLE)} — Blueprint</title><style>{css}</style></head><body>{''.join(pages)}</body></html>"
with open(os.path.join(OUT,"ABM_Enterprise_Platform_Blueprint.html"),"w",encoding="utf-8") as f:
    f.write(doc)
print("Blueprint HTML written.")
