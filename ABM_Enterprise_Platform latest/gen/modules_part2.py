# -*- coding: utf-8 -*-
"""Module content, batch 2 (modules 08-14)."""

MODULES_2 = {
"08_journey_engine": {
  "num":"08","name":"Journey Builder Engine",
  "folder":"07_Marketing_Automation",
  "replaces":"HubSpot Workflows + Customer.io journeys — visual multi-step, multi-channel orchestration.",
  "purpose":"Visual, multi-channel journey orchestration: an account/contact enters a journey and moves through steps, conditions, triggers, actions, delays, goals and exit conditions across email, LinkedIn, WhatsApp, tasks and webhooks — the drip/sequence brain that replaces Smartlead/Instantly sequencing natively, with pause-on-reply and the account-centric rule enforced.",
  "scope_in":["Journey canvas: steps, branches, delays, waits","Enrollment (from segment/list/trigger/rule)","Conditions & decision splits","Multi-channel actions (email/LinkedIn/WhatsApp/task/webhook/AI)","Goals & exit conditions","Pause-on-reply, account-centric pause","Per-journey analytics"],
  "scope_out":["Single blast campaigns (Marketing Engine)","Channel delivery internals (Delivery/LinkedIn engines)","Arbitrary internal automations (Workflow Engine 16)"],
  "personas":[["Marketer","Designs nurture journeys"],["AE","Enrolls target accounts"],["System","Advances enrollments on schedule/events"]],
  "entities":[
    ("journey","A journey definition.","id UUID pk; tenant_id UUID; name text; status enum(draft,active,paused,archived); entry enum(segment,trigger,manual,rule); definition jsonb; goal jsonb; exit jsonb; version int; created_at"),
    ("journey_step","A node in the journey.","id UUID pk; journey_id UUID; type enum(email,linkedin,whatsapp,task,delay,wait,condition,split,goal,webhook,ai,manual); config jsonb; position jsonb; next_ids uuid[]"),
    ("enrollment","A contact/account moving through a journey.","id UUID pk; journey_id UUID; contact_id UUID; account_id UUID; current_step_id UUID; status enum(active,waiting,completed,exited,paused); enrolled_at; next_run_at timestamptz; context jsonb"),
    ("journey_event","Step execution record.","id UUID pk; enrollment_id UUID; step_id UUID; result enum(done,skipped,failed,branched); at timestamptz; detail jsonb")
  ],
  "apis":[
    ("POST","/v1/journeys","Create journey (canvas definition).","201"),
    ("POST","/v1/journeys/{id}:activate","Validate + activate.","200"),
    ("POST","/v1/journeys/{id}:enroll","Enroll contacts/accounts (or by segment).","202"),
    ("GET","/v1/journeys/{id}/analytics","Funnel by step, conversion, goal rate.","200"),
    ("POST","/v1/enrollments/{id}:pause","Pause an enrollment.","200"),
    ("GET","/v1/enrollments","Query enrollments by status/step.","200")
  ],
  "workflows":["Enroll (consent+suppression+hold checks) -> scheduler advances enrollment at next_run_at -> step executes via channel engine -> branch on condition/event -> goal met => exit(success); reply => account-centric pause; exit condition => exit","Worker loop: due enrollments -> execute step -> compute next_run_at (delay + timezone/KSA calendar)"],
  "states":("enrollment",["active","waiting","paused","completed","exited"],"active<->waiting on delays; ->paused on hold/reply; ->completed on goal; ->exited on exit condition/suppression"),
  "events_pub":["journey.enrolled","journey.step.executed","journey.goal.met","journey.exited","journey.step.email","journey.step.linkedin"],
  "events_sub":["email.reply.received","account.held","contact.consent.changed","segment.member.added"],
  "rules":[
    "JRN-001: Enrollment blocked if do_not_contact / suppressed / account on hold — checked at enroll AND at each step.",
    "JRN-002: Any positive reply pauses the enrollment and triggers account-centric pause (all enrollments for the account).",
    "JRN-003: Max touches per contact per journey respects global cap (default 4 email).",
    "JRN-004: Step timing obeys timezone + KSA calendar (no Fri/Sat/Ramadan sends).",
    "JRN-005: A contact cannot be active in two journeys that target the same channel simultaneously (collision guard)."
  ],
  "permissions":[["journey.manage","Marketer, Admin"],["journey.enroll","AE, Marketer"],["enrollment.pause","AE, Marketer, Admin"]],
  "validations":["journey graph acyclic except explicit loops with max-iter","every path reaches goal/exit","channel steps reference valid templates/sequences"],
  "errors":["422 unreachable step / no exit","409 channel collision","423 enrollment blocked by hold"],
  "integrations_internal":["Marketing Engine (email send)","LinkedIn Engine (12)","Email Delivery (11)","Contact/Account Engines (gates)","Analytics","Rules Engine (triggers)"],
  "testing":["Pause-on-reply halts within one cycle","Account-centric cascade","KSA calendar delay math","Collision guard across journeys","Goal detection ends enrollment"],
  "acceptance":["Design a 4-touch journey with a reply exit and run it end-to-end in a sandbox","Reply pauses all account enrollments","Timezone-correct step firing"],
  "edge":["Contact enrolled then unsubscribes -> exit immediately","Journey edited while enrollments live -> versioning, existing keep old version","Loop step with max-iter guard prevents infinite drip"],
  "checklist":["journey + step + enrollment + event tables","canvas validator (graph)","scheduler/worker advancing enrollments","channel dispatch adapters","pause/cascade logic","per-step analytics"]
},

"09_campaign_engine": {
  "num":"09","name":"Campaign Builder Engine",
  "folder":"07_Marketing_Automation",
  "replaces":"HubSpot Campaigns + orchestration wrapper over ABM plays.",
  "purpose":"The strategic wrapper that groups journeys, email campaigns, LinkedIn sequences, landing pages, assets and target account lists into a single named ABM campaign with objectives, budget, timeline, membership and unified ROI — the object leadership plans and reports against.",
  "scope_in":["Campaign object: objective, audience (account list), budget, timeline, owner","Membership: journeys, email campaigns, sequences, assets, landing pages under one campaign","Unified campaign analytics & ROI/pipeline attribution rollup","Campaign templates (reusable ABM plays)"],
  "scope_out":["Step execution (Journey/Marketing)","Attribution math (Attribution Engine 18-attr)","Asset storage (Asset Library 14)"],
  "personas":[["Marketing lead","Plans & reports campaigns"],["AE","Sees campaign context on accounts"],["Exec","Reviews campaign ROI"]],
  "entities":[
    ("campaign","ABM campaign.","id UUID pk; tenant_id UUID; name text; objective enum(awareness,demand,pipeline,expansion); status enum(planned,active,completed,archived); audience_account_list_id UUID; budget numeric; start_date date; end_date date; owner_id UUID; kpis jsonb"),
    ("campaign_member","Asset/journey/campaign linked under a campaign.","id UUID pk; campaign_id UUID; member_type enum(journey,email_campaign,sequence,landing_page,asset,form); member_id UUID"),
    ("campaign_metric","Rolled-up metric snapshot.","campaign_id UUID; date date; sends int; opens int; clicks int; replies int; meetings int; opportunities int; pipeline_value numeric; spend numeric")
  ],
  "apis":[
    ("POST","/v1/campaigns","Create campaign (objective/budget/timeline).","201"),
    ("POST","/v1/campaigns/{id}/members","Attach a journey/campaign/asset.","201"),
    ("GET","/v1/campaigns/{id}/roi","Unified ROI/pipeline rollup.","200"),
    ("POST","/v1/campaigns:from-template","Instantiate a reusable ABM play.","201"),
    ("GET","/v1/campaigns","List/filter campaigns.","200")
  ],
  "workflows":["Plan campaign -> attach journeys/emails/assets/landing pages -> activate -> members execute -> metrics roll up nightly -> ROI vs budget & pipeline","Template play: pick play -> instantiate journeys+assets pre-wired -> assign account list"],
  "states":("campaign",["planned","active","completed","archived"],"planned->active on start; ->completed at end_date/goal; ->archived manual"),
  "events_pub":["campaign.activated","campaign.completed"],
  "events_sub":["journey.goal.met","deal.stage.changed","email.event.*","meeting.booked"],
  "rules":[
    "CMP-001: A campaign's ROI aggregates only members linked to it (no double count across campaigns via attribution weighting).",
    "CMP-002: Deactivating a campaign pauses its member journeys.",
    "CMP-003: Budget overrun flags the campaign and notifies owner.",
    "CMP-004: Account can be in multiple campaigns; attribution splits credit (see Attribution Engine)."
  ],
  "permissions":[["campaign.manage","Marketing lead, Admin"],["campaign.read","All"]],
  "validations":["end_date>start_date","audience list exists","budget>=0"],
  "errors":["422 invalid timeline","404 member not found","409 member already linked"],
  "integrations_internal":["Journey/Marketing/LinkedIn/Landing/Asset engines","Attribution","Analytics/Reporting","Pipeline"],
  "testing":["ROI rollup correctness","Deactivate pauses members","Template instantiation wiring","Multi-campaign attribution split"],
  "acceptance":["Build an ABM play grouping 2 journeys + landing page + asset list, activate, and see unified ROI","Budget overrun alerts"],
  "edge":["Member journey shared by two campaigns -> attribution weighted, not doubled","Campaign ends with live enrollments -> graceful drain or forced exit per setting"],
  "checklist":["campaign + member + metric tables","rollup job","template instantiation","budget monitor","ROI view"]
},

"10_ai_personalization_engine": {
  "num":"10","name":"AI Personalization Engine",
  "folder":"10_AI_Engine",
  "replaces":"Jasper/Copy.ai/Clay AI columns + custom prompt stacks — content generation & personalization.",
  "purpose":"The content-generation brain: turns intelligence (brief, persona, pain, signals) into channel-ready, on-brand, compliant copy — emails, subjects, LinkedIn messages, landing-page copy, proposals, case studies, meeting prep — via a governed prompt/orchestration layer with the 7-agent chain, QC guardrails, and PII anonymization.",
  "scope_in":["7-agent chain: Signal Analyst->Account Research->Persona Psychology->Pain Inference->Strategy->Message Gen->QC","Generators: email, subject, LinkedIn, landing page, proposal, case study, meeting prep, call summary","Prompt Builder & template library","Brand voice + teaser-discipline QC guardrails","PII anonymization (no real names/emails to LLM)","Predictive: intent, buying-stage, deal-probability, risk (scored assists)"],
  "scope_out":["Delivery (channel engines)","Storing final CRM records","Model hosting (Integration/Admin config)"],
  "personas":[["AE","Requests a draft for a contact"],["Marketer","Bulk-generates campaign variants"],["System","Auto-drafts inside journeys"]],
  "entities":[
    ("generation","One AI generation request+result.","id UUID pk; tenant_id UUID; kind enum(email,subject,linkedin,landing,proposal,case_study,meeting_prep,call_summary,brief); subject_type enum; subject_id UUID; prompt_id UUID; input_context jsonb; output text; qc jsonb; confidence numeric(4,3); status enum(draft,qc_passed,qc_failed,approved,rejected); model text; created_at"),
    ("prompt","Versioned prompt template.","id UUID pk; tenant_id UUID; kind enum; name text; template text; variables text[]; guardrails jsonb; version int; active bool"),
    ("brand_voice","Tenant brand/voice + rules.","id UUID pk; tenant_id UUID; tone text; do_rules text[]; dont_rules text[]; teaser_rules jsonb; glossary jsonb"),
    ("prediction","A predictive score for an entity.","id UUID pk; entity_type enum; entity_id UUID; kind enum(intent,buying_stage,deal_probability,risk); value jsonb; confidence numeric(4,3); created_at")
  ],
  "apis":[
    ("POST","/v1/ai/generate","Generate content of a kind for a subject with context.","200 Generation"),
    ("POST","/v1/ai/generate:bulk","Bulk variant generation.","202 job"),
    ("POST","/v1/ai/qc","Run QC guardrails on a draft.","200"),
    ("POST","/v1/ai/prompts","Create/version a prompt.","201"),
    ("POST","/v1/ai/predict","Compute a prediction (intent/stage/probability/risk).","200"),
    ("PUT","/v1/ai/brand-voice","Set brand voice & guardrails.","200")
  ],
  "workflows":["Request -> assemble context (intelligence brief + persona + signals) -> anonymize PII -> run agent chain -> QC guardrails (teaser discipline, brand, compliance) -> qc_passed => surface for human/auto approval; qc_failed => regenerate or flag","Predictions computed on demand + on key events, cached with confidence"],
  "states":("generation",["draft","qc_passed","qc_failed","approved","rejected"],"draft->qc_passed/qc_failed by QC; qc_passed->approved by human/autonomy; ->rejected"),
  "events_pub":["ai.generation.created","ai.generation.qc_failed","ai.prediction.updated"],
  "events_sub":["intelligence.record.created","journey.step.ai","deal.created (proposal prep)"],
  "rules":[
    "AIP-001: No real PII is sent to an external model — placeholders substituted, personalized locally.",
    "AIP-002: QC must pass before any generation is eligible for send (teaser discipline, brand, no leaked facts).",
    "AIP-003: C-suite content always requires human approval regardless of QC/autonomy.",
    "AIP-004: Every generation stores its prompt version + input context for reproducibility/audit.",
    "AIP-005: Predictions always carry confidence; never surfaced as certainties."
  ],
  "permissions":[["ai.generate","AE, Marketer, system"],["ai.prompt.manage","Ops, Admin"],["ai.brandvoice.manage","Marketing lead, Admin"]],
  "validations":["prompt variables satisfied by context","output non-empty","confidence in [0,1]"],
  "errors":["422 missing context vars","409 QC failed (returns reasons)","503 model unavailable -> fallback model/queue"],
  "integrations_internal":["Intelligence Engine (context)","Journey/Marketing (consumers)","CRM (writes drafts/notes)","Integration Layer (model providers)","Admin (AI credits)"],
  "testing":["PII never leaves in prompt (assert anonymization)","QC catches leaked facts (BFSI teaser case)","Prompt versioning reproducibility","Predictive calibration on labeled set"],
  "acceptance":["Generate a persona-tailored email that passes QC and cites the triggering signal","c-suite draft forced to human review","Bulk variants for A/B produced"],
  "edge":["Sparse context (no signals) -> generic-but-safe fallback, flagged low confidence","Model returns unsafe/off-brand -> QC fail + regenerate","Arabic output requested -> localized generation + RTL note"],
  "checklist":["agent chain orchestrator","QC guardrail service","prompt registry + versioning","anonymizer","predictor set","brand voice store","model adapter via Integration Layer"]
},

"11_email_delivery_engine": {
  "num":"11","name":"Email Delivery Engine",
  "folder":"08_Email_Engine",
  "replaces":"Mandrill/SendGrid MTA + Postfix — the actual send + event pipeline.",
  "purpose":"The low-level send-and-track layer: accept a rendered message, deliver it via MTA/provider with IP-pool + reputation management, and capture the full event pipeline (delivered/open/click/bounce/complaint) that everything upstream depends on — the native replacement for Mailchimp's real moat.",
  "scope_in":["Send API (single + batch) with queueing & rate control","Provider/MTA adapters (SMTP, Mandrill-style API) + failover","Open pixel, click redirect, bounce/complaint webhooks","Feedback-loop registration, suppression sync","IP pool & warmup enforcement, throttling","Event normalization -> platform event bus"],
  "scope_out":["Audience/template/compose (Marketing Engine)","Journey logic (Journey Engine)","Deliverability domain config UI (Marketing/Admin)"],
  "personas":[["System","Primary caller"],["Deliverability admin","Monitors reputation/queues"]],
  "entities":[
    ("send_request","A queued send.","id UUID pk; tenant_id UUID; message_id UUID; to_email citext; from_domain_id UUID; ip_pool text; rendered_html text; headers jsonb; status enum(queued,sending,sent,failed,throttled); attempts int; scheduled_at; sent_at"),
    ("delivery_event","Normalized event.","id UUID pk; message_id UUID; type enum(delivered,open,click,bounce,complaint,deferral,unsub); meta jsonb; occurred_at timestamptz; provider text"),
    ("ip_pool","Sending IP pool.","id UUID pk; tenant_id UUID; name text; ips text[]; warmup_stage int; daily_cap int; reputation numeric(4,3)"),
    ("provider_route","MTA/provider config + failover order.","id UUID pk; tenant_id UUID; name text; kind enum(smtp,api); priority int; config jsonb; healthy bool")
  ],
  "apis":[
    ("POST","/v1/delivery/send","Enqueue a rendered message.","202"),
    ("POST","/v1/delivery/send:batch","Batch enqueue.","202"),
    ("POST","/v1/delivery/webhooks/{provider}","Ingest provider events (public HTTPS).","200"),
    ("GET","/v1/delivery/messages/{id}/events","Event trail for a message.","200"),
    ("GET","/v1/delivery/health","Queue depth, provider health, reputation.","200")
  ],
  "workflows":["send enqueued -> throttle/warmup check -> MTA send via highest-priority healthy route (failover) -> provider webhooks -> normalize to delivery_event -> emit email.event.* -> update message + suppression + engagement","Bounce/complaint -> suppression + negative engagement + reputation adjust"],
  "states":("send_request",["queued","throttled","sending","sent","failed"],"queued->throttled on cap; ->sending on slot; ->sent on accept; ->failed after retries/failover exhausted"),
  "events_pub":["email.event.delivered","email.event.opened","email.event.clicked","email.event.bounced","email.event.complained","email.reply.received"],
  "events_sub":["email.campaign.sent (enqueue)","journey.step.email"],
  "rules":[
    "DEL-001: Requires a public HTTPS webhook endpoint to receive provider events (deployment prerequisite).",
    "DEL-002: Warmup + daily cap per IP pool enforced; overflow queues to next window.",
    "DEL-003: Hard bounce/complaint => immediate suppression sync to Marketing Engine.",
    "DEL-004: Provider failover on 5xx/timeout to next healthy route; idempotent by message_id.",
    "DEL-005: All events normalized to one schema regardless of provider."
  ],
  "permissions":[["delivery.send","system, Marketer(indirect)"],["delivery.ops","Deliverability Admin, Admin"]],
  "validations":["from_domain authenticated","to_email valid & not suppressed","ip_pool within cap"],
  "errors":["503 no healthy route","429 throttled","409 duplicate message_id (idempotent no-op)"],
  "integrations_internal":["Marketing Engine (suppression/engagement)","Contact Engagement rollup","Lead Scoring (reachability)","Analytics","Admin (domains/IPs)"],
  "testing":["Idempotent webhook ingestion","Failover on primary down","Warmup cap enforcement","Event normalization across 2 providers","Open/click attribution to message"],
  "acceptance":["Send 10k with tracking; opens/clicks/bounces captured & normalized","Primary provider outage fails over transparently","Complaint suppresses instantly"],
  "edge":["Duplicate provider event -> dedup by (message,type,ts)","Webhook replay attack -> signature verification","Recipient MX greylists -> deferral + retry with backoff"],
  "checklist":["send queue + workers","MTA/API adapters + failover","pixel + redirect + webhook receivers (public HTTPS)","event normalizer","warmup/throttle controller","reputation tracker"]
},

"12_linkedin_engine": {
  "num":"12","name":"LinkedIn Automation Engine",
  "folder":"09_LinkedIn_Engine",
  "replaces":"Smartlead/Expandi/Dux-Soup — LinkedIn touches, gated by ban-risk controls.",
  "purpose":"Native, safety-first LinkedIn outreach: connection requests, messages, InMail, profile views and post engagement as journey/sequence steps — behind a strict ban-risk circuit breaker, human-like pacing, and per-seat daily limits. Deliberately the last capability activated.",
  "scope_in":["LinkedIn action steps: connect, message, InMail, view, follow, like","Per-seat daily limits + human-like randomized pacing","Ban-risk circuit breaker + anomaly halt","Seat/session management (per-user auth)","Reply detection -> pause-on-reply"],
  "scope_out":["Scraping/enrichment (Enrichment Engine)","Content generation (AI Engine)","Signal capture from LinkedIn (Signal Engine SIG-EXEC)"],
  "personas":[["AE","Owns a LinkedIn seat, runs sequences"],["Admin","Sets limits & risk policy"],["System","Executes paced actions"]],
  "entities":[
    ("li_seat","A connected LinkedIn account/seat.","id UUID pk; tenant_id UUID; user_id UUID; status enum(active,cooldown,disconnected,banned_suspected); daily_limits jsonb; health numeric(4,3); last_action_at"),
    ("li_action","A queued/executed action.","id UUID pk; seat_id UUID; contact_id UUID; type enum(connect,message,inmail,view,follow,like); status enum(queued,sent,accepted,replied,failed,skipped); scheduled_at; executed_at; detail jsonb"),
    ("li_sequence","A LinkedIn-only sequence (or journey steps).","id UUID pk; tenant_id UUID; name text; steps jsonb; pacing jsonb")
  ],
  "apis":[
    ("POST","/v1/linkedin/seats","Connect/register a seat.","201"),
    ("POST","/v1/linkedin/actions","Queue an action (paced).","202"),
    ("GET","/v1/linkedin/seats/{id}/health","Seat health + limits + risk.","200"),
    ("POST","/v1/linkedin/circuit-breaker:status","Query/trip circuit breaker.","200")
  ],
  "workflows":["Action queued -> circuit breaker healthy? -> within seat daily limit & pacing window? -> execute with human-like delay -> detect accept/reply -> reply => pause-on-reply + account-centric pause","Anomaly (spike in failures/captcha) -> trip breaker -> seat cooldown -> notify"],
  "states":("li_seat",["active","cooldown","disconnected","banned_suspected"],"active->cooldown on limit/anomaly; ->banned_suspected on hard signals; ->disconnected on auth loss"),
  "events_pub":["linkedin.action.sent","linkedin.reply.received","linkedin.seat.cooldown","linkedin.circuit_breaker.tripped"],
  "events_sub":["journey.step.linkedin","account.held"],
  "rules":[
    "LI-001: No LinkedIn action executes unless the ban-risk circuit breaker is healthy (hard gate).",
    "LI-002: Per-seat daily caps + randomized human-like pacing strictly enforced.",
    "LI-003: Reply => pause-on-reply + account-centric pause.",
    "LI-004: Suspected-ban => immediate seat halt + human notification; no auto-retry.",
    "LI-005: This engine is activated last in the roadmap, after the breaker service is proven."
  ],
  "permissions":[["linkedin.seat.manage","AE(own), Admin"],["linkedin.action.queue","AE, system"],["linkedin.policy.manage","Admin"]],
  "validations":["action within seat limits","seat active","contact has linkedin_url"],
  "errors":["503 breaker tripped","429 seat daily cap","409 duplicate pending action"],
  "integrations_internal":["Journey Engine","Contact Engine (reply->pause)","Account Engine (cascade)","Notification"],
  "testing":["Breaker halts all actions","Pacing randomization within human bounds","Cap enforcement per seat","Reply triggers cascade"],
  "acceptance":["Run a connect+message sequence within limits; reply pauses account","Simulated anomaly trips breaker and halts seats"],
  "edge":["Seat auth expires mid-sequence -> queue holds, notify, no data loss","Two AEs target same contact -> collision guard","Captcha detected -> cooldown not retry"],
  "checklist":["seat/session mgmt","paced action executor","circuit breaker service","reply detector","limit config","cooldown state machine"]
},

"13_landing_forms_engine": {
  "num":"13","name":"Landing Page & Forms Engine",
  "folder":"07_Marketing_Automation",
  "replaces":"HubSpot Landing Pages + Forms + Unbounce + popups/preference center.",
  "purpose":"Native landing pages, forms, popups, preference & unsubscribe centers: a builder + hosting + submission pipeline that captures leads directly into the CRM, powers gated assets (whitepaper/case-study downloads), and manages consent — closing the loop the BFSI whitepaper campaign needed.",
  "scope_in":["Landing page builder (blocks) + hosting + SEO/OG/JSON-LD","Forms (fields, validation, progressive profiling, hidden UTM)","Popups & preference center + unsubscribe center","Submission -> contact create/update + journey enroll + consent capture","Gated content delivery (asset unlock)"],
  "scope_out":["Asset storage (Asset Library 14)","Email sending (Delivery/Marketing)","Analytics math (Analytics)"],
  "personas":[["Marketer","Builds pages/forms"],["Visitor/Lead","Submits form"],["System","Processes submission -> CRM"]],
  "entities":[
    ("landing_page","Hosted page.","id UUID pk; tenant_id UUID; slug text unique; title text; blocks jsonb; seo jsonb; status enum(draft,published); form_id UUID null; asset_id UUID null; created_at"),
    ("form","Form definition.","id UUID pk; tenant_id UUID; name text; fields jsonb; consent_config jsonb; progressive bool; redirect jsonb; created_at"),
    ("submission","A form submission.","id UUID pk; form_id UUID; landing_page_id UUID null; contact_id UUID null; data jsonb; utm jsonb; consent_given bool; ip inet; created_at"),
    ("preference","Contact channel preferences.","id UUID pk; contact_id UUID; channels jsonb; unsubscribed_all bool; updated_at")
  ],
  "apis":[
    ("POST","/v1/pages","Create/publish a landing page.","201"),
    ("POST","/v1/forms","Create a form.","201"),
    ("POST","/v1/forms/{id}/submit","Public submission endpoint.","201"),
    ("GET","/p/{slug}","Public render of a landing page.","200 html"),
    ("PUT","/v1/preferences/{contact}","Update preference/unsub center.","200")
  ],
  "workflows":["Publish page/form -> visitor submits -> validate + spam check -> upsert contact (identity resolution) + capture consent + UTM -> optional journey enroll + gated asset unlock -> emit form.submitted","Preference center update -> propagate consent/suppression"],
  "states":("landing_page",["draft","published","archived"],"draft->published on publish; ->archived"),
  "events_pub":["form.submitted","page.published","preference.updated","consent.captured"],
  "events_sub":["campaign.activated (link pages)","asset.published"],
  "rules":[
    "LP-001: Every form capturing contactable data must capture explicit consent (PDPL) + store IP/timestamp.",
    "LP-002: Submission upserts via Identity Resolution — no blind duplicate contacts.",
    "LP-003: Unsubscribe center writes global suppression immediately.",
    "LP-004: Gated asset served only after valid submission; link is signed & expiring.",
    "LP-005: Canonical/OG URLs must be real published paths before indexing."
  ],
  "permissions":[["pages.manage","Marketer, Admin"],["forms.manage","Marketer, Admin"],["submissions.read","Marketer, AE, Admin"]],
  "validations":["slug unique","required fields","consent present when required","valid redirect"],
  "errors":["409 slug taken","422 missing consent","429 submission rate-limit (bot)"],
  "integrations_internal":["Contact Engine (upsert)","Journey (enroll)","Asset Library (unlock)","Marketing (suppression)","Analytics (conversion)"],
  "testing":["Submission dedups to existing contact","Consent stored with proof","Gated link expires","Bot/spam rate limiting"],
  "acceptance":["Publish a gated whitepaper page; submission creates contact, captures consent, unlocks asset, enrolls in journey","Unsub center suppresses globally"],
  "edge":["Repeat submitter -> progressive profiling adds fields, no dup","Missing UTM -> direct/organic attribution","Asset link shared -> expiry blocks non-submitters"],
  "checklist":["page/form builder + renderer","submission pipeline + identity upsert","consent + preference center","gated asset signer","spam protection","SEO/OG/JSON-LD"]
},

"14_asset_library": {
  "num":"14","name":"Asset Library",
  "folder":"07_Marketing_Automation",
  "replaces":"HubSpot Files + DAM — content & collateral store.",
  "purpose":"Central store for marketing/sales collateral (whitepapers, case studies, one-pagers, decks, images) with versioning, gating, usage tracking and CDN delivery — the source of truth for every asset a campaign, landing page or email references.",
  "scope_in":["Asset upload + versioning + metadata/tags","Gating flag + signed/expiring links","Usage tracking (downloads, which campaigns use it)","CDN/hosting + access control","AI-generated asset intake (proposals/case studies from AI Engine)"],
  "scope_out":["Generation (AI Engine)","Page building (Landing Engine)","Email templates (Marketing Engine)"],
  "personas":[["Marketer","Manages collateral"],["AE","Attaches assets to outreach"],["System","Stores AI-generated assets"]],
  "entities":[
    ("asset","A stored asset.","id UUID pk; tenant_id UUID; name text; type enum(whitepaper,case_study,one_pager,deck,image,pdf,doc,other); storage_url text; gated bool; tags text[]; version int; owner_id UUID; created_at"),
    ("asset_usage","Where/when used.","id UUID pk; asset_id UUID; context_type enum(campaign,landing,email,linkedin); context_id UUID; downloads int; last_used_at")
  ],
  "apis":[
    ("POST","/v1/assets","Upload/register asset (versioned).","201"),
    ("GET","/v1/assets","Search/filter by type/tag.","200"),
    ("POST","/v1/assets/{id}:sign","Get a signed expiring download link.","200"),
    ("GET","/v1/assets/{id}/usage","Usage & download analytics.","200")
  ],
  "workflows":["Upload -> virus/type check -> version -> CDN publish -> available to campaigns/pages/emails; gated assets served via signed links from Landing/Email","AI Engine outputs proposal/case study -> stored as asset version"],
  "states":("asset",["draft","published","archived"],"draft->published on publish; new upload => version++; ->archived"),
  "events_pub":["asset.published","asset.downloaded"],
  "events_sub":["ai.generation.approved (store output)","form.submitted (gated download)"],
  "rules":[
    "AST-001: Gated assets only served via signed, expiring links (no public URL).",
    "AST-002: New upload creates a new version; old versions retained & referenceable.",
    "AST-003: Download events feed engagement + campaign analytics.",
    "AST-004: File type/size validated; malware-scanned before publish."
  ],
  "permissions":[["assets.manage","Marketer, Admin"],["assets.read","All"]],
  "validations":["allowed type/size","unique name+version","signed link TTL set"],
  "errors":["415 unsupported type","413 too large","410 expired link"],
  "integrations_internal":["Landing/Forms (gating)","Marketing/Email (attach)","AI Engine (store outputs)","Analytics (downloads)"],
  "testing":["Version increments correctly","Signed link expiry","Malware scan gate","Usage tracking accuracy"],
  "acceptance":["Upload a case study, gate it, serve via expiring link, track downloads","New version supersedes but keeps old"],
  "edge":["Same asset used in 3 campaigns -> usage attributed to each","Expired link re-request after new submission -> fresh link","Archived asset referenced by live page -> warn before archive"],
  "checklist":["asset + usage tables","upload + versioning + scan","CDN + signed links","usage tracker"]
},
}
