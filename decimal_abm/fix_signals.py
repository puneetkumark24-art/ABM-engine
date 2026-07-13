"""Quick fix: strips HTML from existing signal summaries in the database."""
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "abm_engine.db"
conn = sqlite3.connect(str(DB_PATH))

signals = conn.execute("SELECT id, summary, title FROM signals").fetchall()
fixed = 0
for sid, summary, title in signals:
    if summary and ('<' in summary or '&nbsp;' in summary):
        clean = re.sub(r'<[^>]+>', '', summary)
        clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&')
        clean = clean.replace('&lt;', '<').replace('&gt;', '>').strip()
        conn.execute("UPDATE signals SET summary = ? WHERE id = ?", (clean, sid))
        fixed += 1
    if title and ('<' in title or '&nbsp;' in title):
        clean_t = re.sub(r'<[^>]+>', '', title)
        clean_t = clean_t.replace('&nbsp;', ' ').replace('&amp;', '&').strip()
        conn.execute("UPDATE signals SET title = ? WHERE id = ?", (clean_t, sid))

conn.commit()
conn.close()
print(f"Fixed {fixed} signals. Refresh the Intelligence tab.")
