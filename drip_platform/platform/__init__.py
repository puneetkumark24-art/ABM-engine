"""
NOTE: this directory is named `platform`, which collides with the Python
standard-library module of the same name. The real ABM enterprise 26-module
structure now lives in **`abm_platform/`** (safe name) — NOT here.

This __init__ exists only to prevent the name collision from breaking stdlib
imports (uuid, subprocess, etc. all call platform.system()). It transparently
re-exports the genuine standard-library `platform` module, so `import platform`
keeps working normally everywhere. The sibling files in this folder are inert.
"""
import importlib.util as _ilu
import os as _os
import sysconfig as _sc

_stdlib_platform = _os.path.join(_sc.get_paths()["stdlib"], "platform.py")
_spec = _ilu.spec_from_file_location("_real_stdlib_platform", _stdlib_platform)
_real = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_real)

for _k in dir(_real):
    if not _k.startswith("__"):
        globals()[_k] = getattr(_real, _k)
