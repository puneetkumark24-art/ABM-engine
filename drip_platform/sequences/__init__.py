"""
drip_platform/sequences
────────────────────────
Module 08 — Sequence / Journey Engine (Enterprise Blueprint), ported from
decimal_abm/abm_engine/workflow/ onto DRIP's ORM Person/Organization model.

- send_window.py   KSA business-hours + weekend/blackout send gate (T-TIME-2).
                   Pure function of the clock; no schema dependency. Ported
                   from decimal_abm unchanged except swapping loguru for the
                   stdlib logging module (loguru isn't a DRIP dependency).
- engine.py        ORM policy layer the API/scheduler calls:
                   ensure_default_sequence, enroll_person, backfill_enrollments,
                   get_due, advance, pause, pause_on_reply (account-centric).

ADDITIVE ONLY — nothing here mutates existing tables. Compliance gates
(do_not_contact / consent_status != 'denied' / replied / is_active) and the
account-centric pause rule (ACC-001) are enforced here, matching the Bible and
the decimal_abm Phase 1 behaviour so turning this on never contacts anyone the
old engine wouldn't have.
"""
