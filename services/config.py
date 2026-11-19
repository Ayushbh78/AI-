"""Settings: read from the .env file in the project folder (or the environment)."""
import os
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
COURSES_DIR = DATA_DIR / "courses"
MATERIALS_DIR = DATA_DIR / "materials"

PLACEHOLDER = "PASTE_YOUR_KEY_HERE"

# Dates (study schedule, streaks) follow Indian time unless TZ is set, also on a cloud server that runs in UTC.
os.environ.setdefault("TZ", "Asia/Kolkata")
if hasattr(time, "tzset"):
    time.tzset()


_env_cache = {"stamp": None, "values": {}}


def _read_env_file():
    """The .env file is parsed again only when it changed (this is called many times for every page)."""
    env_file = BASE_DIR / ".env"
    try:
        info = env_file.stat()
        stamp = (info.st_mtime_ns, info.st_size)
    except OSError:
        _env_cache.update(stamp=None, values={})
        return _env_cache["values"]
    if stamp == _env_cache["stamp"]:
        return _env_cache["values"]
    values = {}
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    _env_cache.update(stamp=stamp, values=values)
    return values


def get_setting(name, default=""):
    """The .env file is read on every call, so a new key works without a restart."""
    return _read_env_file().get(name) or os.environ.get(name) or default


def has_api_key():
    key = get_setting("GROQ_API_KEY")
    return bool(key) and key != PLACEHOLDER


def has_search_key():
    """Optional Tavily key: lets the app look topics up on the web (GeeksforGeeks etc.)."""
    key = get_setting("TAVILY_API_KEY")
    return bool(key) and key != PLACEHOLDER
