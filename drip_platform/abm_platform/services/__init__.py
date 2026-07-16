"""
abm_platform/services — real implementations for the 16 Phase-9 modules.
Each service is a plain module of functions taking a SQLAlchemy Session,
mirroring sequences/engine.py's style. No service performs any real external
send: email transport defaults to dry_run, LinkedIn execution is a stub gated
by the circuit breaker, and AI generation defaults to an offline template
generator. Compliance gates are enforced inside services, never in routers.
"""
