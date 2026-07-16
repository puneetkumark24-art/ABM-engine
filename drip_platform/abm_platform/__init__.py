"""
platform/ — the enterprise ABM platform, 26 modules mapped onto drip_platform.

This is the additive structural home for the full platform (blueprint:
ABM_Enterprise_Platform/). Each mNN_* sub-package is one module. The event bus
(Module 24, abm_platform.events) and the registry (platform.registry) are live.
Existing DRIP code (models, scoring, sequences, routers, etl) is unchanged and
is *wired into* the relevant modules rather than duplicated.

Nothing here mutates existing tables or behaviour — importing `platform` is
side-effect free.
"""
from . import registry, events   # noqa: F401
