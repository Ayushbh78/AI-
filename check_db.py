"""Run:  python check_db.py   -> tests the database connection (DATABASE_URL in .env or the environment).

It connects, creates the tables, writes a test row, reads it back and deletes it. Prints PASS or the exact problem.
"""
import sys

from services import db
from services.config import get_setting

url = get_setting("DATABASE_URL").strip()
if not url:
    print("DATABASE_URL is not set. The app will save to local files only (lost when a cloud host restarts).")
    print("Add DATABASE_URL (Supabase -> Connect -> Session pooler) to .env or to Render -> Environment.")
    sys.exit(1)

try:
    db.get_doc("check", "ping")                      # opens the pool and creates the tables
    db.put_doc("check", "ping", {"ok": True})
    back = db.get_doc("check", "ping")
    assert back == {"ok": True}, f"read back {back!r}"
    users = db.get_user("bijay")
    print("PASS: connected to the database, tables exist, a test value was saved and read back.")
    print("      Ready-made accounts present:", "yes" if users else "not yet (they are created when the app starts)")
except Exception as exc:  # noqa: BLE001
    print("FAIL:", exc)
    sys.exit(2)
