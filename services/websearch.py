"""Web lookup through Tavily (free plan: 1,000 searches a month, no card needed).

Searches preferred study sites first (GeeksforGeeks etc.); if they have nothing, searches the whole
web. Results are cached on disk so a repeated question costs no credit and answers instantly.
Never raises: when anything goes wrong it returns [] and the app carries on without web sources.
"""
import json
import threading
import time

import requests

from .config import DATA_DIR, get_setting, has_search_key

URL = "https://api.tavily.com/search"
DEFAULT_DOMAINS = ("geeksforgeeks.org,tutorialspoint.com,w3schools.com,programiz.com,javatpoint.com,"
                   "khanacademy.org,wikipedia.org,mathworld.wolfram.com")
CACHE_FILE = DATA_DIR / "web_cache.json"
CACHE_SECONDS = 7 * 24 * 3600
MAX_CHARS = 1800            # text kept per page
_lock = threading.Lock()
_cache = None


def _load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def _save():
    try:
        CACHE_FILE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _call(query, domains, key, timeout):
    body = {"query": query, "search_depth": "basic", "max_results": 6, "include_raw_content": "text"}
    if domains:
        body["include_domains"] = domains
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    r = requests.post(URL, json=body, headers=headers, timeout=(5, timeout))
    if r.status_code == 400 and "include_raw_content" in body:   # older API: retry without the extra field
        body.pop("include_raw_content")
        r = requests.post(URL, json=body, headers=headers, timeout=(5, timeout))
    r.raise_for_status()
    return r.json().get("results") or []


def search(query, timeout=8, general=False, max_chars=MAX_CHARS, limit=3):
    """Return up to 3 pages as [{"title", "url", "text"}], best first. [] if unavailable.

    general=True searches the whole web (syllabi, books, exam patterns) instead of preferring study sites.
    """
    if not has_search_key():
        return []
    query = " ".join(str(query).split())[:300]
    cache_key = query.lower() + ("|general" if general else "") + (f"|{max_chars}|{limit}" if (max_chars, limit) != (MAX_CHARS, 3) else "")
    with _lock:
        hit = _load().get(cache_key)
    if hit and time.time() - hit["t"] < CACHE_SECONDS:
        return hit["pages"]

    key = get_setting("TAVILY_API_KEY")
    domains = [] if general else [d.strip() for d in get_setting("WEB_DOMAINS", DEFAULT_DOMAINS).split(",") if d.strip()]
    try:
        results = _call(query, domains, key, timeout) if domains else []
        if not results:
            results = _call(query, None, key, timeout)
    except (requests.RequestException, ValueError) as err:
        print("[web] search failed:", err.__class__.__name__, flush=True)
        return []

    pages = []
    for item in results:
        text = (item.get("raw_content") or item.get("content") or "").strip()
        if len(text) < 80 and item.get("content"):
            text = item["content"].strip()
        if text and item.get("url"):
            pages.append({"title": (item.get("title") or item["url"])[:120], "url": item["url"],
                          "text": " ".join(text.split())[:max_chars]})
        if len(pages) == limit:
            break
    print(f"[web] '{query[:60]}' -> {len(pages)} page(s)", flush=True)
    if pages:
        with _lock:
            _load()[cache_key] = {"t": time.time(), "pages": pages}
            _save()
    return pages


def as_context(pages):
    """Numbered web excerpts to put in a prompt."""
    return "\n\n".join(f"[Web {i}: {p['title']}]\n{p['text']}" for i, p in enumerate(pages, start=1))
