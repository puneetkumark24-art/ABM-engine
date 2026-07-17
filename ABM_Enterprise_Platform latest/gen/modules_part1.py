# -*- coding: utf-8 -*-
"""Module content, batch 1 (modules 01-07). Each entry is a rich dict consumed by build.py."""

MODULES_1 = {
"01_intelligence_engine": {
  "num": "01", "name": "Intelligence Engine", "folder": "02_Intelligence",
  "replaces": "The 'brain' — no direct external equivalent; the orchestration layer above Clay/Apollo/6sense intent.",
  "purpose": "The central reasoning and orchestration layer that turns raw captured signals and enriched graph data into ranked, explained, action-ready intelligence. It owns the confidence model (EPIS), the reasoning streams (HYP/VSAT/POWER/TENSION/MOBILITY), and the 'why now / who / what to say' synthesis every downstream engine consumes.",
  "scope_in": ["Signal reasoning streams and hypothesis generation","EPIS confidence calibration on every derived fact","Account/opportunity synthesis (why-now narratives)","Next-Best-Action computation feeding CRM & Journey engines","Intelligence briefs (account, persona, meeting)"],
  "scope_out": ["Raw capture (Signal Engine, 02)","Contact/company enrichment I/O (Enrichment Engine, 03)","Message copywriting (AI Personalization Engine, 10)","Delivery of any kind"],
  "personas": [["BD/AE","Consumes briefs & NBA, asks the Copilot 'who do I call'"],["Sales Manager","Reviews account narratives and risk flags"],["Platform (system)","Primary consumer — every engine reads intelligence outputs"],["Data Steward","Audits confidence calibration and reasoning provenance"]],
  "entities": [
    ("intelligence_record","One synthesized intelligence item about an entity.","id UUID pk; tenant_id UUID fk; subject_type enum(account,contact,opportunity,vendor); subject_id UUID; kind enum(narrative,nba,risk,hypothesis,brief); title text; body jsonb; confidence numeric(4,3); evidence_refs uuid[]; decay_expires_at timestamptz; created_by enum(system,user); created_at timestamptz; superseded_by UUID null"),
    ("hypothesis","A competing explanation for a signal cluster with its own confidence (SIG-HYP).","id UUID pk; tenant_id UUID; signal_cluster_id UUID; statement text; confidence numeric(4,3); supporting_evidence uuid[]; contradicting_evidence uuid[]; status enum(open,confirmed,rejected); created_at timestamptz"),
    ("nba_recommendation","Next-Best-Action for an entity.","id UUID pk; tenant_id UUID; account_id UUID; action_code text; rationale text; confidence numeric(4,3); expected_value numeric; expires_at timestamptz; consumed_by UUID null; status enum(pending,taken,expired,dismissed)"),
    ("evidence_ref","Provenance pointer used by EPIS.","id UUID pk; source_type enum(signal,document,enrichment,activity); source_id UUID; reliability numeric(4,3); observed_at timestamptz")
  ],
  "apis": [
    ("GET","/v1/intelligence/accounts/{id}/brief","Return the synthesized account brief (why-now, committee, risks, NBA).","200 IntelligenceBrief; 404"),
    ("GET","/v1/intelligence/accounts/{id}/nba","Ranked Next-Best-Actions for an account.","200 [NBA]"),
    ("POST","/v1/intelligence/hypotheses:generate","Run reasoning streams over a signal cluster, return hypotheses w/ confidence.","202 job; 200 [Hypothesis]"),
    ("POST","/v1/intelligence/records:query","Filter intelligence records by subject/kind/min-confidence.","200 paged"),
    ("POST","/v1/intelligence/records/{id}:supersede","Mark a record stale and link its replacement.","200")
  ],
  "workflows": ["Signal cluster promoted -> reasoning streams run -> EPIS stamps confidence -> intelligence_record persisted -> event intelligence.record.created emitted -> Scoring & CRM subscribe","NBA lifecycle: computed -> surfaced in CRM timeline -> taken/dismissed -> outcome feeds Lead Scoring"],
  "states": ("intelligence_record", ["draft","active","decayed","superseded"], "draft->active on EPIS pass; active->decayed at decay_expires_at; active->superseded when a newer record covers same subject/kind"),
  "events_pub": ["intelligence.record.created","intelligence.nba.created","intelligence.hypothesis.confirmed"],
  "events_sub": ["signal.cluster.promoted","enrichment.entity.updated","activity.logged"],
  "rules": [
    "INT-001: No intelligence_record may be persisted without >=1 evidence_ref.",
    "INT-002: confidence = f(evidence reliability, corroboration count, recency) via EPIS; never hardcoded to 1.0.",
    "INT-003: A record whose every evidence_ref is expired is auto-decayed nightly.",
    "INT-004: NBA expected_value must be recomputed if the underlying account score changes by >10 points.",
    "INT-005: C-suite-targeted NBAs are always flagged human_review_required regardless of autonomy tier."
  ],
  "permissions": [["intelligence.read","AE, Manager, Admin"],["intelligence.hypothesis.generate","Manager, Admin, system"],["intelligence.record.supersede","Data Steward, Admin"]],
  "validations": ["confidence in [0,1]","subject_id must resolve within tenant","decay_expires_at > created_at"],
  "errors": ["422 no-evidence on persist","409 supersede loop (A supersedes B supersedes A)","404 unknown subject"],
  "integrations_internal": ["Signal Engine (input clusters)","Enrichment Engine (graph facts)","Scoring Engine (consumes/refreshes)","AI Personalization (brief -> copy)","Copilot (query surface)"],
  "testing": ["Unit: EPIS confidence monotonicity (more corroboration never lowers confidence)","Contract: brief schema stable","Property: decayed records never surface in NBA","Golden-file: fixed signal set -> deterministic hypothesis ranking"],
  "acceptance": ["Given a promoted cluster, a hypothesis set with calibrated confidence is produced <5s","Account brief renders committee+why-now+top-3 NBA","Superseded records disappear from all read APIs"],
  "edge": ["Contradictory signals of equal reliability -> two open hypotheses, none auto-confirmed","Zero contacts on account -> NBA = 'discover committee' not 'email CDO'","Signal storm (100+ in an hour) -> dedup+cluster before reasoning to avoid brief spam"],
  "checklist": ["EPIS module + reliability table","Reasoning stream runners (5)","intelligence_record + hypothesis + nba tables & migrations","brief assembler","NBA ranker","event pub/sub wiring","decay job"]
},

"02_signal_engine": {
  "num":"02","name":"Signal Detection Engine","folder":"03_Signal_Detection",
  "replaces":"6sense/Bombora intent + Google Alerts + custom scrapers — capture & first-pass classification.",
  "purpose":"Autonomous capture of buying and context signals across eight sourcing sub-streams, with provenance, idempotency, relevance filtering, dedup, and decay — producing clean, deduped, confidence-eligible signals for the Intelligence Engine.",
  "scope_in":["8 capture sub-streams (NEWS/REG/EXEC/VENDOR/SUBS/EVENT/FIN/PATH)","raw_captures provenance log + dedup","SIG-RELEVANCE 4-axis filter","Signal decay stamping","Clustering related signals"],
  "scope_out":["Deep reasoning (Intelligence Engine)","Contact enrichment (Enrichment Engine)","LinkedIn action-taking (LinkedIn Engine, 12)"],
  "personas":[["System","Runs streams on cadence"],["Data Steward","Tunes sources & relevance rules"],["BD/AE","Sees the filtered signal feed"]],
  "entities":[
    ("raw_capture","Append-only provenance record of every fetch.","id UUID pk; tenant_id UUID; stream enum(news,reg,exec,vendor,subs,event,fin,path); source_url text; payload jsonb; dedup_hash text unique; fetched_at timestamptz"),
    ("signal","A promoted, relevant signal.","id UUID pk; tenant_id UUID; account_id UUID null; type enum(leadership,regulatory,product,hiring,funding,tender,partnership,event,financial); title text; summary text; urgency enum(P1,P2,P3,P4); relevance numeric(4,3); confidence numeric(4,3); source_reliability numeric(4,3); decay_category enum(fast,medium,slow); decay_expires_at timestamptz; cluster_id UUID null; raw_capture_id UUID fk; created_at timestamptz"),
    ("signal_cluster","Group of signals describing one underlying event.","id UUID pk; tenant_id UUID; account_id UUID; label text; signal_ids uuid[]; promoted bool; created_at"),
    ("source","A configured capture source.","id UUID pk; tenant_id UUID; stream enum; name text; url_or_query text; cadence_cron text; reliability numeric(4,3); enabled bool; ban_risk enum(none,low,high)")
  ],
  "apis":[
    ("GET","/v1/signals","Filter feed by account/type/urgency/min-relevance/date.","200 paged"),
    ("POST","/v1/signals","Manual signal entry (a capture adapter).","201"),
    ("POST","/v1/signals/{id}:reclassify","Override type/urgency; logged.","200"),
    ("GET","/v1/sources","List configured sources.","200"),
    ("POST","/v1/sources","Add/enable a source with cadence + ban-risk.","201"),
    ("POST","/v1/signals:ingest","Internal ingest endpoint used by stream workers.","202")
  ],
  "workflows":["Worker fetches -> write raw_capture (dedup_hash) -> relevance filter (4 axes) -> if high: create signal + stamp decay -> cluster -> emit signal.created / signal.cluster.promoted","Ban-risk circuit breaker: high-risk stream (LinkedIn) throttles/halts on anomaly before capture"],
  "states":("signal",["captured","filtered_out","active","expired","clustered"],"captured->active on relevance pass; captured->filtered_out on low relevance (retained, not surfaced); active->expired at decay; active->clustered when joined to a cluster"),
  "events_pub":["signal.created","signal.cluster.promoted","signal.filtered_out","source.ban_risk.tripped"],
  "events_sub":["schedule.tick","account.created (to seed watches)"],
  "rules":[
    "SIG-001: Nothing becomes a signal without first existing as a raw_capture (provenance mandatory).",
    "SIG-002: dedup_hash collision => merge into existing signal, never create duplicate.",
    "SIG-003: Relevance <0.4 => filtered_out (retained, never surfaced to users).",
    "SIG-004: LinkedIn/SIG-PATH streams may not run until ban-risk circuit breaker service is healthy.",
    "SIG-005: Every signal carries decay_category; expired signals excluded from scoring reads."
  ],
  "permissions":[["signals.read","All roles"],["signals.create","AE, Steward, system"],["sources.manage","Steward, Admin"]],
  "validations":["dedup_hash unique per tenant","relevance/confidence in [0,1]","cadence_cron valid"],
  "errors":["409 duplicate capture","422 invalid cron","503 stream disabled by circuit breaker"],
  "integrations_internal":["Intelligence Engine (clusters out)","Account Engine (attribution)","Scoring (signal strength dim)","Enrichment (trigger on leadership/hiring)"],
  "testing":["Idempotency: same payload twice -> one signal","Relevance gate golden set","Decay expiry excludes from scoring query","Circuit breaker halts high-risk stream on simulated ban"],
  "acceptance":["Re-running a scan never inflates counts","Football-sponsorship vs RFP correctly separated by relevance","Expired signals vanish from feed default view"],
  "edge":["Same event from 2 feeds -> single clustered signal","Non-English (Arabic) source -> language-tagged, still filtered","Source goes 404 -> disabled + steward notified, no crash"],
  "checklist":["raw_captures + signals + clusters + sources tables","8 stream workers (NEWS live; others staged)","relevance filter service","dedup + decay","circuit breaker","feed API"]
},

"03_enrichment_engine": {
  "num":"03","name":"Contact & Account Enrichment Engine","folder":"04_Contact_Enrichment",
  "replaces":"Apollo + Clay + ZoomInfo + Lusha — data acquisition, waterfall enrichment, verification.",
  "purpose":"Acquire, resolve, verify and continuously refresh contact and company data into the graph — a native waterfall enrichment pipeline with provider adapters, email/phone verification, and identity resolution, so the platform owns its data instead of renting Apollo.",
  "scope_in":["Provider adapter framework (pluggable data sources)","Waterfall enrichment (try sources in priority order)","Email/phone verification & scoring","Identity resolution & merge","Refresh scheduling & staleness detection"],
  "scope_out":["Signal capture (Signal Engine)","Relationship inference (Relationship Graph Engine, 05-graph)","Outreach"],
  "personas":[["System","Runs enrichment jobs"],["Data Steward","Configures providers, resolves merge conflicts"],["AE","Requests enrichment on a target"]],
  "entities":[
    ("enrichment_job","One enrichment request for an entity.","id UUID pk; tenant_id UUID; entity_type enum(contact,company); entity_id UUID; status enum(queued,running,partial,done,failed); providers_tried text[]; result jsonb; cost_credits int; created_at; finished_at"),
    ("provider","A configured data source adapter.","id UUID pk; name text; kind enum(contact,company,email_verify,phone_verify); priority int; cost_per_call numeric; rate_limit int; enabled bool; config jsonb"),
    ("verification","Email/phone verification result.","id UUID pk; contact_id UUID; channel enum(email,phone); status enum(valid,invalid,risky,unknown,catch_all); score numeric(4,3); verified_at timestamptz"),
    ("merge_candidate","Two records suspected identical.","id UUID pk; entity_type enum; a_id UUID; b_id UUID; similarity numeric(4,3); signals jsonb; status enum(pending,merged,rejected)")
  ],
  "apis":[
    ("POST","/v1/enrichment/jobs","Enqueue enrichment for a contact/company.","202 job"),
    ("GET","/v1/enrichment/jobs/{id}","Job status + result.","200"),
    ("POST","/v1/enrichment/verify","Verify an email/phone synchronously.","200 Verification"),
    ("GET","/v1/enrichment/merge-candidates","List pending merges.","200"),
    ("POST","/v1/enrichment/merge-candidates/{id}:resolve","Merge or reject.","200"),
    ("POST","/v1/providers","Register/configure a provider adapter.","201")
  ],
  "workflows":["Job queued -> waterfall: call providers by priority until fields filled or exhausted -> verify email/phone -> upsert to graph via Identity Resolution -> emit enrichment.entity.updated","Nightly staleness scan -> re-enqueue contacts older than N days"],
  "states":("enrichment_job",["queued","running","partial","done","failed"],"queued->running on worker pick; running->partial if some fields found; ->done when verified & upserted; ->failed on all providers exhausted"),
  "events_pub":["enrichment.entity.updated","enrichment.verification.completed","enrichment.merge.detected"],
  "events_sub":["contact.created","signal.created (leadership/hiring -> enrich)","account.tiered (HOT -> enrich committee)"],
  "rules":[
    "ENR-001: Waterfall stops at first source that satisfies required fields (cost control).",
    "ENR-002: Never overwrite a verified field with an unverified value (Identity Resolution guard).",
    "ENR-003: Email status 'invalid'/'risky' sets contact do_not_email until re-verified.",
    "ENR-004: Merge requires similarity>=0.9 OR a hard key match (LinkedIn URL / verified email).",
    "ENR-005: Enrichment credit spend per account capped by tier (HOT>WARM>COLD=0)."
  ],
  "permissions":[["enrichment.request","AE, Steward, system"],["providers.manage","Admin"],["merge.resolve","Steward, Admin"]],
  "validations":["entity resolves in tenant","provider priority unique per kind","similarity in [0,1]"],
  "errors":["402 credit cap exceeded","409 merge conflict on verified fields","429 provider rate limit -> waterfall to next"],
  "integrations_internal":["Identity Resolution (05/graph)","Contact & Account Engines","Signal Engine (triggers)","Admin (credit quotas)"],
  "testing":["Waterfall stops early when field satisfied","Verified value not clobbered","Credit cap enforced","Merge on hard-key match"],
  "acceptance":["HOT account committee auto-enriched within SLA","Invalid emails auto-suppressed","Duplicate contact from 2 providers merges to one"],
  "edge":["All providers fail -> job.failed, entity keeps prior data","Catch-all domain -> status catch_all, score mid, flagged","Conflicting titles across providers -> keep highest-reliability, log others"],
  "checklist":["provider adapter interface + 2 stub adapters","waterfall orchestrator","email/phone verifier","merge engine","credit metering hook","staleness scanner"]
},

"04_contact_engine": {
  "num":"04","name":"Contact Intelligence Engine","folder":"04_Contact_Enrichment",
  "replaces":"HubSpot Contacts + Apollo person records — the people system of record & scoring.",
  "purpose":"System of record for people at scale (architected for 1M+ contacts): profile, career history, persona classification, decision authority, engagement history, and per-contact intelligence — the authoritative contact object every other engine references.",
  "scope_in":["Contact CRUD & bulk import","Persona & seniority classification","Decision authority / buying influence scoring","Engagement history rollup","Consent & suppression state on the person"],
  "scope_out":["Company/account object (Account Engine)","Committee role mapping (CRM Engine relationship layer)","Message sending"],
  "personas":[["AE","Owns and works contacts"],["Steward","Maintains data quality"],["System","Classifies & scores"]],
  "entities":[
    ("contact","A person.","id UUID pk; tenant_id UUID; account_id UUID null; full_name text; first_name text; last_name text; title text; department text; seniority enum(c_suite,evp,svp,vp,director,manager,ic); persona_code text; decision_authority numeric(4,3); buying_influence numeric(4,3); email citext; email_status enum; phone text; linkedin_url text unique; country text; city text; consent_status enum(none,opted_in,denied); do_not_contact bool; owner_id UUID; lifecycle enum(subscriber,lead,mql,sql,opportunity,customer); created_at; updated_at; source text"),
    ("career_event","Job history / mobility.","id UUID pk; contact_id UUID; org_name text; title text; start_date date; end_date date null; is_current bool; detected_via enum(enrichment,signal_exec)"),
    ("contact_engagement","Rolled-up engagement stats.","contact_id UUID pk; opens int; clicks int; replies int; meetings int; last_interaction_at timestamptz; engagement_score numeric(4,3)")
  ],
  "apis":[
    ("GET","/v1/contacts","Search/filter (title, seniority, account, persona, score).","200 paged"),
    ("POST","/v1/contacts","Create contact.","201"),
    ("PATCH","/v1/contacts/{id}","Update fields (guarded).","200"),
    ("POST","/v1/contacts:bulk","Bulk import CSV/JSON.","202 job"),
    ("GET","/v1/contacts/{id}/timeline","Unified activity timeline.","200"),
    ("POST","/v1/contacts/{id}:classify","Recompute persona/authority.","200")
  ],
  "workflows":["Create/import -> enrichment triggered -> persona & authority classified -> engagement rollup subscribes to activity events -> mobility (SIG-EXEC) creates career_event + may transfer warm relationship","Consent change -> propagate do_not_contact everywhere"],
  "states":("contact.lifecycle",["subscriber","lead","mql","sql","opportunity","customer"],"advances on scoring thresholds & CRM deal linkage; can regress on disqualify"),
  "events_pub":["contact.created","contact.updated","contact.classified","contact.consent.changed","contact.mobility.detected"],
  "events_sub":["enrichment.entity.updated","activity.logged","email.event.*","deal.stage.changed"],
  "rules":[
    "CON-001: linkedin_url and verified email are unique identity keys per tenant.",
    "CON-002: do_not_contact=true blocks enrollment in any journey/campaign at enrollment time AND send time.",
    "CON-003: seniority c_suite forces human_review on any outreach (ties to autonomy ladder).",
    "CON-004: engagement_score feeds account Persona-Reachability (20%).",
    "CON-005: A contact with email_status invalid is do_not_email until re-verified."
  ],
  "permissions":[["contacts.read","All"],["contacts.write","AE, Steward, Admin"],["contacts.bulk","Steward, Admin"],["contacts.delete","Admin"]],
  "validations":["email format + tenant-unique","seniority in enum","scores in [0,1]"],
  "errors":["409 duplicate identity key","422 invalid consent transition","413 bulk too large -> chunk"],
  "integrations_internal":["Account Engine","Enrichment","CRM Engine (committee)","Marketing/Journey (enrollment gating)","Lead Scoring"],
  "testing":["Dedup on linkedin/email","Consent propagation blocks send","1M-row import performance (batched)","Timeline merges all channels in order"],
  "acceptance":["Import 10k contacts deduped & enriched","c-suite contact always flags review","Consent denial removes from active journeys"],
  "edge":["Same person two accounts (board seats) -> primary + secondary affiliation","Name-only contact (no email) -> enrichment queued, not enrollable","Mobility to competitor -> relationship transfers, old edge archived"],
  "checklist":["contact + career_event + engagement tables (partitioned)","classifier","bulk importer (chunked)","timeline assembler","consent propagation job"]
},

"05_account_engine": {
  "num":"05","name":"Account Engine",
  "folder":"05_Account_Management",
  "replaces":"HubSpot Companies + 6sense account model — the account system of record & tiering.",
  "purpose":"System of record for target organizations and their structure (parents, subsidiaries, vendors, tech stack), the account scoring inputs, tiering (HOT/WARM/COLD), and the account-centric orchestration rule that one reply pauses the whole account.",
  "scope_in":["Account CRUD & hierarchy (parent/subsidiary)","Tech stack & vendor mapping on the account","Account tier assignment & daily budget","Account-level pause/hold state","Product-fit mapping (account x product)"],
  "scope_out":["Score computation math (Lead Scoring Engine, 18) — Account Engine stores & consumes","People (Contact Engine)","Deals (Pipeline/CRM)"],
  "personas":[["AE","Works target accounts"],["Manager","Allocates tiers/territories"],["System","Tiers & budgets"]],
  "entities":[
    ("account","Target organization.","id UUID pk; tenant_id UUID; name text; type enum(bank,fintech,subsidiary,vendor,regulator,consulting); parent_id UUID null; segment text; sub_segment text; tier enum(hot,warm,cold); digital_maturity enum(low,med,high); core_banking text; open_banking enum(none,v1,v2); score numeric(5,2); status enum(active,paused,excluded); employees int; website text; country text; created_at; updated_at"),
    ("account_tech","Technology/vendor used by account.","id UUID pk; account_id UUID; category enum(core,los,lms,payments,fraud,aml,kyc,cloud,api_gw,crm); vendor text; confidence numeric(4,3); source text; entrenchment numeric(4,3)"),
    ("product_fit","Account x Decimal product fit.","id UUID pk; account_id UUID; product_id UUID; fit_score numeric(4,3); pitch_angle text"),
    ("account_hold","Pause/hold record (account-centric rule).","id UUID pk; account_id UUID; reason enum(reply,meeting,manual,compliance); started_at; expires_at null; created_by")
  ],
  "apis":[
    ("GET","/v1/accounts","Filter by tier/segment/score/status.","200 paged"),
    ("POST","/v1/accounts","Create account.","201"),
    ("PATCH","/v1/accounts/{id}","Update (tier/status guarded).","200"),
    ("GET","/v1/accounts/{id}/graph","Account + subsidiaries + vendors + committee.","200"),
    ("POST","/v1/accounts/{id}:hold","Pause the account (reason).","200"),
    ("POST","/v1/accounts/{id}:release","Release a hold.","200")
  ],
  "workflows":["Score change -> re-tier (HOT>=75/WARM>=50/COLD) -> set daily budget -> HOT triggers committee enrichment","Positive reply anywhere -> account_hold(reason=reply) -> all journeys for account pause -> notify owner"],
  "states":("account.status",["active","paused","excluded"],"active->paused on hold; paused->active on release/expiry; ->excluded manual/compliance"),
  "events_pub":["account.created","account.tiered","account.held","account.released"],
  "events_sub":["score.updated","email.reply.received","meeting.booked","enrichment.entity.updated"],
  "rules":[
    "ACC-001: Account-centric pause — a hold suspends every active journey/campaign touch for the account.",
    "ACC-002: Max 5 new accounts activated per day per tenant (MVP budget).",
    "ACC-003: Tier thresholds HOT>=75, WARM>=50, else COLD; recomputed on score change.",
    "ACC-004: Enrichment credit only for HOT (full) and WARM (limited); COLD=0.",
    "ACC-005: entrenchment on incumbent vendor lowers Effective-Opportunity (Scoring modifier)."
  ],
  "permissions":[["accounts.read","All"],["accounts.write","AE, Manager, Admin"],["accounts.tier.override","Manager, Admin"],["accounts.exclude","Admin"]],
  "validations":["parent_id != self; no cycles","tier in enum","score 0..100"],
  "errors":["409 hierarchy cycle","422 invalid tier override without reason","423 account locked (held) for outreach"],
  "integrations_internal":["Contact Engine","Lead Scoring","Journey/Campaign (pause gate)","Intelligence (narrative)","Pipeline"],
  "testing":["Hold cascades to all journeys","Re-tier on score cross","Cycle prevention in hierarchy","Daily activation cap"],
  "acceptance":["Reply pauses entire account within seconds","HOT auto-enriches committee","Subsidiary rolls up to parent in graph view"],
  "edge":["Subsidiary hot, parent cold -> independent tiers, shared relationships","Merge two accounts (M&A) -> hierarchy + dedupe","Excluded account never re-enters via import"],
  "checklist":["account + account_tech + product_fit + hold tables","tiering service","hold/cascade orchestrator","hierarchy graph query","budget counter"]
},

"06_crm_engine": {
  "num":"06","name":"CRM Engine (HubSpot Replica)",
  "folder":"06_CRM_Engine",
  "replaces":"HubSpot CRM in full — accounts, contacts, deals, activities, custom objects, properties, timelines, workflows.",
  "purpose":"A full native CRM: the relational spine tying accounts, contacts, companies, buying committees, relationship graph, deals, pipelines, activities, tasks, notes, custom objects and properties into one auditable system of record with AI timeline, engagement scoring, next-best-action, forecasting, duplicate/merge, search, views, lists and segments — reproducing HubSpot CRM capability natively.",
  "scope_in":["Objects: Account, Contact, Company, Deal, Opportunity, Activity, Task, Note, Meeting, Call, Email, Custom Object","Buying Committee & Relationship Graph","Properties framework (custom fields) + Lead Status + Lifecycle","Pipelines & stages (thin ref to Pipeline Engine 19)","Owners/Teams/Permissions, Views/Lists/Segments/Tags","AI Timeline, Engagement Score, Next-Best-Action surfacing, Forecasting hooks","Duplicate detection, Merge engine, Search, Audit logs"],
  "scope_out":["Score math (18)","Marketing sends (07)","Journey logic (08)"],
  "personas":[["AE","Lives in the CRM daily"],["Manager","Forecasts, reviews pipeline"],["Ops/Admin","Defines objects, properties, pipelines"],["System","Writes activities & NBAs to timeline"]],
  "entities":[
    ("crm_object","Polymorphic object registry (built-in + custom).","id UUID pk; tenant_id UUID; object_type text; is_custom bool; label text; schema jsonb; created_at"),
    ("property","Custom/standard field definition.","id UUID pk; tenant_id UUID; object_type text; key text; label text; data_type enum(text,number,date,enum,bool,ref,calc); options jsonb; required bool; unique bool; group text"),
    ("deal","Sales deal/opportunity.","id UUID pk; tenant_id UUID; account_id UUID; name text; pipeline_id UUID; stage_id UUID; amount numeric; currency text; probability numeric(4,3); close_date date; owner_id UUID; status enum(open,won,lost); lost_reason text; created_at; updated_at"),
    ("activity","Any interaction (universal activity).","id UUID pk; tenant_id UUID; type enum(email,call,meeting,linkedin,whatsapp,note,task,demo,rfp,poc); subject_type enum(account,contact,deal); subject_id UUID; owner_id UUID; occurred_at timestamptz; outcome text; body jsonb; source enum(user,system)"),
    ("committee_member","Buying committee role mapping.","id UUID pk; account_id UUID; contact_id UUID; product_id UUID; role enum(decision_maker,influencer,champion,blocker,approver,user); influence numeric(4,3); engagement numeric(4,3)"),
    ("relationship","Graph edge (org/person/vendor/tech).","id UUID pk; from_type enum; from_id UUID; to_type enum; to_id UUID; rel_type text; strength numeric(4,3); confidence numeric(4,3); source text; start_date date; end_date date null"),
    ("view","Saved filter/segment/list.","id UUID pk; tenant_id UUID; object_type text; name text; kind enum(view,list,segment); definition jsonb; dynamic bool; owner_id UUID"),
    ("crm_task","Task.","id UUID pk; tenant_id UUID; title text; due_at timestamptz; assignee_id UUID; related_type enum; related_id UUID; status enum(open,done,skipped); priority enum(low,med,high)"),
    ("audit_log","Change history.","id UUID pk; tenant_id UUID; actor_id UUID; object_type text; object_id UUID; action text; before jsonb; after jsonb; at timestamptz")
  ],
  "apis":[
    ("GET","/v1/crm/{object}/{id}","Fetch any object with expandable associations.","200"),
    ("POST","/v1/crm/{object}","Create record (validates against properties).","201"),
    ("PATCH","/v1/crm/{object}/{id}","Update (audited).","200"),
    ("POST","/v1/crm/properties","Define a custom property.","201"),
    ("POST","/v1/crm/objects","Define a custom object.","201"),
    ("GET","/v1/crm/{object}/{id}/timeline","Unified AI timeline.","200"),
    ("POST","/v1/crm/deals/{id}:move","Move deal stage (guarded transitions).","200"),
    ("GET","/v1/crm/duplicates","List duplicate candidates.","200"),
    ("POST","/v1/crm/{object}:merge","Merge two records.","200"),
    ("POST","/v1/crm/views","Create view/list/segment (static or dynamic).","201"),
    ("GET","/v1/crm/search","Cross-object search (Search Engine backed).","200")
  ],
  "workflows":["Record CRUD -> property validation -> audit_log -> emit crm.{object}.changed -> Search index update + timeline entry","Deal stage move -> guarded transition -> probability recalced -> forecast refresh -> activity logged","Duplicate detected -> surfaced -> merge -> associations re-pointed, loser soft-deleted, audit"],
  "states":("deal.status/stage",["open(stage 1..n)","won","lost"],"stage transitions constrained by pipeline definition; open->won/lost terminal; reopen creates new deal or audited revert"),
  "events_pub":["crm.contact.changed","crm.deal.changed","deal.stage.changed","crm.merged","crm.task.completed"],
  "events_sub":["intelligence.nba.created","email.event.*","meeting.booked","score.updated","enrichment.entity.updated"],
  "rules":[
    "CRM-001: Every mutation writes an audit_log with before/after.",
    "CRM-002: Custom property keys are immutable once data exists; type changes require migration.",
    "CRM-003: Deal stage transitions must follow the pipeline's allowed graph; illegal moves rejected.",
    "CRM-004: Merge re-points all associations and never deletes activity history.",
    "CRM-005: NBA and AI-timeline entries are system-authored and read-only to users.",
    "CRM-006: Dynamic segments re-evaluate on member field changes; static lists do not."
  ],
  "permissions":[["crm.read","All (row-level by owner/team)"],["crm.write","AE, Manager, Admin"],["crm.schema.manage","Admin/Ops"],["crm.merge","Manager, Admin"],["crm.delete","Admin"]],
  "validations":["property schema enforced on write","unique properties enforced","stage belongs to deal's pipeline"],
  "errors":["422 property validation","409 illegal stage transition","409 merge across tenants","403 row-level denial"],
  "integrations_internal":["Pipeline (19)","Lead Scoring (18)","Marketing/Journey (enrollment source lists)","Analytics/Attribution","Search Engine","Notification"],
  "testing":["Custom object + property lifecycle","Illegal stage move rejected","Merge preserves history","Row-level permission matrix","Timeline ordering across sources"],
  "acceptance":["Create a custom object with fields and CRUD it via API/UI","Deal forecast updates on stage move","Duplicate contacts merge cleanly with full history","Dynamic segment updates as fields change"],
  "edge":["Property type change with existing data -> guided migration, not silent","Circular association (A parent of B parent of A) rejected","Merging owner-conflicting records -> ownership rule applied + audit","10M activities on one account -> timeline paginated & indexed"],
  "checklist":["polymorphic object + property framework","deal/activity/task/note/meeting tables","committee + relationship graph tables","views/lists/segments engine","duplicate + merge engine","audit log","search integration","forecasting hook","AI timeline assembler"]
},

"07_marketing_engine": {
  "num":"07","name":"Marketing Automation Engine (Mailchimp Replica)",
  "folder":"07_Marketing_Automation",
  "replaces":"Mailchimp + Customer.io + Brevo — audience, segmentation, templates, sending, tracking, automation, deliverability.",
  "purpose":"A full native marketing-automation system: audiences & dynamic segments, suppression lists, template/email builder with AI generation, sending with open/click/bounce tracking, A/B & multivariate testing, personalization/merge tags/dynamic blocks, transactional + drip automation, deliverability (IP warming, domain/DKIM/SPF/DMARC, SMTP), scheduling with timezone/send-time optimization — replacing Mailchimp entirely.",
  "scope_in":["Audiences, Lists, Segments (static+dynamic), Suppression lists","Template Builder / Drag-drop Email Builder / AI Email + Subject generator","Preview, Spam checker, Link/Open/Click/Bounce tracking, Heatmaps","A/B + Multivariate testing","Personalization: merge tags, dynamic blocks","Automation: triggers, drip campaigns, transactional emails, webhooks","Deliverability: IP warming, domain mgmt, SMTP, DKIM/SPF/DMARC","Scheduling: timezone send, send-time optimization, AI optimization"],
  "scope_out":["Multi-step cross-channel journeys (Journey Engine 08)","Raw MTA internals delegated to Email Delivery Engine (11)","Landing pages/forms (13)"],
  "personas":[["Marketer","Builds campaigns & audiences"],["Deliverability admin","Manages domains/IPs/warmup"],["AE","Triggers 1:1 sends from CRM"],["System","Fires transactional + automation"]],
  "entities":[
    ("audience","A managed set of contacts.","id UUID pk; tenant_id UUID; name text; kind enum(list,segment); dynamic bool; definition jsonb; size_cache int; updated_at"),
    ("suppression","Global/list suppression entry.","id UUID pk; tenant_id UUID; scope enum(global,list); list_id UUID null; email citext; reason enum(unsub,bounce,complaint,manual,invalid); created_at"),
    ("template","Reusable email template.","id UUID pk; tenant_id UUID; name text; html text; mjml text null; blocks jsonb; merge_tags text[]; created_by; version int"),
    ("email_campaign","A one-to-many send.","id UUID pk; tenant_id UUID; name text; template_id UUID; audience_id UUID; from_domain_id UUID; subject text; preheader text; status enum(draft,scheduled,sending,sent,paused); ab_config jsonb null; schedule jsonb; created_at"),
    ("email_message","Per-recipient message instance.","id UUID pk; campaign_id UUID null; journey_step_id UUID null; contact_id UUID; status enum(queued,sent,delivered,opened,clicked,bounced,complained,unsub); variant text null; provider_msg_id text; sent_at; events jsonb"),
    ("ab_test","Test config & result.","id UUID pk; campaign_id UUID; type enum(ab,multivariate); variants jsonb; metric enum(open,click,reply); winner text null; status enum(running,decided)"),
    ("domain","Sending domain + auth.","id UUID pk; tenant_id UUID; domain text; dkim_status enum; spf_status enum; dmarc_status enum; ip_pool text; warmup_stage int; reputation numeric(4,3)")
  ],
  "apis":[
    ("POST","/v1/mkt/audiences","Create list/segment (dynamic definition).","201"),
    ("GET","/v1/mkt/audiences/{id}/members","Resolve members.","200 paged"),
    ("POST","/v1/mkt/templates","Create/version a template.","201"),
    ("POST","/v1/mkt/templates:generate","AI-generate template/subject from brief.","200"),
    ("POST","/v1/mkt/campaigns","Create campaign (audience+template+schedule+AB).","201"),
    ("POST","/v1/mkt/campaigns/{id}:schedule","Schedule/send (timezone/STO).","200"),
    ("POST","/v1/mkt/campaigns/{id}:spamcheck","Run spam/deliverability preflight.","200"),
    ("GET","/v1/mkt/campaigns/{id}/report","Opens/clicks/bounces/heatmap.","200"),
    ("POST","/v1/mkt/suppressions","Add suppression.","201"),
    ("POST","/v1/mkt/domains","Add sending domain + auth checks.","201")
  ],
  "workflows":["Build audience -> build/generate template -> create campaign -> spamcheck preflight -> schedule (timezone/STO) -> Email Delivery Engine sends -> track events -> report; AB: split, measure metric, auto-pick winner, send winner to remainder","Transactional: event trigger -> template render -> immediate send via delivery engine","Suppression: any unsub/bounce/complaint -> global suppression -> excluded from all future sends"],
  "states":("email_campaign",["draft","scheduled","sending","sent","paused"],"draft->scheduled on schedule; ->sending at fire time; ->sent on completion; ->paused on deliverability trip"),
  "events_pub":["email.campaign.sent","email.event.opened","email.event.clicked","email.event.bounced","email.event.complained","email.unsub"],
  "events_sub":["contact.consent.changed","journey.step.email","deal.stage.changed (transactional)","schedule.tick"],
  "rules":[
    "MKT-001: Every send checks global + list suppression AND contact consent/do_not_contact at send time.",
    "MKT-002: A domain below reputation threshold or mid-warmup throttles volume automatically.",
    "MKT-003: Unsub/bounce/complaint => immediate global suppression + feedback to Lead Scoring (negative).",
    "MKT-004: KSA calendar — no sends Fri/Sat or during Ramadan blackout window.",
    "MKT-005: A/B winner auto-selected only after minimum sample & significance; else manual.",
    "MKT-006: Merge-tag with no value uses fallback; never sends a literal {tag}."
  ],
  "permissions":[["mkt.campaign.manage","Marketer, Admin"],["mkt.send","Marketer, Admin"],["mkt.domain.manage","Deliverability Admin, Admin"],["mkt.audience.manage","Marketer, Ops"]],
  "validations":["audience non-empty at schedule","domain auth (DKIM/SPF) green before send","subject/preheader length limits","AB variants>=2"],
  "errors":["409 send to unauthenticated domain","422 empty audience","423 blocked by KSA calendar","429 warmup throttle"],
  "integrations_internal":["Email Delivery Engine (11)","Contact Engine (consent)","Journey Engine (08)","Analytics/Attribution","AI Personalization (10)","Lead Scoring (feedback)"],
  "testing":["Suppression enforced at send","Warmup throttle curve","AB significance gate","Timezone send correctness","Merge-tag fallback","KSA blackout blocks send"],
  "acceptance":["Send a segmented campaign with tracking & report","AB test auto-picks winner and completes send","Bounce suppresses contact everywhere","DKIM/SPF must be green to send"],
  "edge":["Dynamic segment shrinks to 0 before send -> abort + notify","Contact unsubscribes mid-campaign -> excluded from remaining batches","Shared IP complaint spike -> auto-pause + alert","Duplicate email in two lists -> single send (identity dedup)"],
  "checklist":["audience/segment engine (shared w/ CRM views)","template + block builder + AI generate","campaign + message tables","tracking pixel + click redirect + bounce/complaint webhooks","AB/MVT engine","domain/DKIM/SPF/DMARC + warmup","suppression service","scheduler + STO"]
},
}
