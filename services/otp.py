"""One-time e-mail codes (6 digits) for sign-up, forgot password and code login.

Safety rules: the code is stored only as a keyed hash, lasts 10 minutes, allows 5 wrong tries, can be re-sent
after 60 seconds, and at most 5 codes per hour per e-mail. A per-IP limit stops bulk sending.
Pending codes live in storage.py, so they work with Supabase and on your own PC.
"""
import hashlib
import hmac
import secrets
import time

from . import storage

TTL = 10 * 60
MAX_TRIES = 5
COOLDOWN = 60
MAX_PER_HOUR = 5
IP_MAX_PER_HOUR = 20

_ip_hits = {}


class OtpError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def ip_guard(ip):
    now = time.time()
    hits = [t for t in _ip_hits.get(ip, []) if now - t < 3600]
    if len(hits) >= IP_MAX_PER_HOUR:
        raise OtpError("Too many requests from this device. Please try again in an hour.", 429)
    hits.append(now)
    _ip_hits[ip] = hits
    if len(_ip_hits) > 5000:   # keep memory small
        for k in list(_ip_hits)[:2500]:
            _ip_hits.pop(k, None)


def _key(purpose, email):
    return f"{purpose}:{email}"


def _hash(purpose, email, code):
    return hmac.new(storage.secret_key().encode(), f"{purpose}|{email}|{code}".encode(), hashlib.sha256).hexdigest()


def issue(purpose, email, payload=None):
    """Make a new code. Returns the plain code (to be e-mailed). Enforces cooldown and hourly limit."""
    now = time.time()
    with storage.update_doc("otp", _key(purpose, email)) as doc:
        sent = [t for t in doc.get("sent", []) if now - t < 3600]
        if sent and now - sent[-1] < COOLDOWN:
            raise OtpError(f"Please wait {int(COOLDOWN - (now - sent[-1])) + 1} seconds before asking for a new code.", 429)
        if len(sent) >= MAX_PER_HOUR:
            raise OtpError("Too many codes were requested. Please try again in an hour.", 429)
        code = f"{secrets.randbelow(1000000):06d}"
        doc.update(h=_hash(purpose, email, code), exp=now + TTL, tries=0, sent=sent + [now])
        if payload is not None:
            doc["payload"] = payload
    return code


def payload_of(purpose, email):
    doc = storage.get_doc("otp", _key(purpose, email), {}) or {}
    return doc.get("payload")


def forget(purpose, email):
    """Cancel a pending code (used when the e-mail could not be sent)."""
    with storage.update_doc("otp", _key(purpose, email)) as doc:
        doc.pop("h", None)


def verify(purpose, email, code):
    """Check a code. Returns the stored payload (or True). Raises OtpError. A code works once."""
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    error = None          # the error is raised AFTER the document is saved, so the try counter really counts
    result = True
    with storage.update_doc("otp", _key(purpose, email)) as doc:
        if not doc.get("h"):
            error = OtpError("No code is waiting for this e-mail. Please ask for a new code.")
        elif time.time() > doc.get("exp", 0):
            doc.pop("h", None)
            error = OtpError("This code has expired. Please ask for a new code.")
        elif doc.get("tries", 0) >= MAX_TRIES:
            doc.pop("h", None)
            error = OtpError("Too many wrong tries. Please ask for a new code.", 429)
        elif len(code) != 6 or not hmac.compare_digest(doc["h"], _hash(purpose, email, code)):
            doc["tries"] = doc.get("tries", 0) + 1
            left = MAX_TRIES - doc["tries"]
            if left <= 0:
                doc.pop("h", None)
                error = OtpError("Too many wrong tries. Please ask for a new code.", 429)
            else:
                error = OtpError(f"That code is not correct. {left} {'try' if left == 1 else 'tries'} left.")
        else:
            result = doc.get("payload")
            doc.pop("h", None)
            doc.pop("payload", None)
    if error:
        raise error
    return result if result is not None else True
