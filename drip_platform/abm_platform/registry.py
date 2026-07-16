"""
platform/registry.py — the canonical map of the 26 enterprise modules onto this
codebase. Single source of truth for the status API and for humans navigating
the platform/ package. status: LIVE (working) / PARTIAL (real code, incomplete)
/ SCAFFOLD (structure + spec, not yet implemented).
"""
from __future__ import annotations

MODULES: list[dict] = [
    {"num": "01", "key": "intelligence", "name": "Intelligence Engine", "blueprint_folder": "02_Intelligence", "status": "PARTIAL", "replaces": "orchestration / EPIS / reasoning", "wired_to": "scoring, etl.signal_intel"},
    {"num": "02", "key": "signal_detection", "name": "Signal Detection Engine", "blueprint_folder": "03_Signal_Detection", "status": "LIVE", "replaces": "6sense/Bombora + scrapers", "wired_to": "etl.signal_decay, etl.signal_intel, models.Signal"},
    {"num": "03", "key": "enrichment", "name": "Contact & Account Enrichment Engine", "blueprint_folder": "04_Contact_Enrichment", "status": "LIVE", "replaces": "Apollo/Clay/ZoomInfo", "wired_to": "abm_platform.services.enrichment (waterfall, verify_email, detect_duplicates)"},
    {"num": "04", "key": "contact", "name": "Contact Intelligence Engine", "blueprint_folder": "04_Contact_Enrichment", "status": "PARTIAL", "replaces": "HubSpot Contacts", "wired_to": "models.Person, routers.persons"},
    {"num": "05", "key": "account", "name": "Account Engine", "blueprint_folder": "05_Account_Management", "status": "PARTIAL", "replaces": "HubSpot Companies", "wired_to": "models.Organization, models.AccountIntelligence, routers.organizations"},
    {"num": "06", "key": "crm_engine", "name": "CRM Engine (HubSpot Replica)", "blueprint_folder": "06_CRM_Engine", "status": "PARTIAL", "replaces": "HubSpot CRM", "wired_to": "models(Organization,Person,Opportunity,BuyingCommitteeMember,ActivityLog,AuditLog)"},
    {"num": "07", "key": "marketing", "name": "Marketing Automation Engine (Mailchimp Replica)", "blueprint_folder": "07_Marketing_Automation", "status": "LIVE", "replaces": "Mailchimp/Customer.io", "wired_to": "abm_platform.services.marketing (audiences, suppression, campaigns, AB, dry-run send)"},
    {"num": "08", "key": "journey", "name": "Journey / Sequence Engine", "blueprint_folder": "07_Marketing_Automation", "status": "LIVE", "replaces": "HubSpot Workflows/Smartlead", "wired_to": "sequences.engine, sequences.send_window"},
    {"num": "09", "key": "campaign", "name": "Campaign Builder Engine", "blueprint_folder": "07_Marketing_Automation", "status": "LIVE", "replaces": "HubSpot Campaigns", "wired_to": "abm_platform.services.campaign (ABM plays + rollup)"},
    {"num": "10", "key": "ai_personalization", "name": "AI Personalization Engine", "blueprint_folder": "10_AI_Engine", "status": "LIVE", "replaces": "Jasper/Copy.ai + prompt stacks", "wired_to": "abm_platform.services.ai_gen (anonymized generate + QC + c-suite gate)"},
    {"num": "11", "key": "email_delivery", "name": "Email Delivery Engine", "blueprint_folder": "08_Email_Engine", "status": "LIVE", "replaces": "Mandrill/SendGrid MTA", "wired_to": "abm_platform.services.delivery (send queue + normalized events + webhook ingest (dry-run only))"},
    {"num": "12", "key": "linkedin", "name": "LinkedIn Automation Engine", "blueprint_folder": "09_LinkedIn_Engine", "status": "LIVE", "replaces": "Smartlead/Expandi", "wired_to": "abm_platform.services.linkedin (seats + caps + circuit breaker + reply cascade (stub executor))"},
    {"num": "13", "key": "landing_forms", "name": "Landing Page & Forms Engine", "blueprint_folder": "07_Marketing_Automation", "status": "LIVE", "replaces": "HubSpot Landing/Forms", "wired_to": "abm_platform.services.landing (forms + consent upsert + unsubscribe)"},
    {"num": "14", "key": "asset_library", "name": "Asset Library", "blueprint_folder": "07_Marketing_Automation", "status": "LIVE", "replaces": "HubSpot Files/DAM", "wired_to": "abm_platform.services.assets (versioning + HMAC signed links + usage)"},
    {"num": "15", "key": "rules_engine", "name": "Rules Engine", "blueprint_folder": "13_Rules_Engine", "status": "LIVE", "replaces": "HubSpot workflow logic / IFTTT", "wired_to": "abm_platform.services.rules (IF/THEN evaluator + 5 actions + simulate)"},
    {"num": "16", "key": "workflow_engine", "name": "Workflow Engine (n8n-style)", "blueprint_folder": "11_Workflow_Engine", "status": "LIVE", "replaces": "n8n/Zapier/Make", "wired_to": "abm_platform.services.workflow (durable node runs + approval + delay)"},
    {"num": "17", "key": "analytics", "name": "Analytics Engine", "blueprint_folder": "12_Analytics", "status": "LIVE", "replaces": "HubSpot/Mailchimp analytics", "wired_to": "abm_platform.services.analytics (bus-fed metric events + query + funnel)"},
    {"num": "18", "key": "lead_scoring", "name": "Lead & Account Scoring Engine", "blueprint_folder": "05_Account_Management", "status": "LIVE", "replaces": "HubSpot scoring/6sense", "wired_to": "scoring, models.AccountScore, modifiers.json"},
    {"num": "19", "key": "pipeline", "name": "Pipeline Management Engine", "blueprint_folder": "05_Account_Management", "status": "LIVE", "replaces": "HubSpot deal pipelines", "wired_to": "abm_platform.services.pipeline (stages, weighted forecast, health) + models_p10"},
    {"num": "20", "key": "reporting", "name": "Reporting Engine", "blueprint_folder": "12_Analytics", "status": "LIVE", "replaces": "HubSpot reports/dashboards", "wired_to": "abm_platform.services.reporting (reports + exec brief (non-decayed only))"},
    {"num": "21", "key": "notification", "name": "Notification Engine", "blueprint_folder": "14_Admin", "status": "LIVE", "replaces": "HubSpot notifications/Slack", "wired_to": "abm_platform.services.notification (in-app inbox + quiet hours + urgent bypass)"},
    {"num": "22", "key": "attribution", "name": "Attribution Engine", "blueprint_folder": "12_Analytics", "status": "LIVE", "replaces": "HubSpot attribution/Bizible", "wired_to": "abm_platform.services.attribution (5 credit models + campaign rollup)"},
    {"num": "23", "key": "api_gateway", "name": "API Gateway", "blueprint_folder": "15_API", "status": "PARTIAL", "replaces": "Kong/Apigee", "wired_to": "main.app (FastAPI surface)"},
    {"num": "24", "key": "integration_bus", "name": "Integration Layer & Event Bus", "blueprint_folder": "16_UI", "status": "LIVE", "replaces": "internal Kafka/Redis bus", "wired_to": "abm_platform.events"},
    {"num": "25", "key": "admin", "name": "Admin Console & User/Permission Mgmt", "blueprint_folder": "14_Admin", "status": "LIVE", "replaces": "HubSpot settings + RBAC", "wired_to": "abm_platform.services.admin (RBAC deny-by-default + quotas + audit)"},
    {"num": "26", "key": "copilot", "name": "AI Copilot", "blueprint_folder": "10_AI_Engine", "status": "LIVE", "replaces": "HubSpot ChatSpot/Breeze", "wired_to": "abm_platform.services.copilot (intent router: call-list / approach / status)"}
]


def modules() -> list[dict]:
    return list(MODULES)


def by_status() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in MODULES:
        out.setdefault(m["status"], []).append(f'{m["num"]} {m["name"]}')
    return out


def summary() -> dict:
    counts: dict[str, int] = {}
    for m in MODULES:
        counts[m["status"]] = counts.get(m["status"], 0) + 1
    return {"total": len(MODULES), "by_status": counts}
