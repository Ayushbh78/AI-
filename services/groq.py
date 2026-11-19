"""Thin client for the Groq API (no SDK needed, only `requests`).

Groq speaks the OpenAI chat-completions format. Built to never hang: short timeouts, a hard
overall deadline per call, and a quick fall-through to the next model when one is rate limited
or no longer available.
"""
import json
import re
import time

import requests

from .config import get_setting, has_api_key

URL = "https://api.groq.com/openai/v1/chat/completions"
MODELS_URL = "https://api.groq.com/openai/v1/models"
DEFAULT_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODELS = ["openai/gpt-oss-20b", "llama-3.1-8b-instant"]
# Used only when the models above are gone: the app asks Groq which models the key can use and picks
# the best chat model in this order (first match wins).
PREFERRED = ("gpt-oss-120b", "llama-3.3-70b", "gpt-oss-20b", "llama-3.1-8b", "llama", "qwen", "gemma")
NOT_CHAT = ("whisper", "tts", "guard", "orpheus", "embed", "compound", "distil-whisper")

CONNECT_TIMEOUT = 10      # seconds to open the connection
READ_TIMEOUT = 40         # seconds to wait for one answer
DEADLINE = 85             # seconds for the whole generate() call, all retries included


_found = []   # the model that last worked, tried first next time


class GroqError(Exception):
    """fatal=True means retrying will not help (missing or rejected API key)."""

    def __init__(self, message, status=502, fatal=False):
        super().__init__(message)
        self.status = status
        self.fatal = fatal


def _log(text):
    print(f"[groq] {text}", flush=True)


def _api_message(response):
    try:
        body = response.json()
        return (body.get("error", {}).get("message", "") or response.text[:300]).strip()
    except (ValueError, AttributeError):
        return response.text[:300].strip()


def _post(payload, key, budget=READ_TIMEOUT):
    """One HTTP call. Returns the response, or raises GroqError on network trouble."""
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    try:
        return requests.post(URL, headers=headers, json=payload, timeout=(CONNECT_TIMEOUT, max(5, budget)))
    except requests.Timeout:
        raise GroqError("Groq took too long to answer. Please try again in a moment.", status=504)
    except requests.RequestException as exc:
        raise GroqError(f"Could not reach Groq. Check your internet connection. ({exc.__class__.__name__})", status=503)


def _parse_json(text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise GroqError("Groq sent back data in a format the app could not read. Please try again.")


def _extract(data, json_mode):
    choices = data.get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
    # Some reasoning models wrap their thinking in <think> tags; hide it from students.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    if not text:
        raise GroqError("Groq returned an empty answer. Please try again.")
    return _parse_json(text) if json_mode else text


def discover(key):
    """Ask Groq which chat models this key can use, best first. [] if the call fails."""
    try:
        r = requests.get(MODELS_URL, headers={"Authorization": f"Bearer {key}"}, timeout=(CONNECT_TIMEOUT, 15))
        ids = [m.get("id", "") for m in (r.json().get("data") or []) if m.get("active", True)]
    except (requests.RequestException, ValueError, AttributeError):
        return []
    ids = [i for i in ids if i and not any(bad in i.lower() for bad in NOT_CHAT)]
    ranked = []
    for want in PREFERRED:
        ranked += [i for i in ids if want in i.lower() and i not in ranked]
    return ranked + [i for i in ids if i not in ranked]


def _messages(prompt, system, history, json_mode):
    system = system or ""
    if json_mode:
        system = (system + " Respond with a single valid JSON object only, no other text.").strip()
    messages = [{"role": "system", "content": system}] if system else []
    for turn in history or []:
        messages.append({"role": "user" if turn["role"] == "user" else "assistant", "content": turn["text"]})
    if prompt is not None:
        messages.append({"role": "user", "content": prompt})
    return messages


def generate(prompt=None, *, system=None, history=None, json_mode=False, temperature=0.7, max_tokens=8192, deadline=DEADLINE):
    """Call Groq. Returns text, or parsed JSON when json_mode=True."""
    if not has_api_key():
        raise GroqError(
            "Groq API key is missing. Open the .env file, paste your key after GROQ_API_KEY= and save.",
            status=400, fatal=True)
    key = get_setting("GROQ_API_KEY")

    base = {"messages": _messages(prompt, system, history, json_mode),
            "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        base["response_format"] = {"type": "json_object"}

    models = []
    for name in [get_setting("GROQ_MODEL", DEFAULT_MODEL)] + FALLBACK_MODELS:
        if name and name not in models:
            models.append(name)
    if _found:
        models = _found[:1] + [m for m in models if m not in _found[:1]]

    started = time.time()
    last_error = None
    discovered = False
    tried = []

    while models:
        model = models.pop(0)
        tried.append(model)
        if time.time() - started > deadline:
            raise last_error or GroqError("Groq took too long to answer. Please try again.", status=504)
        payload = dict(base, model=model)
        if "gpt-oss" in model:
            payload["reasoning_effort"] = "low"   # fast answers; keeps the token budget for the reply
        t0 = time.time()
        try:
            response = _post(payload, key, deadline - (time.time() - started))
            if response.status_code in (500, 502, 503) and time.time() - started < deadline - 30:
                time.sleep(1.5)
                response = _post(payload, key)
        except GroqError as err:
            _log(f"{model}: {err} ({time.time() - t0:.1f}s)")
            last_error = err
            raise  # network problem or hang: say so now instead of waiting through every model

        _log(f"{model}: HTTP {response.status_code} in {time.time() - t0:.1f}s")

        if response.status_code == 200:
            try:
                result = _extract(response.json(), json_mode)
                _found[:] = [model]   # remember what worked
                return result
            except ValueError:
                last_error = GroqError("Groq sent an unreadable response. Please try again.")
                continue
            except GroqError as err:
                last_error = err
                if "format the app could not read" in str(err) or "empty answer" in str(err):
                    continue  # cheap to retry once with the next model
                raise

        message = _api_message(response)
        _log(f"   {message[:200]}")
        if response.status_code in (401, 403):
            raise GroqError(f"Groq rejected the API key ({message[:160]}). Check GROQ_API_KEY in the .env file.",
                            status=400, fatal=True)
        if response.status_code == 429:
            last_error = GroqError("Groq rate limit reached (free tier). Wait a minute and try again.", status=429)
            continue  # another model has its own quota
        if response.status_code in (400, 404) and re.search(r"model|decommission|not found|access", message, re.I):
            last_error = GroqError(f"Model {model} is not available for this key.", status=502)
            if not models and not discovered:   # every listed model is gone: ask Groq what is available
                discovered = True
                models = [m for m in discover(key) if m not in tried][:4]
                _log(f"asking Groq for available models: {models}")
            continue
        last_error = GroqError(f"Groq error ({response.status_code}): {message[:200]}")
        break

    if last_error is not None:
        raise last_error
    raise GroqError("None of the configured Groq models are available. Set GROQ_MODEL in the .env file.", fatal=True)


def check():
    """Tiny test call used by /api/health and the startup self-check. Returns (ok, message)."""
    try:
        text = generate("Reply with the single word: ok", max_tokens=16, temperature=0)
        return True, f"Groq is working ({text.strip()[:20]!r})."
    except GroqError as err:
        return False, str(err)
