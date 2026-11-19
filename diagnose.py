"""Run:  python diagnose.py   -> shows exactly where Groq (and web search) fail on this computer."""
import time, requests
from services.config import get_setting, has_api_key, has_search_key
from services import groq
model = get_setting("GROQ_MODEL", groq.DEFAULT_MODEL)
print("Groq key found:", has_api_key(), "| model:", model)
print("Tavily key found:", has_search_key())

print("Models this key can use:", groq.discover(get_setting("GROQ_API_KEY")) or "could not list")
t = time.time()
try:
    r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                      headers={"Authorization": "Bearer " + get_setting("GROQ_API_KEY")},
                      json={"model": model, "messages": [{"role": "user", "content": "Say hi in 3 words"}], "max_tokens": 50},
                      timeout=(10, 30))
    print(f"[groq] HTTP {r.status_code} in {time.time()-t:.1f}s\n   {r.text[:300]!r}")
except Exception as e:
    print(f"[groq] FAILED after {time.time()-t:.1f}s: {e.__class__.__name__}: {e}")

if has_search_key():
    t = time.time()
    try:
        r = requests.post("https://api.tavily.com/search",
                          headers={"Authorization": "Bearer " + get_setting("TAVILY_API_KEY")},
                          json={"query": "binary search geeksforgeeks", "max_results": 1}, timeout=(10, 30))
        print(f"[tavily] HTTP {r.status_code} in {time.time()-t:.1f}s\n   {r.text[:200]!r}")
    except Exception as e:
        print(f"[tavily] FAILED after {time.time()-t:.1f}s: {e.__class__.__name__}: {e}")

print("App self-test:", groq.check())
