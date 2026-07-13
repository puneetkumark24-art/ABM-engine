"""
abm_engine/workflow
────────────────────
Phase 1 additions: the "drip" / sequencing engine.

- send_window.py     KSA business-hours + weekend/holiday send gate (T-TIME-2)
- sequence_db.py     Additive tables: sequence_definitions / sequence_steps /
                     sequence_enrollments — data-driven cadence instead of the
                     hardcoded "5 touches, 3-day gap" that used to live in
                     database/db.py.
- sequence_engine.py High-level API used by core/orchestrator.py:
                     ensure_default_sequence(), backfill_enrollments(),
                     get_contacts_due(), advance(), pause().

Nothing here changes existing tables. Everything is additive and defaults to
reproducing the exact cadence the engine already used, so turning this on
does not change who gets contacted or when unless a sequence is explicitly
edited.
"""
