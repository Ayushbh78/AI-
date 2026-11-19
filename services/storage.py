"""Storage for courses, study material, users and the login-cookie key.

Two backends, same functions:
  * DATABASE_URL set (Render + Supabase)  -> Postgres tables (see db.py). Survives deploys and restarts.
  * DATABASE_URL not set (running locally) -> JSON files in the data folder, exactly as before.
"""
import contextlib
import copy
import json
import os
import re
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .config import COURSES_DIR, DATA_DIR, MATERIALS_DIR

USERS_FILE = DATA_DIR / "users.json"
SECRET_FILE = DATA_DIR / ".secret_key"
DEFAULT_USERS = ("bijay", "ayush", "pragyansh", "pushpendra", "vaishnavi")
DEFAULT_PASSWORD = "12345"

_lock = threading.RLock()
_key_locks = {}
_key_locks_guard = threading.Lock()


def _io_lock():
    """JSON files on disk need our lock; the database does not (holding a lock during a network call made requests queue up)."""
    return contextlib.nullcontext() if db.enabled() else _lock


def _key_lock(name):
    """One lock per document: two people never wait for each other, two edits of the same document never overwrite each other."""
    with _key_locks_guard:
        return _key_locks.setdefault(name, threading.RLock())


# ---- tiny in-memory cache for things every page asks for (user record, profile). Cleared whenever we write them. ----
_cache = {}
_NOTHING = "\0nothing"   # marker: "this document does not exist (yet)"
_CACHE_SECONDS = {"user": 60, "profile": 30, "bookmeta": 30, "library": 20, "activity": 20}


def _cache_get(name, ttl):
    hit = _cache.get(name)
    if hit and time.time() < hit[0]:
        return True, copy.deepcopy(hit[1])
    return False, None


def _cache_put(name, ttl, value):
    if len(_cache) > 2000:
        _cache.clear()
    _cache[name] = (time.time() + ttl, copy.deepcopy(value))


def _cache_drop(name):
    _cache.pop(name, None)


class CourseNotFound(Exception):
    pass


class UserExists(Exception):
    pass


def _ensure_dirs():
    COURSES_DIR.mkdir(parents=True, exist_ok=True)
    MATERIALS_DIR.mkdir(parents=True, exist_ok=True)


def _write_json(path, data):
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _safe(cid):
    return "".join(ch for ch in str(cid) if ch.isalnum())


def _course_path(cid):
    return COURSES_DIR / f"{_safe(cid)}.json"


def _materials_path(cid):
    return MATERIALS_DIR / f"{_safe(cid)}.json"


def list_courses(owner=None, include_unowned=False):
    """All courses, or (with owner) only that person's. With the database the filtering happens there."""
    if db.enabled():
        return db.list_courses(owner, include_unowned)
    _ensure_dirs()
    courses = []
    with _lock:
        for path in COURSES_DIR.glob("*.json"):
            course = _read_json(path)
            if course:
                courses.append(course)
    if owner is not None:
        courses = [c for c in courses if c.get("owner") == owner or (include_unowned and not c.get("owner"))]
    courses.sort(key=lambda c: c.get("created", ""), reverse=True)
    return courses


def load_course(cid):
    if db.enabled():
        course = db.get_course(_safe(cid))
    else:
        _ensure_dirs()
        with _lock:
            course = _read_json(_course_path(cid))
    if course is None:
        raise CourseNotFound(cid)
    return course


def save_course(course):
    if db.enabled():
        db.put_course(_safe(course["id"]), course)
        return
    _ensure_dirs()
    with _lock:
        _write_json(_course_path(course["id"]), course)


@contextmanager
def update(cid):
    """Load a course, let the caller change it, save it. Nothing is saved if the caller raises."""
    with _key_lock("course:" + str(cid)):
        course = load_course(cid)
        yield course
        save_course(course)


# ---------- generic documents: profile, study records, library, cached suggestions ----------

def _doc_key(key):
    """Reversible file-safe name, so different keys can never share a file."""
    return "".join(ch if ch.isascii() and (ch.isalnum() or ch in "_-") else "_%x_" % ord(ch) for ch in str(key))[:150]


def _doc_path(kind, key):
    return DATA_DIR / "docs" / _safe(kind) / f"{_doc_key(key)}.json"


def _get_doc_fresh(kind, key):
    with _io_lock():
        if db.enabled():
            return db.get_doc(_safe(kind), str(key))
        return _read_json(_doc_path(kind, key))


def get_doc(kind, key, default=None):
    ttl = _CACHE_SECONDS.get(kind)
    name = f"doc:{kind}:{key}"
    if ttl:
        found, data = _cache_get(name, ttl)
        if found:
            return default if data == _NOTHING else data
    data = _get_doc_fresh(kind, key)
    if ttl:
        _cache_put(name, ttl, _NOTHING if data is None else data)
    return default if data is None else data


def put_doc(kind, key, data):
    _cache_drop(f"doc:{kind}:{key}")
    with _io_lock():
        if db.enabled():
            db.put_doc(_safe(kind), str(key), data)
            return
        path = _doc_path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        _write_json(path, data)


@contextmanager
def update_doc(kind, key, default_factory=dict):
    """Load a document (or a fresh default), let the caller change it, save it. Nothing is saved if the caller raises."""
    with _key_lock(f"doc:{kind}:{key}"):
        data = _get_doc_fresh(kind, key)       # always the newest copy, never the cached one
        if data is None:
            data = default_factory()
        yield data
        put_doc(kind, key, data)


def delete_course(cid):
    if db.enabled():
        db.delete_course(_safe(cid))
        return
    with _lock:
        for path in (_course_path(cid), _materials_path(cid)):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def load_materials(cid):
    if db.enabled():
        return db.get_materials(_safe(cid)) or []
    _ensure_dirs()
    with _lock:
        return _read_json(_materials_path(cid)) or []


def save_materials(cid, materials):
    if db.enabled():
        db.put_materials(_safe(cid), materials)
        return
    _ensure_dirs()
    with _lock:
        _write_json(_materials_path(cid), materials)


# ---------- users and login ----------

def secret_key():
    """Key for signing the login cookie, so logins survive restarts.

    1. SECRET_KEY environment variable (set this on Render).
    2. Otherwise a random key created once and kept in the database (or in the data folder when running locally).
    """
    env_key = os.environ.get("SECRET_KEY", "").strip()
    if env_key:
        return env_key
    if db.enabled():
        with _lock:
            key = db.get_secret("secret_key")
            if not key:
                key = db.put_secret_once("secret_key", secrets.token_hex(32))
            return key
    _ensure_dirs()
    with _lock:
        try:
            key = SECRET_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            key = ""
        if not key:
            key = secrets.token_hex(32)
            SECRET_FILE.write_text(key, encoding="utf-8")
        return key


def _load_users():
    return _read_json(USERS_FILE) or {}


def _user_record(key):
    if db.enabled():
        return db.get_user(key)
    return _load_users().get(key)


def _public(username, record):
    return {"username": username, "name": record.get("name") or username.capitalize(), "email": record.get("email") or ""}


def ensure_default_users():
    """Make sure the three ready-made accounts exist (password 12345). Existing accounts are left alone."""
    if db.enabled():
        with _lock:
            for name in DEFAULT_USERS:
                db.add_user_if_missing(name, {"name": name.capitalize(),
                                              "password": generate_password_hash(DEFAULT_PASSWORD),
                                              "created": datetime.now().isoformat(timespec="seconds")})
        return
    _ensure_dirs()
    with _lock:
        users = _load_users()
        changed = False
        for name in DEFAULT_USERS:
            if name not in users:
                users[name] = {"name": name.capitalize(), "password": generate_password_hash(DEFAULT_PASSWORD),
                               "created": datetime.now().isoformat(timespec="seconds")}
                changed = True
        if changed:
            _write_json(USERS_FILE, users)


def get_user(username):
    """Called on every request, so the answer is remembered for a minute (and forgotten when the account changes)."""
    key = str(username or "").strip().lower()
    if not key:
        return None
    found, cached = _cache_get("user:" + key, 60)
    if found:
        return cached
    with _io_lock():
        record = _user_record(key)
    user = _public(key, record) if record else None
    if user:
        _cache_put("user:" + key, 60, user)
    return user


def _email_key(email):
    return str(email or "").strip().lower()


def make_username(email):
    """Internal account id made from the e-mail (students never see or type it). Always unique."""
    base = re.sub(r"[^a-z0-9_.]", "", _email_key(email).split("@")[0])[:14]
    if len(base) < 3:
        base = (base + "student")[:14]
    candidate = base
    while _user_record(candidate):
        candidate = f"{base}{secrets.randbelow(9000) + 1000}"
    return candidate


def find_username_by_email(email):
    """Username that owns this (verified) email, or None. Old accounts have no email."""
    key = _email_key(email)
    if not key:
        return None
    return get_doc("emailidx", key, None)


def create_user(username, password=None, name="", email="", password_hash=None):
    """Create an account. Pass the plain password, or an already hashed one (signup keeps only the hash while waiting for the code)."""
    key = str(username).strip().lower()
    email = _email_key(email)
    record = {"name": (name or "").strip()[:40] or key.capitalize(),
              "password": password_hash or generate_password_hash(password),
              "created": datetime.now().isoformat(timespec="seconds")}
    if email:
        record["email"] = email
    with _lock:
        if email and find_username_by_email(email):
            raise UserExists(email)
        if db.enabled():
            if not db.add_user_if_missing(key, record):
                raise UserExists(key)
        else:
            _ensure_dirs()
            users = _load_users()
            if key in users:
                raise UserExists(key)
            users[key] = record
            _write_json(USERS_FILE, users)
        if email:
            put_doc("emailidx", email, key)
        _cache_drop("user:" + key)
    return _public(key, record)


def set_password(username, password):
    key = str(username or "").strip().lower()
    with _lock:
        if db.enabled():
            record = db.get_user(key)
            if not record:
                return False
            record["password"] = generate_password_hash(password)
            db.update_user(key, record)
            _cache_drop("user:" + key)
            return True
        users = _load_users()
        if key not in users:
            return False
        users[key]["password"] = generate_password_hash(password)
        _write_json(USERS_FILE, users)
        _cache_drop("user:" + key)
        return True


def check_login(username, password):
    """`username` may be the username or the email address."""
    key = str(username or "").strip().lower()
    if "@" in key:
        key = find_username_by_email(key) or ""
    with _io_lock():
        record = _user_record(key)
    if record and check_password_hash(record["password"], str(password or "")):
        return _public(key, record)
    return None
