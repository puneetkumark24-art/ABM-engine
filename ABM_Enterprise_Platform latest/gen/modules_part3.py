# -*- coding: utf-8 -*-
"""Module content, batch 3 (modules 15-21)."""

MODULES_3 = {
"15_rules_engine": {
  "num":"15","name":"Rules Engine",
  "folder":"13_Rules_Engine",
  "replaces":"HubSpot workflow logic + custom IFTTT — the no-code IF/THEN decision core.",
  "purpose":"The configurable no-code decision core every enterprise product revolves around: WHEN/IF (conditions over signals, scores, entities, events) THEN (actions across any engine). Non-developers compose rules like 'IF signal_score>80 AND funding>$50M AND CTO exists THEN create opportunity, assign owner, generate brief+email+LinkedIn sequence, start campaign, wait 3 days, check open...' — evaluated deterministically and auditable.",
  "scope_in":["Rule authoring (conditions + actions) no-code","Condition operators over any entity/field/event/score","Action catalog (create/assign/generate/enroll/notify/update/wait/branch)","Rule evaluation engine (event-driven + scheduled)","Rule versioning, priority, conflict resolution, dry-run/simulate","Audit of every firing"],
  "scope_out":["Long-running visual flows (Workflow Engine 16 — Rules can call Workflows)","Channel execution internals","Score math (Lead Scoring)"],
  "personas":[["Ops/RevOps","Authors rules"],["Admin","Approves/prioritizes"],["System","Evaluates & fires"]],
  "entities":[
    ("rule","A rule definition.","id UUID pk; tenant_id UUID; name text; trigger enum(event,schedule,manual); event_type text null; conditions jsonb; actions jsonb; priority int; status enum(draft,active,paused); version int; created_by; created_at"),
    ("rule_firing","An evaluation/execution record.","id UUID pk; rule_id UUID; subject_type enum; subject_id UUID; matched bool; actions_result jsonb; at timestamptz; dry_run bool"),
    ("action_def","Catalog of available actions.","code text pk; label text; params_schema jsonb; target_engine text; idempotent bool"),
    ("condition_op","Catalog of operators.","code text pk; label text; applies_to text[]")
  ],
  "apis":[
    ("POST","/v1/rules","Create a rule (conditions+actions).","201"),
    ("POST","/v1/rules/{id}:simulate","Dry-run over historical/sample data.","200"),
    ("POST","/v1/rules/{id}:activate","Activate after validation.","200"),
    ("GET","/v1/rules/{id}/firings","Firing history/audit.","200"),
    ("GET","/v1/rules/catalog","Available conditions + actions.","200")
  ],
  "workflows":["Event arrives OR schedule ticks -> match rules by trigger -> evaluate conditions (short-circuit) -> if matched, execute action list in order (some actions call Workflow Engine for waits/branches) -> record firing + audit","Simulate: run against sample without side effects, show what would fire"],
  "states":("rule",["draft","active","paused"],"draft->active on validate; active<->paused"),
  "events_pub":["rule.fired","rule.action.executed","rule.conflict.detected"],
  "events_sub":["* (subscribes to any platform event by trigger config)"],
  "rules":[
    "RUL-001: Conditions are pure/deterministic; same inputs => same match.",
    "RUL-002: Actions execute in defined order; failure policy per action (halt/continue/retry).",
    "RUL-003: Rule priority resolves conflicts; two rules acting on same field => higher priority wins, logged.",
    "RUL-004: Every firing (incl. dry-run) is audited with matched conditions snapshot.",
    "RUL-005: Actions that send/outreach still pass consent/suppression/hold/autonomy gates (rules cannot bypass compliance)."
  ],
  "permissions":[["rules.author","Ops, Admin"],["rules.activate","Admin"],["rules.read","Manager, Ops, Admin"]],
  "validations":["conditions reference valid fields/ops","actions reference valid action_def + params schema","no self-referential infinite fire (guard)"],
  "errors":["422 invalid condition/action schema","409 priority conflict unresolved","500 action failed (per failure policy)"],
  "integrations_internal":["Every engine (action targets)","Workflow Engine (delegation)","Lead Scoring, Signals, CRM (condition inputs)","Audit"],
  "testing":["Determinism","Priority conflict resolution","Compliance gate cannot be bypassed","Simulate has no side effects","Ordered action execution + failure policy"],
  "acceptance":["Author the sample 'IF score>80 AND funding>50M AND CTO exists THEN...' rule and simulate it, then activate","Conflicting rules resolve by priority with audit"],
  "edge":["Rule fires on entity later suppressed -> downstream send still blocked by gate","Circular rule (A triggers B triggers A) -> loop guard","Bulk event storm -> batched evaluation"],
  "checklist":["condition + action catalogs","evaluator (event + schedule)","simulate mode","priority/conflict resolver","firing audit","compliance-gate enforcement in actions"]
},

"16_workflow_engine": {
  "num":"16","name":"Workflow Engine (n8n-style)",
  "folder":"11_Workflow_Engine",
  "replaces":"n8n / Zapier / Make — visual node-based automation inside the platform.",
  "purpose":"A visual, node-based automation builder (like n8n but native): drag nodes — Email, LinkedIn, Webhook, CRM, Condition, Delay, Wait, Decision, Loop, Merge, Split, HTTP, Python, LLM, News/RSS, Slack, Teams, WhatsApp, SMS, Call, Meeting, Calendar, Approval, Manual Step, AI Step — wire them into durable, resumable workflows that power everything from onboarding to complex multi-branch plays.",
  "scope_in":["Visual DAG builder with 25+ node types","Durable execution (resumable across waits/restarts)","Triggers: event, schedule, webhook, manual","Data mapping between nodes; expressions","Error handling, retries, timeouts per node","Sub-workflows, loops, merges, splits, approvals","Run history, logs, replay"],
  "scope_out":["Marketing-specific journeys (Journey Engine — though it may compile to workflows)","No-code IF/THEN business rules (Rules Engine — Rules can invoke Workflows)"],
  "personas":[["Ops/Automation builder","Designs workflows"],["Admin","Governs credentials/limits"],["System","Executes runs"]],
  "entities":[
    ("workflow","A workflow definition (DAG).","id UUID pk; tenant_id UUID; name text; nodes jsonb; edges jsonb; triggers jsonb; status enum(draft,active,paused); version int; created_at"),
    ("workflow_run","An execution instance.","id UUID pk; workflow_id UUID; status enum(running,waiting,succeeded,failed,cancelled); trigger_ctx jsonb; started_at; finished_at; cursor jsonb"),
    ("node_execution","One node's execution in a run.","id UUID pk; run_id UUID; node_id text; status enum(pending,running,done,failed,skipped,waiting); input jsonb; output jsonb; attempts int; error text null; at timestamptz"),
    ("credential","Stored credential/connection for nodes.","id UUID pk; tenant_id UUID; kind text; name text; secret_ref text; scopes text[]")
  ],
  "apis":[
    ("POST","/v1/workflows","Create workflow (nodes+edges).","201"),
    ("POST","/v1/workflows/{id}:run","Trigger a run (manual/test).","202"),
    ("GET","/v1/workflows/runs/{id}","Run status + node executions.","200"),
    ("POST","/v1/workflows/runs/{id}:resume","Resume a waiting run (approval/callback).","200"),
    ("GET","/v1/workflows/{id}/history","Run history + logs.","200")
  ],
  "workflows":["Trigger -> create run -> execute nodes along DAG -> Delay/Wait/Approval suspends run (durable) -> external callback/schedule resumes -> Condition/Decision branches, Loop iterates, Merge/Split combine -> terminal success/fail; retries per node policy","Sub-workflow node invokes another workflow synchronously/async"],
  "states":("workflow_run",["running","waiting","succeeded","failed","cancelled"],"running<->waiting on durable pauses; ->succeeded/failed terminal; ->cancelled manual"),
  "events_pub":["workflow.run.started","workflow.run.finished","workflow.node.failed","workflow.approval.requested"],
  "events_sub":["rule.fired (invoke)","schedule.tick","webhook.received","approval.decided"],
  "rules":[
    "WFL-001: Execution is durable — a run survives process restart and resumes from cursor.",
    "WFL-002: Each node has retry/timeout policy; exhausted retries -> failure path or run fail.",
    "WFL-003: Credentials are referenced by secret_ref, never inlined; scoped per tenant.",
    "WFL-004: Outreach nodes (email/linkedin/etc.) still pass all compliance gates.",
    "WFL-005: Loops require max-iteration bounds; unbounded loops rejected at validate."
  ],
  "permissions":[["workflow.build","Ops, Admin"],["workflow.run","Ops, Admin, system"],["credential.manage","Admin"]],
  "validations":["DAG valid (no illegal cycles; loops bounded)","node configs schema-valid","credentials exist & scoped"],
  "errors":["422 invalid DAG","401 missing credential scope","408 node timeout -> failure policy"],
  "integrations_internal":["All engines via nodes","Rules Engine (invocation)","Integration Layer (HTTP/3rd-party nodes)","Admin (credentials)","Notification (Slack/Teams nodes)"],
  "testing":["Durability: kill worker mid-run, resume correctly","Retry/timeout policy","Approval suspend/resume","Bounded loop","Compliance gate in outreach nodes"],
  "acceptance":["Build a workflow with Delay + Approval + Condition + Email that survives a restart and completes","Failed node follows failure path"],
  "edge":["Approval never answered -> timeout -> escalation path","External HTTP node flaky -> retries then failure branch","Large fan-out (Split 1000) -> throttled batching"],
  "checklist":["DAG model + validator","durable executor + cursor persistence","25+ node implementations","retry/timeout/error policy","credential vault ref","run history/logs/replay"]
},

"17_analytics_engine": {
  "num":"17","name":"Analytics Engine",
  "folder":"12_Analytics",
  "replaces":"HubSpot Analytics + Mailchimp Reports + product analytics — metrics & funnels.",
  "purpose":"Unified analytics across accounts, campaigns, journeys, pipeline, revenue, email, LinkedIn, AI performance and workflows — an event-sourced metrics layer with funnels, cohorts, conversion, response/meeting rates and dashboards, feeding both the Reporting Engine and the Copilot.",
  "scope_in":["Event ingestion from the platform event bus into an analytics store","Metric definitions & aggregations (rollups, funnels, cohorts)","Domain analytics: account, campaign, journey, pipeline, revenue, email, LinkedIn, AI, workflow","Conversion funnels, response/meeting rates, CAC hooks","Query API + materialized dashboards"],
  "scope_out":["Attribution modeling (Attribution Engine 18-attr)","Report rendering/export (Reporting Engine 20)","Raw CRM object storage"],
  "personas":[["Manager/Exec","Reads dashboards"],["Marketer","Campaign performance"],["Analyst","Ad-hoc queries"]],
  "entities":[
    ("metric_event","Normalized analytics event.","id UUID pk; tenant_id UUID; event_type text; subject_type text; subject_id UUID; props jsonb; occurred_at timestamptz"),
    ("metric_def","A defined metric.","id text pk; tenant_id UUID; name text; formula jsonb; grain enum(day,week,month); dimensions text[]"),
    ("rollup","Precomputed aggregate.","id UUID pk; metric_id text; dims jsonb; period date; value numeric"),
    ("funnel","A funnel definition + snapshot.","id UUID pk; tenant_id UUID; name text; steps jsonb; snapshot jsonb; updated_at")
  ],
  "apis":[
    ("POST","/v1/analytics/query","Query metrics with dims/filters/grain.","200"),
    ("GET","/v1/analytics/funnels/{id}","Funnel conversion snapshot.","200"),
    ("POST","/v1/analytics/metrics","Define a metric.","201"),
    ("GET","/v1/analytics/dashboards/{key}","Prebuilt dashboard payload.","200")
  ],
  "workflows":["Event bus -> analytics ingester -> metric_event store -> scheduled + incremental rollups -> dashboards/query API; funnels recomputed on cadence","Copilot/Reporting query metrics via query API"],
  "states":("rollup",["stale","fresh"],"marked stale on new events in period; recomputed to fresh by rollup job"),
  "events_pub":["analytics.rollup.completed","analytics.anomaly.detected"],
  "events_sub":["* (all domain events)","email.event.*","deal.stage.changed","journey.step.executed"],
  "rules":[
    "ANL-001: Metrics are tenant-isolated; no cross-tenant aggregation.",
    "ANL-002: Rollups are idempotent & reproducible from metric_events (event-sourced).",
    "ANL-003: Late-arriving events re-open the affected period for recompute.",
    "ANL-004: Anomaly detection flags large deltas (e.g. bounce spike) -> notify."
  ],
  "permissions":[["analytics.read","Manager, Marketer, Exec, Admin"],["analytics.define","Analyst, Admin"]],
  "validations":["metric formula valid","grain supported","dimensions exist"],
  "errors":["422 invalid metric formula","413 query too broad -> require filters"],
  "integrations_internal":["All engines (events)","Attribution","Reporting","Copilot","Notification (anomalies)"],
  "testing":["Rollup reproducibility from events","Late event recompute","Tenant isolation","Funnel math correctness"],
  "acceptance":["Query meeting-rate by campaign by month","Bounce-spike anomaly fires alert","Dashboards load within SLA"],
  "edge":["Backfill historical events -> periods recompute","High-cardinality dimension -> sampling/limits","Timezone boundaries in day-grain rollups"],
  "checklist":["event ingester","metric_event store (columnar/partitioned)","rollup engine","funnel/cohort calc","query API","anomaly detector"]
},

"18_lead_scoring_engine": {
  "num":"18","name":"Lead & Account Scoring Engine",
  "folder":"05_Account_Management",
  "replaces":"HubSpot scoring + 6sense/MadKudu — the scoring math & Effective-Opportunity model.",
  "purpose":"The quantitative core: computes the 0-100 account score (Signal 35% / Regulatory 30% / Reachability 20% / Relationship 15%), the Effective-Opportunity equation with its modifier chain, and contact-level lead scores — recalculated daily and on material events, driving tiering, routing and prioritization.",
  "scope_in":["Account base score (4 weighted dimensions)","Effective-Opportunity = Dynamic_Score x ICS/100 x Stage x Budget x Entrenchment x Risk x Window","Contact lead scoring (fit + engagement)","Modifier lookup table (Bible Artifact 1)","Daily recompute + event-driven recompute","Score history & explainability"],
  "scope_out":["Tier assignment/holds (Account Engine consumes score)","Signal reasoning (Intelligence)","Engagement capture (Delivery/Contact)"],
  "personas":[["System","Recomputes scores"],["Manager","Reviews score drivers"],["AE","Sorts by Effective-Opportunity"]],
  "entities":[
    ("account_score","Daily account score snapshot.","id UUID pk; tenant_id UUID; account_id UUID; signal numeric; regulatory numeric; reachability numeric; relationship numeric; base_score numeric(5,2); effective_opportunity numeric; modifiers jsonb; computed_at timestamptz"),
    ("lead_score","Contact-level score.","id UUID pk; contact_id UUID; fit numeric; engagement numeric; total numeric(5,2); grade enum(A,B,C,D); computed_at"),
    ("modifier","Modifier lookup entry.","id UUID pk; kind enum(ics,stage,budget,entrenchment,risk,window); condition jsonb; multiplier numeric(4,3)"),
    ("score_event","Explainability record.","id UUID pk; account_id UUID; delta numeric; reason text; at timestamptz")
  ],
  "apis":[
    ("GET","/v1/scoring/accounts/{id}","Current score + dimension breakdown + modifiers.","200"),
    ("POST","/v1/scoring/accounts/{id}:recompute","Force recompute.","200"),
    ("GET","/v1/scoring/accounts/{id}/history","Score over time + drivers.","200"),
    ("PUT","/v1/scoring/modifiers","Update modifier table.","200"),
    ("GET","/v1/scoring/contacts/{id}","Lead score + grade.","200")
  ],
  "workflows":["Daily job recomputes all active accounts; material events (new signal, engagement, stage move) trigger targeted recompute -> base score -> apply modifier chain -> effective_opportunity -> emit score.updated -> Account Engine re-tiers","Explainability: each recompute writes score_event deltas with reasons"],
  "states":("account_score",["current","superseded"],"new snapshot supersedes previous; history retained"),
  "events_pub":["score.updated","score.threshold.crossed"],
  "events_sub":["signal.created/expired","email.event.*","deal.stage.changed","enrichment.entity.updated","relationship changes"],
  "rules":[
    "SCO-001: Base = 0.35*signal + 0.30*regulatory + 0.20*reachability + 0.15*relationship (weights configurable, must sum to 1).",
    "SCO-002: Effective-Opportunity applies the full modifier chain from the lookup table.",
    "SCO-003: Only non-expired signals contribute to the signal dimension.",
    "SCO-004: A >10-point base change forces NBA/Effective-Opportunity refresh.",
    "SCO-005: Every score change is explainable (score_event with reason)."
  ],
  "permissions":[["scoring.read","All"],["scoring.modifiers.manage","Manager, Admin"],["scoring.recompute","Manager, Admin, system"]],
  "validations":["weights sum to 1","multipliers>0","dimensions in [0,100]"],
  "errors":["422 weights!=1","404 unknown account","409 modifier condition invalid"],
  "integrations_internal":["Account Engine (tiering)","Intelligence (NBA)","Signals/Contact/CRM (inputs)","Analytics"],
  "testing":["Weight-sum guard","Expired signals excluded","Modifier chain correctness vs Bible table","Explainability completeness","Threshold-cross event"],
  "acceptance":["Recompute yields the same number as the Bible worked example for a fixture account","Score change re-tiers account & logs reasons"],
  "edge":["All signals expired -> signal dim=0, score reflects other dims","New account no data -> baseline low score, not error","Weight reconfig -> full recompute"],
  "checklist":["dimension calculators","modifier lookup table + loader","effective-opportunity computer","daily + event recompute jobs","score history + explainability"]
},

"19_pipeline_engine": {
  "num":"19","name":"Pipeline Management Engine",
  "folder":"05_Account_Management",
  "replaces":"HubSpot deal pipelines + forecasting.",
  "purpose":"Deal pipeline configuration and progression: multiple pipelines, custom stages with entry/exit criteria and probabilities, weighted forecasting, gap-to-quota and pipeline-health analytics — the revenue spine the CRM deals move along.",
  "scope_in":["Pipeline & stage config (per product/segment)","Stage entry/exit criteria & default probabilities","Weighted forecast (commit/likely/worst)","Pipeline health: stalled deals, single-threaded, hygiene","Quota & gap analysis"],
  "scope_out":["Deal object CRUD (CRM Engine holds deals; Pipeline defines structure)","Score math (Lead Scoring)","Reporting UI (Reporting Engine)"],
  "personas":[["Manager","Configures pipelines, forecasts"],["AE","Moves deals"],["Exec","Reviews forecast"]],
  "entities":[
    ("pipeline","A pipeline.","id UUID pk; tenant_id UUID; name text; product_id UUID null; stages jsonb; default bool; created_at"),
    ("stage","A stage.","id UUID pk; pipeline_id UUID; name text; order int; probability numeric(4,3); entry_criteria jsonb; exit_criteria jsonb; rotting_days int"),
    ("forecast","A forecast snapshot.","id UUID pk; tenant_id UUID; period text; commit numeric; likely numeric; worst numeric; weighted numeric; quota numeric; gap numeric; computed_at"),
    ("pipeline_health","Health flags per deal.","deal_id UUID; flags text[]; stalled_days int; single_threaded bool; updated_at")
  ],
  "apis":[
    ("POST","/v1/pipelines","Create pipeline + stages.","201"),
    ("GET","/v1/pipelines/{id}/forecast","Weighted forecast + gap.","200"),
    ("GET","/v1/pipelines/{id}/health","Stalled/single-threaded/hygiene flags.","200"),
    ("PATCH","/v1/pipelines/{id}/stages","Edit stages/criteria/probabilities.","200")
  ],
  "workflows":["Configure pipeline+stages -> CRM deals reference stage -> stage move validated vs entry/exit criteria -> probability & forecast recompute -> health scan flags stalled/single-threaded -> notify","Forecast recompute nightly + on stage moves"],
  "states":("deal (via pipeline)",["stage 1..n","won","lost"],"transitions constrained by entry/exit criteria; rotting_days triggers stalled flag"),
  "events_pub":["forecast.updated","pipeline.deal.stalled","pipeline.health.flagged"],
  "events_sub":["deal.stage.changed","deal.created","activity.logged (single-thread check)"],
  "rules":[
    "PIP-001: Stage moves must satisfy entry criteria; exits require exit criteria or reason.",
    "PIP-002: Weighted forecast = sum(amount*stage_probability) for open deals.",
    "PIP-003: Deal idle > stage.rotting_days => stalled flag + NBA.",
    "PIP-004: Single-threaded deal (one contact) => risk flag.",
    "PIP-005: Close-date in past on open deal => hygiene flag."
  ],
  "permissions":[["pipeline.manage","Manager, Admin"],["pipeline.read","All"],["forecast.read","Manager, Exec, Admin"]],
  "validations":["stage order unique","probabilities in [0,1]","criteria schema valid"],
  "errors":["409 illegal stage transition","422 invalid criteria","404 pipeline"],
  "integrations_internal":["CRM (deals)","Lead Scoring","Intelligence (NBA on stalled)","Analytics/Reporting","Notification"],
  "testing":["Entry/exit criteria enforcement","Weighted forecast math","Stalled detection","Single-thread flag","Hygiene flags"],
  "acceptance":["Configure a product pipeline; forecast reflects weighted open deals; stalled deals flagged with NBA","Illegal stage move blocked"],
  "edge":["Deal on custom pipeline product mismatch -> validation","Backdated close date -> hygiene flag not silent","Multi-currency deals -> normalized in forecast"],
  "checklist":["pipeline + stage config","transition validator","forecast computer","health scanner","quota/gap calc"]
},

"20_reporting_engine": {
  "num":"20","name":"Reporting Engine",
  "folder":"12_Analytics",
  "replaces":"HubSpot reports/dashboards + exports + scheduled digests.",
  "purpose":"Turns analytics into consumable, shareable output: custom report builder, prebuilt dashboards, scheduled email digests, exports (PDF/CSV/XLSX), and the executive-brief generator (one-click pre-meeting PDF) — the presentation layer over the Analytics Engine.",
  "scope_in":["Report builder (pick metrics/dims/viz)","Dashboard composition (11 role-based dashboards)","Scheduled digests (daily/weekly)","Exports: PDF/CSV/XLSX","Executive Brief generator (account one-pager PDF)","Sharing & permissions on reports"],
  "scope_out":["Metric computation (Analytics)","Attribution math (Attribution)","Data storage"],
  "personas":[["Exec","Views dashboards/briefs"],["Manager","Builds & schedules reports"],["AE","One-click account brief before a meeting"]],
  "entities":[
    ("report","A saved report.","id UUID pk; tenant_id UUID; name text; definition jsonb; viz enum(table,line,bar,funnel,kpi); owner_id UUID; shared_with jsonb"),
    ("dashboard","A composed dashboard.","id UUID pk; tenant_id UUID; key text; name text; widgets jsonb; role_scope text[]"),
    ("schedule","A scheduled delivery.","id UUID pk; report_id UUID null; dashboard_id UUID null; cron text; recipients text[]; format enum(pdf,csv,xlsx,html); enabled bool"),
    ("brief","Generated executive brief.","id UUID pk; account_id UUID; pdf_url text; generated_at; sections jsonb")
  ],
  "apis":[
    ("POST","/v1/reports","Create a report.","201"),
    ("GET","/v1/reports/{id}/render","Render report data/viz.","200"),
    ("POST","/v1/reports/{id}:export","Export PDF/CSV/XLSX.","200"),
    ("POST","/v1/reports/schedules","Schedule a digest.","201"),
    ("POST","/v1/briefs:generate","One-click account exec brief PDF.","200")
  ],
  "workflows":["Build report over analytics metrics -> render/visualize -> optionally schedule digest -> exporter renders PDF/CSV/XLSX -> deliver via Email engine","Exec brief: gather account intelligence+committee+signals+pipeline+risks -> render PDF -> store as brief + asset"],
  "states":("schedule",["enabled","disabled"],"toggled; runs on cron"),
  "events_pub":["report.exported","digest.sent","brief.generated"],
  "events_sub":["analytics.rollup.completed","schedule.tick"],
  "rules":[
    "REP-001: Reports respect row-level permissions of the requesting user (no data leakage via reports).",
    "REP-002: Scheduled digests deliver via the platform Email engine (consistent deliverability).",
    "REP-003: Exec brief pulls only current, non-decayed intelligence.",
    "REP-004: Exports are tenant-scoped & access-logged."
  ],
  "permissions":[["reports.build","Manager, Analyst, Admin"],["reports.read","per share + role"],["briefs.generate","AE, Manager, Admin"]],
  "validations":["report references valid metrics","cron valid","recipients authorized"],
  "errors":["403 unauthorized share","422 invalid report def","413 export too large -> async"],
  "integrations_internal":["Analytics (data)","Attribution","Email Delivery (digests)","Asset Library (brief storage)","Admin (permissions)"],
  "testing":["Row-level permission in reports","Export fidelity PDF/CSV/XLSX","Scheduled digest delivery","Brief content freshness"],
  "acceptance":["Build & schedule a weekly pipeline digest emailed as PDF","Generate an exec brief PDF for an account in one click"],
  "edge":["Huge export -> async job + link","Recipient lacks access to underlying data -> redacted/blocked","Brief for account with sparse data -> graceful sections"],
  "checklist":["report builder + renderer","dashboard composer (11 prebuilt)","exporters (pdf/csv/xlsx)","scheduler","exec-brief generator","share permissions"]
},

"21_notification_engine": {
  "num":"21","name":"Notification Engine",
  "folder":"14_Admin",
  "replaces":"HubSpot notifications + Slack/Teams alerts.",
  "purpose":"Central multi-channel notification and alerting: in-app, email, Slack, Teams, WhatsApp — delivering NBAs, replies, hot-account alerts, approvals, anomalies and digests to the right person with preferences, batching and escalation.",
  "scope_in":["Notification templates + channels (in-app/email/Slack/Teams/WhatsApp)","User notification preferences & quiet hours","Real-time alerts (reply, hot account, approval needed, anomaly)","Batching/digest + escalation policies","Delivery tracking of notifications"],
  "scope_out":["Marketing sends (Marketing/Delivery)","The events themselves (produced by other engines)"],
  "personas":[["AE","Gets reply/hot-account alerts"],["Manager","Approvals/escalations"],["Admin","Configures channels/policies"]],
  "entities":[
    ("notification","A notification instance.","id UUID pk; tenant_id UUID; user_id UUID; kind text; channel enum(in_app,email,slack,teams,whatsapp); payload jsonb; status enum(pending,sent,read,failed); priority enum(low,med,high,urgent); created_at; read_at"),
    ("notify_pref","Per-user preferences.","user_id UUID pk; channels jsonb; quiet_hours jsonb; digest enum(off,daily,weekly)"),
    ("escalation","Escalation policy.","id UUID pk; tenant_id UUID; kind text; steps jsonb; timeout_min int")
  ],
  "apis":[
    ("POST","/v1/notifications:send","Emit a notification (internal).","202"),
    ("GET","/v1/notifications","User inbox (in-app).","200"),
    ("POST","/v1/notifications/{id}:read","Mark read.","200"),
    ("PUT","/v1/notifications/preferences","Set channels/quiet hours/digest.","200")
  ],
  "workflows":["Event -> notification rule maps to users+channels -> respect prefs/quiet hours -> deliver (channel adapter) -> track read -> unacknowledged high-priority escalates per policy","Digest batches low-priority into daily/weekly"],
  "states":("notification",["pending","sent","read","failed"],"pending->sent on deliver; ->read on ack; ->failed on channel error (retry/next channel)"),
  "events_pub":["notification.sent","notification.escalated"],
  "events_sub":["email.reply.received","account.tiered (hot)","workflow.approval.requested","analytics.anomaly.detected","intelligence.nba.created"],
  "rules":[
    "NOT-001: Respect user quiet hours + KSA calendar for non-urgent notifications.",
    "NOT-002: Urgent (reply on live deal) bypasses digest & quiet hours.",
    "NOT-003: Unacknowledged high-priority escalates after timeout.",
    "NOT-004: Notification delivery uses platform Email engine for email channel."
  ],
  "permissions":[["notifications.read.own","All"],["notify.policy.manage","Admin"]],
  "validations":["channel enabled for tenant","recipient exists","priority valid"],
  "errors":["422 channel not configured","429 rate-limited per user","failover to next channel on failure"],
  "integrations_internal":["All engines (sources)","Email Delivery","Integration Layer (Slack/Teams/WhatsApp)","Admin (channel config)"],
  "testing":["Quiet-hours honored except urgent","Escalation on timeout","Channel failover","Digest batching"],
  "acceptance":["Reply on a hot deal alerts AE instantly across in-app+Slack","Low-priority items batch into daily digest"],
  "edge":["User offline all channels -> escalate to manager","Slack workspace disconnected -> failover email","Notification storm -> per-user rate limit + batch"],
  "checklist":["notification + prefs + escalation tables","channel adapters (in-app/email/slack/teams/whatsapp)","preference + quiet-hours logic","escalation engine","digest batcher"]
},
}
