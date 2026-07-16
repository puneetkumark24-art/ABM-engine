# Phase 8 — Whole 26-Module Enterprise Structure (`abm_platform/`)

Scaffolds the entire enterprise platform (blueprint: `ABM_Enterprise_Platform/`)
**inside** `drip_platform/`, additively, so all 26 modules have a real home in the
codebase and the already-built ones are wired to their existing implementations.
`drip_platform/` remains the single engine (MASTER_CONSOLIDATION_PLAN); this is
organization, not a fork.

## What was added

```
drip_platform/
  abm_platform/                 ← NEW: the 26-module structure
    __init__.py                 imports registry + events (side-effect free)
    events.py                   Module 24 — in-process event bus (LIVE, self-tested)
    registry.py                 canonical 26-module map + status API data
    README.md                   the whole map, LIVE/PARTIAL/SCAFFOLD
    m01_intelligence/ … m26_copilot/
        __init__.py
        SPEC.md                 pointer to ABM_Enterprise_Platform/<folder>/
        service.py              stable import point: wired impl OR NotImplementedError stub
  routers/platform_status.py    ← NEW: GET /platform/modules, GET /platform/health
  main.py                       ← edited: include_router(platform_status.router)
  platform/__init__.py          ← REPLACED with a stdlib shim (see note below)
```

## Status of the 26 modules (from the live registry)

- **LIVE (4):** 02 Signal Detection, 08 Journey/Sequence, 18 Lead & Account Scoring,
  24 Integration Layer & Event Bus.
- **PARTIAL (6):** 01 Intelligence, 04 Contact, 05 Account, 06 CRM Engine,
  19 Pipeline, 23 API Gateway.
- **SCAFFOLD (16):** 03 Enrichment, 07 Marketing, 09 Campaign, 10 AI Personalization,
  11 Email Delivery, 12 LinkedIn, 13 Landing/Forms, 14 Asset Library, 15 Rules,
  16 Workflow, 17 Analytics, 20 Reporting, 21 Notification, 22 Attribution,
  25 Admin, 26 Copilot.

Each LIVE/PARTIAL module's `service.py` names the real code it is wired to
(e.g. m08 → `sequences.engine`; m18 → `scoring` + `modifiers.json`;
m02 → `etl.signal_decay`/`signal_intel`; m06 → the CRM-shaped `models`).

## The `platform/` → `abm_platform/` note (important)

A first pass created the package as `platform/`, which **collides with the Python
standard-library `platform` module** and broke stdlib imports (even `uuid` calls
`platform.system()`). The real structure was moved to **`abm_platform/`** (safe
name). The old `platform/` directory could not be deleted from this session, so its
`__init__.py` was replaced with a transparent shim that re-exports the genuine
stdlib `platform` module — `import platform` works normally again. The leftover
`platform/mNN_*` files are inert; you can delete the `platform/` folder on your
machine at your convenience:

```
rmdir /s /q "C:\Users\Puneet\Desktop\ABM business logic\drip_platform\platform"
```

## Verified (this session, SQLite / import-level)

- `abm_platform/events.py` self-test passes (publish → 2 deliveries; same event id
  redelivered → 0; handler isolation).
- `abm_platform.registry.summary()` → `{total: 26, LIVE:4, PARTIAL:6, SCAFFOLD:16}`.
- All 26 module packages **and** their `service.py` import cleanly (26/26).
- All 6 API routers import together; `GET /platform/modules` and `/platform/health`
  return the live registry via `TestClient`.
- `import platform; platform.system()` works (stdlib shim confirmed).

## How to extend a module

Pick a SCAFFOLD module → open its blueprint spec at
`ABM_Enterprise_Platform/<folder>/` → implement against its checklist + acceptance
criteria → flip its `status` in `abm_platform/registry.py` to PARTIAL/LIVE → wire
`service.py` to the real code. Exactly how Module 08 (Journey/Sequence) was built
in Phase 7.

## Nothing changed

No existing table, column, model, router behaviour, or `decimal_abm` code was
modified. `abm_platform/` is import-side-effect-free; the only runtime addition is
two read-only `/platform/*` endpoints.
