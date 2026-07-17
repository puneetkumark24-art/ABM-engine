# -*- coding: utf-8 -*-
"""Module content, batch 4 (modules 22-26) + Attribution (18-attr)."""

MODULES_4 = {
"22_attribution_engine": {
  "num":"22","name":"Attribution Engine",
  "folder":"12_Analytics",
  "replaces":"HubSpot attribution + Bizible-style multi-touch models.",
  "purpose":"Assigns credit for pipeline and revenue across the touches, campaigns, journeys and channels that influenced an account — multi-touch attribution models (first/last/linear/time-decay/W-shaped/custom) that turn the activity graph into ROI the Campaign and Reporting engines consume.",
  "scope_in":["Touch capture into attribution paths","Attribution models: first, last, linear, time-decay, U/W-shaped, custom","Account-based attribution (credit at account not just contact)","Campaign/channel/journey ROI rollup","Model comparison & configurable window"],
  "scope_out":["Metric storage (Analytics)","Report rendering (Reporting)","Deal amounts (CRM/Pipeline)"],
  "personas":[["Marketing lead","Chooses model, reads ROI"],["Exec","Revenue attribution"],["Analyst","Model comparison"]],
  "entities":[
    ("touch","An attributable touch.","id UUID pk; tenant_id UUID; account_id UUID; contact_id UUID; channel enum(email,linkedin,event,web,content,call); campaign_id UUID null; journey_id UUID null; occurred_at timestamptz; weight numeric(4,3) null"),
    ("attribution_path","Ordered touches to an outcome.","id UUID pk; account_id UUID; deal_id UUID; touch_ids uuid[]; outcome enum(meeting,opportunity,won); value numeric; window_days int"),
    ("attribution_result","Credit per touch/campaign under a model.","id UUID pk; path_id UUID; model enum(first,last,linear,time_decay,u_shaped,w_shaped,custom); credit jsonb; computed_at")
  ],
  "apis":[
    ("GET","/v1/attribution/campaigns/{id}","Attributed pipeline/revenue for a campaign.","200"),
    ("POST","/v1/attribution:recompute","Recompute under a chosen model/window.","202"),
    ("GET","/v1/attribution/models:compare","Compare credit across models.","200")
  ],
  "workflows":["Touches captured from events -> on outcome (meeting/opp/won) assemble attribution_path within window -> apply model(s) -> credit rolled to campaign/channel/journey -> feeds Campaign ROI & Reporting","Model change -> recompute results, keep history"],
  "states":("attribution_result",["current","recomputed"],"new model/window supersedes; history kept"),
  "events_pub":["attribution.recomputed"],
  "events_sub":["email.event.clicked","linkedin.reply.received","form.submitted","meeting.booked","deal.stage.changed"],
  "rules":[
    "ATT-001: A touch is credited to exactly one campaign per model run; multi-campaign split uses model weights (no double count).",
    "ATT-002: Attribution window configurable per tenant; touches outside window excluded.",
    "ATT-003: Account-based models can credit account-level touches to any contact's outcome at that account.",
    "ATT-004: Model choice is explicit; results always tagged with model+window."
  ],
  "permissions":[["attribution.read","Marketing, Exec, Admin"],["attribution.configure","Marketing lead, Admin"]],
  "validations":["window>0","model in enum","path touches within window"],
  "errors":["422 unknown model","404 no path for deal"],
  "integrations_internal":["Analytics","Campaign (ROI)","Reporting","CRM/Pipeline (outcomes)"],
  "testing":["No double counting across campaigns","Window exclusion","Model math (W-shaped 30/30/30/10 etc.)","Account-based credit"],
  "acceptance":["Show campaign-attributed pipeline under linear vs W-shaped","Change window and recompute"],
  "edge":["Outcome with zero prior touches -> direct/unattributed bucket","Very long sales cycle beyond window -> partial path","Touch shared by two journeys -> split by weights"],
  "checklist":["touch capture","path assembler","model library","account-based logic","ROI rollup","model comparison"]
},

"23_api_gateway": {
  "num":"23","name":"API Gateway",
  "folder":"15_API",
  "replaces":"Kong/Apigee + HubSpot public API surface.",
  "purpose":"The single, secured entry point for all external and inter-service API traffic: routing, authentication, authorization, rate limiting, quotas, versioning, request/response validation, API keys, webhooks-out and developer docs — the front door to the whole platform.",
  "scope_in":["Request routing to services","AuthN (OAuth2/JWT/API key) + AuthZ (RBAC/scopes)","Rate limiting, quotas, throttling per tenant/key","API versioning + deprecation","Request/response validation (OpenAPI)","Outbound webhooks + signing","Developer portal / API docs"],
  "scope_out":["Business logic (each engine)","Identity store (Admin/User Mgmt)","Event bus internals (Integration Layer)"],
  "personas":[["External developer","Uses the API"],["Admin","Manages keys/quotas"],["System","Inter-service calls"]],
  "entities":[
    ("api_key","An API key/credential.","id UUID pk; tenant_id UUID; name text; hashed_key text; scopes text[]; rate_limit int; quota_month int; status enum(active,revoked); created_at; last_used_at"),
    ("route","A registered API route.","id text pk; path text; method text; service text; version text; auth_required bool; scopes text[]; deprecated bool"),
    ("webhook_out","Outbound webhook subscription.","id UUID pk; tenant_id UUID; event_types text[]; url text; secret text; status enum(active,paused); failures int"),
    ("rate_bucket","Per-key rate state.","key_id UUID pk; window_start timestamptz; count int")
  ],
  "apis":[
    ("POST","/v1/admin/api-keys","Create/rotate an API key with scopes.","201"),
    ("GET","/v1/meta/openapi","OpenAPI spec (all versions).","200"),
    ("POST","/v1/admin/webhooks","Register an outbound webhook.","201"),
    ("GET","/v1/admin/usage","API usage/quota per key.","200")
  ],
  "workflows":["Request -> gateway authenticates (key/JWT) -> authorizes scopes/RBAC -> rate-limit/quota check -> validate against OpenAPI -> route to service -> response validated/logged","Outbound: platform event -> matching webhook_out -> signed POST -> retry/backoff on failure -> pause after threshold"],
  "states":("api_key",["active","revoked"],"active->revoked on rotate/compromise"),
  "events_pub":["api.key.created","api.webhook.failed","api.ratelimit.exceeded"],
  "events_sub":["* (for outbound webhooks)"],
  "rules":[
    "GW-001: All external traffic authenticated + authorized; no anonymous business endpoints.",
    "GW-002: Rate limits & monthly quotas enforced per key/tenant; 429 on exceed.",
    "GW-003: Requests validated against OpenAPI; invalid -> 422 before hitting services.",
    "GW-004: Outbound webhooks are signed; consumers verify signature; failing endpoints auto-paused.",
    "GW-005: Deprecated versions return sunset headers; removed after policy window."
  ],
  "permissions":[["apikeys.manage","Admin"],["gateway.config","Admin"],["usage.read","Admin, tenant owner"]],
  "validations":["scopes valid","url https for webhooks","version supported"],
  "errors":["401 bad key","403 scope denied","429 rate/quota","422 schema invalid"],
  "integrations_internal":["All engines (routing)","User/Permission (RBAC)","Integration Layer","Audit"],
  "testing":["AuthN/Z matrix","Rate-limit/quota enforcement","OpenAPI validation rejects bad payloads","Webhook signing + retry/pause"],
  "acceptance":["External key with limited scopes can call only permitted endpoints, throttled at limit","Outbound webhook delivers signed events with retry"],
  "edge":["Clock skew on JWT -> small leeway","Burst above limit -> 429 + Retry-After","Webhook endpoint flapping -> auto-pause + alert"],
  "checklist":["gateway (routing/auth/limits)","api key store + scopes","OpenAPI validation","outbound webhook dispatcher + signing","developer portal","usage metering"]
},

"24_integration_layer": {
  "num":"24","name":"Integration Layer & Event Bus",
  "folder":"16_UI",  # placed under integration domain; see note
  "replaces":"Internal Kafka/Redis event bus + connector framework (optional external bridges).",
  "purpose":"The nervous system: the internal event bus that lets every engine publish/subscribe asynchronously, plus a connector framework for optional external bridges (Slack, Teams, WhatsApp, calendar, model providers) — the plumbing that makes 26 modules one platform while keeping them decoupled.",
  "scope_in":["Internal event bus (publish/subscribe, durable, ordered per key)","Event schema registry + versioning","Connector framework for optional externals (Slack/Teams/WhatsApp/Calendar/LLM providers)","Retry, dead-letter, replay","Idempotency & exactly-once-ish delivery semantics"],
  "scope_out":["Business logic","External API exposure (API Gateway)","Credential UI (Admin)"],
  "personas":[["System","Every engine is a producer/consumer"],["Ops","Monitors bus health, replays DLQ"],["Admin","Manages connectors"]],
  "entities":[
    ("event","A platform event.","id UUID pk; tenant_id UUID; type text; key text; payload jsonb; schema_version int; occurred_at timestamptz; published_at timestamptz"),
    ("subscription","A consumer subscription.","id UUID pk; consumer text; event_types text[]; endpoint text; status enum(active,paused); dlq_count int"),
    ("dead_letter","Failed delivery.","id UUID pk; event_id UUID; subscription_id UUID; error text; attempts int; at timestamptz"),
    ("connector","External bridge config.","id UUID pk; tenant_id UUID; kind enum(slack,teams,whatsapp,calendar,llm,smtp,other); config jsonb; status enum(connected,error); scopes text[]")
  ],
  "apis":[
    ("POST","/v1/events:publish","Publish an event (internal).","202"),
    ("POST","/v1/subscriptions","Register a subscription.","201"),
    ("GET","/v1/events/dlq","List dead letters.","200"),
    ("POST","/v1/events/dlq/{id}:replay","Replay a dead letter.","200"),
    ("POST","/v1/connectors","Configure an external connector.","201")
  ],
  "workflows":["Producer publishes -> bus persists + fans out to subscriptions -> consumer acks; failure -> retry w/ backoff -> DLQ after N -> ops replay","Connector: outbound (Slack message) via connector adapter; inbound (calendar event) normalized to platform event"],
  "states":("event delivery",["published","delivered","retrying","dead_lettered"],"published->delivered on ack; ->retrying on failure; ->dead_lettered after N"),
  "events_pub":["bus.dlq.added","connector.status.changed"],
  "events_sub":["* (transport for all)"],
  "rules":[
    "INT-BUS-001: Events are schema-registered & versioned; consumers tolerate additive changes.",
    "INT-BUS-002: Delivery is at-least-once; consumers must be idempotent (event id dedup).",
    "INT-BUS-003: Ordering guaranteed per key (e.g. per account_id), not globally.",
    "INT-BUS-004: Failed deliveries retry with backoff then dead-letter; never silently dropped.",
    "INT-BUS-005: External connectors are optional bridges, never load-bearing for core flows."
  ],
  "permissions":[["bus.publish","system"],["bus.ops","Ops, Admin"],["connectors.manage","Admin"]],
  "validations":["event matches registered schema","subscription endpoints reachable","connector scopes valid"],
  "errors":["422 schema mismatch","503 consumer down -> retry/DLQ","409 duplicate event id (idempotent)"],
  "integrations_internal":["Every engine","Admin (connectors/credentials)","Notification (Slack/Teams/WhatsApp adapters)","AI Engine (LLM connector)"],
  "testing":["At-least-once + idempotent dedup","Per-key ordering","DLQ + replay","Schema-version tolerance","Connector failure isolation"],
  "acceptance":["Publish account.tiered and confirm all subscribers react idempotently","Kill a consumer, events DLQ and replay cleanly"],
  "edge":["Poison message -> DLQ not infinite retry","Schema v2 additive -> v1 consumers unaffected","Connector outage -> core flows continue"],
  "checklist":["event bus (Redis streams/Kafka)","schema registry","subscription manager","retry + DLQ + replay","connector framework + adapters","idempotency store"]
},

"25_admin_console": {
  "num":"25","name":"Admin Console & User/Permission Management",
  "folder":"14_Admin",
  "replaces":"HubSpot settings + super-admin + billing/quotas + RBAC.",
  "purpose":"The control plane: organizations/tenants, teams, users, roles & permissions (RBAC), API keys, domains, SMTP, integrations, branding, audit logs, usage, billing, quotas, AI credits, monitoring and health — everything an operator configures and governs, with full multi-tenancy.",
  "scope_in":["Tenant/org management (multi-tenancy)","Users, teams, roles, granular permissions (RBAC)","API keys, domains, SMTP, integrations, branding","Usage, billing, quotas, AI credits, rate limits","Audit logs (platform-wide), monitoring, health, feature flags"],
  "scope_out":["Per-engine business config lives in each engine; Admin holds cross-cutting governance","API routing (Gateway)"],
  "personas":[["Tenant Owner/Admin","Governs the workspace"],["RevOps","Manages users/teams/permissions"],["Billing admin","Quotas/credits"]],
  "entities":[
    ("tenant","An organization/workspace.","id UUID pk; name text; plan text; status enum(active,suspended); settings jsonb; created_at"),
    ("user","A user.","id UUID pk; tenant_id UUID; email citext; name text; status enum(active,invited,disabled); last_login_at"),
    ("team","A team.","id UUID pk; tenant_id UUID; name text; member_ids uuid[]"),
    ("role","A role with permissions.","id UUID pk; tenant_id UUID; name text; permissions text[]; is_system bool"),
    ("quota","Usage quota/credit.","id UUID pk; tenant_id UUID; kind enum(ai_credits,emails,api_calls,enrichment_credits,seats); limit int; used int; period text"),
    ("audit_entry","Platform audit.","id UUID pk; tenant_id UUID; actor_id UUID; area text; action text; detail jsonb; at timestamptz")
  ],
  "apis":[
    ("POST","/v1/admin/tenants","Create/configure a tenant.","201"),
    ("POST","/v1/admin/users:invite","Invite a user + role.","201"),
    ("POST","/v1/admin/roles","Create a role with permissions.","201"),
    ("GET","/v1/admin/usage","Usage/quota/credit dashboard.","200"),
    ("GET","/v1/admin/audit","Platform audit log.","200"),
    ("GET","/v1/admin/health","System health/monitoring.","200")
  ],
  "workflows":["Provision tenant -> configure branding/domains/SMTP -> invite users, assign roles/teams -> set quotas/credits -> monitor usage & health; permission changes take effect immediately across services","Quota exhaustion -> block relevant action + notify"],
  "states":("tenant",["active","suspended"],"active->suspended on billing/policy; back on resolve"),
  "events_pub":["tenant.provisioned","user.invited","role.changed","quota.exhausted"],
  "events_sub":["* (usage metering from all engines)"],
  "rules":[
    "ADM-001: Full multi-tenancy — every entity is tenant-scoped; no cross-tenant access ever.",
    "ADM-002: RBAC is deny-by-default; permissions are additive via roles.",
    "ADM-003: Quotas (AI credits, emails, enrichment, API) enforced; exhaustion blocks + alerts.",
    "ADM-004: Every privileged action is audited platform-wide.",
    "ADM-005: Row-level security ties records to owner/team; managers see team, admins see tenant."
  ],
  "permissions":[["admin.full","Admin/Owner"],["users.manage","RevOps, Admin"],["billing.manage","Billing admin, Admin"],["audit.read","Admin"]],
  "validations":["email unique per tenant","role permissions valid","quota limits>=0"],
  "errors":["402 quota exceeded","403 cross-tenant attempt","409 duplicate user"],
  "integrations_internal":["All engines (RBAC + quotas)","API Gateway (keys)","Integration Layer (connectors)","Notification"],
  "testing":["Tenant isolation (no leakage)","RBAC deny-by-default matrix","Quota enforcement + block","Audit completeness","Row-level security"],
  "acceptance":["Two tenants fully isolated","Custom role limits a user to read-only CRM","AI credit exhaustion blocks generation with clear error"],
  "edge":["User in multiple teams -> union of permissions","Suspended tenant -> read-only/blocked gracefully","Credit hits zero mid-journey -> pause + notify, no data loss"],
  "checklist":["tenant/user/team/role tables + RBAC","quota/credit metering","branding/domain/SMTP config","platform audit","health/monitoring","feature flags"]
},

"26_ai_copilot": {
  "num":"26","name":"AI Copilot",
  "folder":"10_AI_Engine",
  "replaces":"HubSpot ChatSpot / Breeze — conversational interface over the whole platform.",
  "purpose":"The natural-language interface to everything: 'Which banks should I call today?', 'How do I approach Riyad Bank?', 'Draft outreach to the Al Rajhi CDO', 'What changed on my accounts this week?' — a governed agentic copilot that queries the graph, invokes engines (with permission + compliance gates), and returns answers, briefs and actions. The realization of the zero-human-intervention vision as an assistant surface.",
  "scope_in":["Conversational NL query over graph/analytics","Action invocation (create task, enroll, generate draft, move deal) via tool-calling","Grounded answers with citations to intelligence/records","Guardrails: permission-aware, compliance-gated, confidence-qualified","Proactive suggestions (today's priorities, risks)"],
  "scope_out":["The underlying data/logic (each engine)","Model hosting (Integration Layer)","Bulk content gen (AI Personalization — Copilot calls it)"],
  "personas":[["AE","Asks who/how/what-to-say"],["Manager","Portfolio questions"],["Exec","'How's pipeline vs quota?'"]],
  "entities":[
    ("copilot_session","A conversation.","id UUID pk; tenant_id UUID; user_id UUID; started_at; context jsonb"),
    ("copilot_turn","One Q/A turn.","id UUID pk; session_id UUID; question text; plan jsonb; tools_called jsonb; answer text; citations uuid[]; confidence numeric(4,3); at timestamptz"),
    ("tool_binding","Registered tool the copilot may call.","code text pk; label text; engine text; params_schema jsonb; required_permission text; compliance_gated bool")
  ],
  "apis":[
    ("POST","/v1/copilot/ask","Ask a question / issue a command.","200 turn"),
    ("GET","/v1/copilot/sessions/{id}","Conversation history.","200"),
    ("GET","/v1/copilot/suggestions","Proactive priorities for the user.","200"),
    ("GET","/v1/copilot/tools","Available tools for this user (permission-filtered).","200")
  ],
  "workflows":["Ask -> intent+plan -> select tools (permission-filtered) -> query engines / analytics / graph -> if action: enforce permission + compliance gate + (autonomy) confirmation -> compose grounded answer w/ citations + confidence -> log turn","Proactive: daily job computes 'today's priorities' from NBA + scores"],
  "states":("copilot_turn",["planned","executed","answered","blocked"],"planned->executed on tool calls; ->answered; ->blocked if permission/compliance denies"),
  "events_pub":["copilot.action.taken","copilot.query.answered"],
  "events_sub":["intelligence.nba.created","score.threshold.crossed"],
  "rules":[
    "COP-001: Copilot can only call tools the user is permitted to (RBAC-filtered tool list).",
    "COP-002: Any action that sends/outreach passes the same consent/suppression/hold/autonomy gates — Copilot cannot bypass compliance.",
    "COP-003: Answers are grounded with citations to platform records; ungrounded claims are qualified/omitted.",
    "COP-004: Destructive/outreach actions require explicit user confirmation unless autonomy tier permits.",
    "COP-005: C-suite outreach via Copilot always requires human confirmation."
  ],
  "permissions":[["copilot.use","All (tool set filtered by role)"],["copilot.actions.write","per underlying engine permission"]],
  "validations":["tool params schema-valid","user permitted for tool","citations resolve"],
  "errors":["403 tool not permitted","409 compliance gate blocked (explained)","422 ambiguous query -> clarify"],
  "integrations_internal":["Intelligence, CRM, Scoring, Analytics, AI Personalization, Journey, Rules","Admin (RBAC)","Integration Layer (LLM)"],
  "testing":["RBAC tool filtering","Compliance gate blocks outreach via copilot","Answer grounding/citations","Confirmation on destructive actions"],
  "acceptance":["'Which banks should I call today?' returns ranked accounts with reasons + citations","'Draft outreach to Al Rajhi CDO' generates via AI Engine but flags human review (c-suite)"],
  "edge":["Ambiguous ask -> clarifying question not wrong action","User lacks permission -> explains, offers permitted alternative","LLM hallucination -> grounding check strips uncited claims"],
  "checklist":["intent/planner + tool-calling","permission-filtered tool registry","grounding + citation checker","compliance-gate enforcement","proactive suggestions job","session/turn logging"]
},
}
