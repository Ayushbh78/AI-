"""Postgres (Supabase) backend used by storage.py when DATABASE_URL is set.

Tables hold each course / material / user as one JSON document, so the app code does not change.
The tables are created automatically on first use (the same SQL is in supabase_schema.sql).
"""
import sys
import threading
import time
from urllib.parse import urlparse

from .config import get_setting

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses   (id TEXT PRIMARY KEY, data JSONB NOT NULL, created TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS materials (course_id TEXT PRIMARY KEY, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS users     (username TEXT PRIMARY KEY, data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS app_secrets (name TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS docs      (kind TEXT NOT NULL, key TEXT NOT NULL, data JSONB NOT NULL, PRIMARY KEY (kind, key));
CREATE INDEX IF NOT EXISTS courses_owner_idx ON courses ((data->>'owner'));
ALTER TABLE docs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE courses      ENABLE ROW LEVEL SECURITY;
ALTER TABLE materials    ENABLE ROW LEVEL SECURITY;
ALTER TABLE users        ENABLE ROW LEVEL SECURITY;
ALTER TABLE app_secrets  ENABLE ROW LEVEL SECURITY;
"""

_pool = None
_pool_lock = threading.Lock()


def _url():
    return get_setting("DATABASE_URL").strip().strip('"').strip("'")


def enabled():
    return bool(_url())


def connected():
    """True once the connection pool is open and the tables exist."""
    return _pool is not None


def _host(url):
    try:
        return urlparse(url).hostname or ""
    except ValueError:      # e.g. a pasted [YOUR-PASSWORD] placeholder confuses the parser
        return ""


def _hint(url):
    host = _host(url)
    if "YOUR-PASSWORD" in url or "YOURPASSWORD" in url:
        return "DATABASE_URL still contains [YOUR-PASSWORD]. Put your real database password there."
    if host.startswith("db.") and host.endswith(".supabase.co"):
        return ("DATABASE_URL uses Supabase's direct host, which is IPv6-only and cannot be reached from Render. "
                "In Supabase click Connect -> 'Session pooler' and use that connection string instead.")
    return ""


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError("DATABASE_URL is set but psycopg is not installed. "
                               "Run: pip install -r requirements.txt") from exc
        url = _url()
        hint = _hint(url)
        if hint:
            raise RuntimeError(hint)
        kwargs = {"autocommit": True, "prepare_threshold": None, "connect_timeout": 15,  # None: works with poolers
                  "keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 3}
        if _host(url) not in ("localhost", "127.0.0.1", "::1") and "sslmode" not in url:
            kwargs["sslmode"] = "require"
        # No "check before every use" (it was an extra round trip to the database for every single query, which made
        # each page twice as slow). A connection that went stale is caught by _run below and replaced.
        pool = ConnectionPool(url, min_size=2, max_size=int(get_setting("DB_POOL_MAX", "6")), kwargs=kwargs,
                              max_idle=600, max_lifetime=1800, open=False, name="ai-university")
        pool.open()
        last = None
        for attempt in range(4):   # the database may still be waking up
            try:
                with pool.connection() as conn:
                    conn.execute(SCHEMA)
                last = None
                break
            except Exception as exc:  # noqa: BLE001 - report below
                last = exc
                time.sleep(2 * (attempt + 1))
        if last is not None:
            pool.close()
            raise RuntimeError(f"Could not connect to the database: {last}. {_hint(url)}".strip()) from last
        print("Database: connected to Postgres (Supabase). Data is saved there.", file=sys.stderr, flush=True)
        _pool = pool
        return _pool


def _run(fn):
    """Run fn(conn). If a connection went stale, drop the dead ones and try again (up to 3 times)."""
    from psycopg import OperationalError
    pool = _get_pool()
    for attempt in (1, 2, 3):
        try:
            with pool.connection() as conn:
                return fn(conn)
        except OperationalError:
            if attempt == 3:
                raise
            try:
                pool.check()     # throws away broken connections so the retry gets a fresh one
            except Exception:    # noqa: BLE001
                pass


def _json(value):
    from psycopg.types.json import Jsonb
    return Jsonb(value)


# ---------- courses ----------

def list_courses(owner=None, include_unowned=False):
    """All courses, or only one person's (filtered in the database, so a page does not download everybody's courses)."""
    def go(conn):
        if owner is None:
            rows = conn.execute("SELECT data FROM courses ORDER BY created DESC").fetchall()
        elif include_unowned:
            rows = conn.execute("SELECT data FROM courses WHERE data->>'owner' = %s OR data->>'owner' IS NULL "
                                "OR data->>'owner' = '' ORDER BY created DESC", (owner,)).fetchall()
        else:
            rows = conn.execute("SELECT data FROM courses WHERE data->>'owner' = %s ORDER BY created DESC", (owner,)).fetchall()
        return [r[0] for r in rows]
    return _run(go)


def get_course(cid):
    def go(conn):
        row = conn.execute("SELECT data FROM courses WHERE id = %s", (cid,)).fetchone()
        return row[0] if row else None
    return _run(go)


def put_course(cid, course):
    def go(conn):
        conn.execute("INSERT INTO courses (id, data, created) VALUES (%s, %s, %s) "
                     "ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data, created = EXCLUDED.created",
                     (cid, _json(course), str(course.get("created", ""))))
    _run(go)


def delete_course(cid):
    def go(conn):
        with conn.transaction():
            conn.execute("DELETE FROM courses WHERE id = %s", (cid,))
            conn.execute("DELETE FROM materials WHERE course_id = %s", (cid,))
    _run(go)


# ---------- materials ----------

def get_materials(cid):
    def go(conn):
        row = conn.execute("SELECT data FROM materials WHERE course_id = %s", (cid,)).fetchone()
        return row[0] if row else None
    return _run(go)


def put_materials(cid, materials):
    def go(conn):
        conn.execute("INSERT INTO materials (course_id, data) VALUES (%s, %s) "
                     "ON CONFLICT (course_id) DO UPDATE SET data = EXCLUDED.data", (cid, _json(materials)))
    _run(go)


# ---------- users ----------

def get_user(username):
    def go(conn):
        row = conn.execute("SELECT data FROM users WHERE username = %s", (username,)).fetchone()
        return row[0] if row else None
    return _run(go)


def add_user_if_missing(username, record):
    """True if the user was created, False if the name was already taken. Existing users are never changed."""
    def go(conn):
        cur = conn.execute("INSERT INTO users (username, data) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING",
                           (username, _json(record)))
        return cur.rowcount == 1
    return _run(go)


def update_user(username, record):
    """Replace an existing user's record (used for password reset)."""
    def go(conn):
        conn.execute("UPDATE users SET data = %s WHERE username = %s", (_json(record), username))
    return _run(go)


# ---------- secrets ----------

def get_secret(name):
    def go(conn):
        row = conn.execute("SELECT value FROM app_secrets WHERE name = %s", (name,)).fetchone()
        return row[0] if row else None
    return _run(go)


def put_secret_once(name, value):
    """Store value unless one already exists; return whichever value is stored (safe with several workers)."""
    def go(conn):
        conn.execute("INSERT INTO app_secrets (name, value) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                     (name, value))
        return conn.execute("SELECT value FROM app_secrets WHERE name = %s", (name,)).fetchone()[0]
    return _run(go)


# ---------- generic documents (profile, study records, library, cached suggestions) ----------

def get_doc(kind, key):
    def go(conn):
        row = conn.execute("SELECT data FROM docs WHERE kind = %s AND key = %s", (kind, key)).fetchone()
        return row[0] if row else None
    return _run(go)


def put_doc(kind, key, data):
    def go(conn):
        conn.execute("INSERT INTO docs (kind, key, data) VALUES (%s, %s, %s) "
                     "ON CONFLICT (kind, key) DO UPDATE SET data = EXCLUDED.data", (kind, key, _json(data)))
    _run(go)
