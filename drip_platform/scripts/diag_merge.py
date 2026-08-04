"""diag_merge.py -- ONE-OFF DIAGNOSTIC. Read-only except for one print of the
raw draft row already in your DB. Explains exactly which files/values are in
play so we can see why the merge-tag fix isn't showing up in your output.

Run:
    python scripts\\diag_merge.py
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

print("=== environment ===")
print("python executable:", sys.executable)
print("python version:", sys.version)
print("ROOT:", ROOT)

from database import SessionLocal  # noqa: E402
import models  # noqa: E402
from abm_platform.services import orchestrator, marketing_ext, ai_gen  # noqa: E402

print("\n=== module file locations (should all be under drip_platform\\) ===")
print("orchestrator loaded from:", orchestrator.__file__)
print("marketing_ext loaded from:", marketing_ext.__file__)
print("ai_gen loaded from:", ai_gen.__file__)

print("\n=== does orchestrator.py reference marketing_ext? ===")
import inspect
src = inspect.getsource(orchestrator.run_tick)
print("'render_merge' in run_tick source:", "render_merge" in src)
print("'marketing_ext' in run_tick source:", "marketing_ext" in src)

print("\n=== render_merge() direct test ===")
db = SessionLocal()
try:
    person = (db.query(models.Person)
              .filter(models.Person.full_name.ilike("%Jaffal%"))
              .first())
    if person is None:
        print("Could not find Abdulhakim Bin Jaffal by name -- picking most recent Draft's person instead.")
        d = db.query(models.Draft).order_by(models.Draft.created_at.desc()).first()
        person = db.get(models.Person, d.person_id) if d else None

    print("person found:", person.id if person else None,
          "full_name:", repr(person.full_name) if person else None)

    test_text = "Dear {name},\n\nBest regards,\n{sender}"
    rendered = marketing_ext.render_merge(db, test_text, person)
    print("render_merge('%s') ->" % test_text.replace(chr(10), "\\n"), repr(rendered))

    print("\n=== most recent Draft row for this person ===")
    d = (db.query(models.Draft).filter_by(person_id=person.id)
         .order_by(models.Draft.created_at.desc()).first())
    if d:
        print("draft.id:", d.id, "created via source:", d.source, "status:", d.status)
        print("draft.body repr (first 200 chars):", repr(d.body[:200]))
    else:
        print("No draft row found for this person at all.")
finally:
    db.close()
