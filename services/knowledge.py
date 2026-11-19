"""Built-in course library (AI, ML, DSA, Calculus, Engineering Maths).

The notes ship inside one packed file (services/_cache.dat) and are read straight from memory,
so lessons and MCQs need no Groq call.
"""
import base64
import hashlib
import json
import random
import threading
import zlib
from datetime import datetime
from pathlib import Path

_FILE = Path(__file__).with_name("_cache.dat")
_lock = threading.Lock()
_data = None

LEVEL_KEYS = {"beginner": ["b"], "mid": ["m"], "advanced": ["a"], "all": ["b", "m", "a"]}
LEVEL_NAME = {"b": "Beginner", "m": "Mid", "a": "Advanced"}
LEVEL_TAG = {"b": "Basic", "m": "Intermediate", "a": "Advanced"}
LEVEL_CHOICES = [("beginner", "Beginner"), ("mid", "Mid"), ("advanced", "Advanced"), ("all", "All levels, basic to advanced")]


def _key():
    return hashlib.sha256(b"auv::rote::" + bytes([7, 21, 91, 3])).digest()


def _load():
    try:
        raw = base64.b85decode(_FILE.read_bytes())
        k = _key()
        plain = bytes(b ^ k[i % len(k)] for i, b in enumerate(raw))
        return json.loads(zlib.decompress(plain).decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        # services/_cache.dat is missing (it is NOT uploaded to GitHub when .gitignore blocks *.dat) or damaged.
        # Do not crash every page with an error: start with no built-in subjects (courses then use the AI instead).
        print(f"WARNING: built-in course data not loaded ({exc.__class__.__name__}: {exc}). "
              "Add services/_cache.dat to your project and deploy again.", flush=True)
        return {"subjects": []}


def data():
    global _data
    if _data is None:
        with _lock:
            if _data is None:
                _data = _load()
    return _data


def subject_options():
    return [(s["id"], s["name"]) for s in data()["subjects"]]


def has_subject(sid):
    return any(s["id"] == sid for s in data()["subjects"])


def _subject(sid):
    for s in data()["subjects"]:
        if s["id"] == sid:
            return s
    return None


def subject_name(sid):
    s = _subject(sid)
    return s["name"] if s else sid


def topic(key):
    """key looks like 'dsa.m.2'. Returns (subject, level_letter, topic) or None."""
    try:
        sid, lvl, idx = key.split(".")
        s = _subject(sid)
        return s, lvl, s["levels"][lvl][int(idx)]
    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
        return None


def iter_facts(sid=None):
    """Yield (subject, level_letter, topic_index, topic, fact_index, q, a)."""
    for s in data()["subjects"]:
        if sid and s["id"] != sid:
            continue
        for lvl in ("b", "m", "a"):
            for ti, t in enumerate(s["levels"][lvl]):
                for fi, (q, a) in enumerate(t["facts"]):
                    yield s, lvl, ti, t, fi, q, a


# ---------- building a course ----------

def build_course(sid, level):
    """Return (title, description, modules) in the same shape the Groq syllabus produces."""
    s = _subject(sid)
    level = level if level in LEVEL_KEYS else "beginner"
    modules, n = [], 0
    for lvl in LEVEL_KEYS[level]:
        topics = []
        for ti, t in enumerate(s["levels"][lvl]):
            n += 1
            topics.append({
                "id": f"t{n}", "title": t["title"], "summary": "Memory hook: " + t["mn"],
                "minutes": 20, "status": "todo", "mastery": None, "attempts": 0,
                "kb": f"{sid}.{lvl}.{ti}",
            })
        if topics:
            modules.append({
                "id": f"m{len(modules) + 1}", "title": f"{LEVEL_NAME[lvl]} {s['name'].split(' (')[0]}",
                "level": LEVEL_TAG[lvl], "goal": "Memorize the key facts, formulas and definitions.",
                "topics": topics,
            })
    label = dict(LEVEL_CHOICES)[level].split(",")[0]
    title = f"{s['name'].split(' (')[0]} ({label})"
    desc = "Structured lessons, worked examples and quizzes, from the basics to advanced."
    return title, desc, modules


# ---------- lessons ----------

def _safe(text):
    """The page's tiny Markdown renderer treats * as emphasis; swap it for a look-alike."""
    return str(text).replace("*", "\u2217")


def iter_topics():
    for s in data()["subjects"]:
        for lvl in ("b", "m", "a"):
            for ti, t in enumerate(s["levels"][lvl]):
                yield s, lvl, ti, t


def lesson(key):
    found = topic(key)
    if not found:
        return None
    s, lvl, t = found
    lines = [
        f"## {t['title']}",
        f"> Memory hook: {_safe(t['mn'])}",
        "",
        "### Overview",
        _safe(t["ov"]),
        "",
        f"### Key facts to memorize ({len(t['facts'])})",
    ]
    for i, (q, a) in enumerate(t["facts"], start=1):
        lines.append(f"{i}. **{_safe(q)}** \u2192 {_safe(a)}")
    lines += [
        "",
        "### Worked example",
        f"> {_safe(t['ex'])}",
        "",
        "### Common mistakes",
    ]
    lines += [f"- {_safe(p)}" for p in t["pit"]]
    lines += [
        "",
        "### Study routine",
        "1. Read the overview, then the facts aloud twice.",
        "2. Cover the answers and recall them with the flashcards below.",
        "3. Repeat today, tomorrow and in three days. Spaced repeats beat one long session.",
        "4. Finish with the quiz to find the facts that did not stick.",
    ]
    return {
        "markdown": "\n".join(lines),
        "cards": [[q, a] for q, a in t["facts"]],
        "sources": [],
        "created": datetime.now().isoformat(timespec="seconds"),
    }


# ---------- MCQs ----------

def _shape(text):
    if "O(" in text:
        return "bigo"
    if any(ch in text for ch in "=^/\u2217") or sum(c.isdigit() for c in text) >= 2:
        return "math"
    return "text"


def _distractors(subject, level, tkey, fact_a, rng):
    seen = {fact_a.lower()}
    ranked = []
    for s, lvl, ti, t, fi, q, a in iter_facts(subject["id"]):
        low = a.lower()
        if low in seen or low in fact_a.lower() or fact_a.lower() in low:
            continue
        seen.add(low)
        bonus = (-15 if f"{s['id']}.{lvl}.{ti}" == tkey else 0) + (-8 if lvl == level else 0)
        ranked.append((abs(len(a) - len(fact_a)) + rng.uniform(0, 12) + bonus, a))
    ranked.sort(key=lambda item: item[0])
    same = [a for _, a in ranked if _shape(a) == _shape(fact_a)]
    other = [a for _, a in ranked if _shape(a) != _shape(fact_a)]
    return (same + other)[:3]


def make_questions(pairs, count, rng=None):
    """pairs: [(course_topic_id, kb_key)]. Returns questions in the format the quiz grader expects."""
    rng = rng or random.Random()
    groups = []
    for tid, key in pairs:
        found = topic(key)
        if not found:
            continue
        facts = list(range(len(found[2]["facts"])))
        rng.shuffle(facts)
        groups.append([tid, key, facts])
    rng.shuffle(groups)

    picked = []
    while len(picked) < count and any(g[2] for g in groups):
        for g in groups:
            if g[2] and len(picked) < count:
                picked.append((g[0], g[1], g[2].pop()))

    questions = []
    for tid, key, fi in picked:
        s, lvl, t = topic(key)
        q, a = t["facts"][fi]
        options = [a] + _distractors(s, lvl, key, a, rng)
        if len(options) < 4:
            continue
        rng.shuffle(options)
        questions.append({
            "topic_id": tid, "question": q, "options": options, "answer_index": options.index(a),
            "explanation": f"{a}. Memory hook: {t['mn']}",
        })
    rng.shuffle(questions)
    return questions
