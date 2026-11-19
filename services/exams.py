"""Real-exam engine (GATE, JEE, NEET, CAT, any exam).

1. get_info()      reads the official syllabus (and pattern when needed) from the web with Tavily, structures it with Groq,
                   and falls back to the built-in data in exam_data.py. Result is cached for 30 days.
2. plan_slots()    decides, from the official pattern, exactly how many questions of which type, marks and subject the paper has.
3. start_paper()   writes the questions with Groq in small batches (background job with progress), checks every question.
4. attempts        the exam hall: a server-side timer, autosave, grading with negative marking, analysis by subject and topic.
5. prepare_course  turns the syllabus into a ready study plan.
"""
import json
import random
import re
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import course_logic as cl
from . import exam_data as ed
from . import groq, prompts, storage, websearch
from .config import has_api_key, has_search_key

INFO_VERSION = 2
INFO_DAYS = 30
BATCH = 6                 # questions written per AI call
WORKERS = 3
JOB_LIMIT = 15 * 60       # seconds: one paper must finish within this
INDEX_LIMIT = 40

JOBS = {}
_jobs_lock = threading.Lock()


class ExamError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _log(text):
    print(f"[exams] {text}", flush=True)


def _clean(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _now():
    return datetime.now().isoformat(timespec="seconds")


def apportion(total, weights):
    """Split `total` into whole numbers that follow `weights` (largest remainder). {key: weight} -> {key: count}."""
    keys = list(weights)
    wsum = sum(max(0.0, float(weights[k])) for k in keys)
    if not keys or total <= 0:
        return {k: 0 for k in keys}
    if wsum <= 0:
        weights, wsum = {k: 1 for k in keys}, len(keys)
    raw = {k: total * max(0.0, float(weights[k])) / wsum for k in keys}
    out = {k: int(raw[k]) for k in keys}
    left = total - sum(out.values())
    for k in sorted(keys, key=lambda x: raw[x] - out[x], reverse=True)[:left]:
        out[k] += 1
    return out


def _ai(prompt, system, max_tokens, temperature=0.5, deadline=70, retries=3):
    """One Groq call. A rate limit (free plan) waits and tries again instead of failing the whole paper."""
    last = None
    for attempt in range(retries):
        try:
            return groq.generate(prompt, system=system, json_mode=True, temperature=temperature,
                                 max_tokens=max_tokens, deadline=deadline)
        except groq.GroqError as err:
            last = err
            if err.fatal:
                raise
            _log(f"AI call failed ({err.status}): {str(err)[:120]}")
            time.sleep(22 if err.status == 429 else 3)
    raise last


# ============================================================ 1. syllabus and pattern

def exam_title(exam_id, paper, custom=""):
    exam = ed.exam_by_id(exam_id)
    if exam_id == "custom":
        return _clean(f"{custom} {paper}", 100)
    name = next((p["name"] for p in exam["papers"] if p["id"] == paper), paper)
    if exam_id == "gate":
        return f"GATE {name} ({paper})"
    return exam["name"] if name == exam["name"] or len(exam["papers"]) == 1 else f"{exam['name']} {name}"


def _key(exam_id, paper, custom):
    base = f"{exam_id}__{paper}" if exam_id != "custom" else "custom__" + re.sub(r"[^a-z0-9]+", "-", f"{custom} {paper}".lower()).strip("-")
    return base[:120]


def _norm_subjects(raw):
    out = []
    for sub in raw if isinstance(raw, list) else []:
        if not isinstance(sub, dict):
            continue
        name = _clean(sub.get("name"), 80)
        topics, seen = [], set()
        for t in sub.get("topics") or []:
            t = _clean(t.get("title") if isinstance(t, dict) else t, 110)
            if t and t.lower() not in seen:
                seen.add(t.lower())
                topics.append(t)
        try:
            weight = float(sub.get("marks") or sub.get("weight") or 0)
        except (TypeError, ValueError):
            weight = 0
        if name and len(topics) >= 2:
            out.append({"name": name, "weight": max(0.0, weight), "topics": topics[:30]})
    return out[:14]


def _norm_pattern(raw):
    """Check a pattern read from the web. Returns None when it cannot be trusted."""
    if not isinstance(raw, dict) or not isinstance(raw.get("sections"), list):
        return None
    sections, total_q = [], 0
    for sec in raw["sections"]:
        groups = []
        for g in (sec.get("groups") or []) if isinstance(sec, dict) else []:
            try:
                count, marks = int(g.get("count")), float(g.get("marks"))
            except (TypeError, ValueError, AttributeError):
                continue
            types = {k: float(v) for k, v in (g.get("types") or {}).items() if k in ("mcq", "msq", "nat") and isinstance(v, (int, float)) and v > 0}
            if count < 1 or marks <= 0 or marks > 10:
                continue
            groups.append({"count": count, "marks": int(marks) if float(marks).is_integer() else marks, "types": types or {"mcq": 1.0}})
            total_q += count
        if groups:
            sections.append({"name": _clean(sec.get("name"), 90) or "Section", "subject": _clean(sec.get("subject"), 80) or None, "groups": groups})
    try:
        duration = int(float(raw.get("duration_min")))
    except (TypeError, ValueError):
        return None
    if not sections or not 10 <= total_q <= 200 or not 20 <= duration <= 360:
        return None
    try:
        neg = max(0.0, min(0.5, float(raw.get("negative_mcq_fraction") or 0)))
    except (TypeError, ValueError):
        neg = 0.0
    total_marks = sum(g["count"] * g["marks"] for s in sections for g in s["groups"])
    return {"duration_min": duration, "total_marks": total_marks, "sections": sections,
            "negative": {"mcq": neg, "msq": 0, "nat": 0}, "rules": []}


def _web_pages(title, need_pattern):
    pages, seen = [], set()
    jobs = [(f"{title} official syllabus subjects topics", 3500, 3)]
    if need_pattern:
        jobs.append((f"{title} exam pattern number of questions marks negative marking duration", 2000, 2))
    for query, chars, limit in jobs:
        for p in websearch.search(query, timeout=15, general=True, max_chars=chars, limit=limit):
            if p["url"] not in seen:
                seen.add(p["url"])
                pages.append(p)
    return pages


EXTRACT_PATTERN_SPEC = '''
  "pattern": {"duration_min": 180, "negative_mcq_fraction": 0.33,
    "sections": [{"name": "section name", "subject": "subject name, or null when the section mixes subjects",
                  "groups": [{"count": 25, "marks": 1, "types": {"mcq": 0.6, "msq": 0.1, "nat": 0.3}}]}]}'''


def _extract(title, pages, need_pattern, exam_id):
    context = "\n\n".join(f"[Page {i}: {p['title']}]\n{p['text']}" for i, p in enumerate(pages, start=1)) if pages else ""
    ga_rule = " Leave out General Aptitude: it is handled separately." if exam_id == "gate" else ""
    source = ("Use ONLY the web pages below. Do not invent topics." if pages
              else "No web pages are available: use your own knowledge of the official syllabus.")
    prompt = f"""Extract the official syllabus{' and exam pattern' if need_pattern else ''} of the exam: {title}.
{source}{ga_rule}

Return only JSON of this shape:
{{"subjects": [{{"name": "official subject name", "marks": 14, "topics": ["short topic title", "..."]}}],{EXTRACT_PATTERN_SPEC if need_pattern else ''}
}}
Rules: topics are short titles (3 to 10 words), 4 to 20 per subject, no duplicates. "marks" = approximate marks that subject
carries in the whole paper (estimate when the pages do not say). Types: mcq = single correct, msq = one or more correct,
nat = numerical answer typed in.

{context}"""
    raw = _ai(prompt, "You extract exam syllabus facts exactly and return valid JSON only.", 3500, temperature=0.1, deadline=75)
    return _norm_subjects(raw.get("subjects")), (_norm_pattern(raw.get("pattern")) if need_pattern else None)


def _finalize_subjects(exam_id, subjects):
    """GATE: General Aptitude (15 marks) is its own subject, the technical subjects share the other 85 marks."""
    subjects = [dict(s) for s in subjects]
    if exam_id == "gate":
        tech = [s for s in subjects if "general aptitude" not in s["name"].lower()]
        counts = apportion(85, {s["name"]: (s["weight"] or 1) for s in tech})
        for s in tech:
            s["weight"] = counts[s["name"]]
        ga = {"name": ed.GA[0], "weight": 15, "topics": list(ed.GA[2])}
        return tech + [ga]
    for s in subjects:
        s["weight"] = s["weight"] or 1
    return subjects


def _build_info(exam_id, paper, custom):
    exam = ed.exam_by_id(exam_id)
    title = exam_title(exam_id, paper, custom)
    built = ed.builtin(exam_id, paper)
    default_pattern = (built[0] if built else ed.gate_pattern() if exam_id == "gate" else None)
    subjects, pattern, sources, origin = None, None, [], ""
    notes = []

    if has_search_key() and has_api_key():
        try:
            pages = _web_pages(title, need_pattern=default_pattern is None)
            if pages:
                subjects, pattern = _extract(title, pages, default_pattern is None, exam_id)
                sources = [{"title": p["title"], "url": p["url"]} for p in pages]
                if len(subjects) >= 2:
                    origin = "web"
                else:
                    subjects = None
                    notes.append("The web pages did not contain a clear syllabus.")
        except groq.GroqError as err:
            if err.fatal:
                raise ExamError(str(err))
            notes.append("The syllabus could not be read from the web right now.")
        except Exception as err:  # noqa: BLE001  never let a lookup crash the page
            _log(f"web lookup failed: {err!r}")
            notes.append("The web lookup failed.")

    if subjects is None and built:
        subjects = [{"name": n, "weight": float(w), "topics": list(t)} for n, w, t in built[1]]
        origin = "builtin"
        if exam_id == "gate":
            subjects = [s for s in subjects if s["name"] != ed.GA[0]]
    if subjects is None:
        if not has_api_key():
            raise ExamError("The AI key is not set on the server, so this exam's syllabus cannot be prepared. Add GROQ_API_KEY.")
        try:
            subjects, pattern = _extract(title, [], default_pattern is None, exam_id)
        except groq.GroqError as err:
            raise ExamError(f"Could not prepare the syllabus: {err}")
        if len(subjects) < 2:
            raise ExamError("Could not find a syllabus for this exam. Check the exam name or add a Tavily key.")
        origin = "ai"
        notes.append("From AI knowledge, not verified on the web. Add TAVILY_API_KEY to read the official pages.")

    pattern_origin = "builtin" if default_pattern else ("web" if pattern else "generic")
    pattern = default_pattern or pattern or ed.generic_pattern()
    if pattern_origin == "generic":
        notes.append("The official pattern could not be read, so a standard pattern is used.")

    subjects = _finalize_subjects(exam_id, subjects)
    names = {s["name"].lower() for s in subjects}
    for sec in pattern["sections"]:        # a section tied to a subject that does not exist becomes a mixed section
        if sec.get("subject") and sec["subject"].lower() not in names:
            sec["subject"] = None
    for sec in pattern["sections"]:
        if sec.get("subject"):
            sec["subject"] = next(s["name"] for s in subjects if s["name"].lower() == sec["subject"].lower())
    return {"version": INFO_VERSION, "exam_id": exam_id, "exam": exam["name"], "paper": paper, "title": title,
            "paper_name": next((p["name"] for p in exam["papers"] if p["id"] == paper), custom or paper),
            "subjects": subjects, "pattern": pattern, "sources": sources, "origin": origin,
            "pattern_origin": pattern_origin, "notes": notes, "built": _now()}


def get_info(exam_id, paper="", custom="", refresh=False):
    exam = ed.exam_by_id(exam_id)
    if not exam:
        raise ExamError("Unknown exam.")
    paper, custom = _clean(paper, 60), _clean(custom, 80)
    if exam_id == "custom":
        if len(custom) < 2:
            raise ExamError("Type the name of the exam.")
    elif paper not in {p["id"] for p in exam["papers"]}:
        raise ExamError("Choose a paper or branch.")
    key = _key(exam_id, paper, custom)
    cached = storage.get_doc("examinfo", key)
    if cached and not refresh and cached.get("version") == INFO_VERSION:
        try:
            age = (datetime.now() - datetime.fromisoformat(cached["built"])).days
        except (KeyError, ValueError):
            age = 999
        if age < INFO_DAYS:
            return cached
    info = _build_info(exam_id, paper, custom)
    storage.put_doc("examinfo", key, info)
    return info


def pattern_summary(info):
    p = info["pattern"]
    total_q = sum(g["count"] for s in p["sections"] for g in s["groups"])
    total_m = sum(g["count"] * g["marks"] for s in p["sections"] for g in s["groups"])
    return {"duration_min": p["duration_min"], "questions": total_q, "marks": total_m, "rules": p.get("rules", []),
            "sections": [{"name": s["name"], "questions": sum(g["count"] for g in s["groups"]),
                          "marks": sum(g["count"] * g["marks"] for g in s["groups"])} for s in p["sections"]]}


# ============================================================ 2. planning the paper

def plan_slots(info, selected=None):
    """The question 'slots' of the whole official paper, optionally only for some subjects.
    Each slot = {section, subject, marks, type}. Counts per section and marks follow the official pattern exactly."""
    pattern, subjects = info["pattern"], info["subjects"]
    fixed = {s["subject"] for s in pattern["sections"] if s.get("subject")}
    free = {s["name"]: s["weight"] for s in subjects if s["name"] not in fixed}
    slots = []
    for sec in pattern["sections"]:
        for gi, g in enumerate(sec["groups"]):
            n = g["count"]
            per_subject = {sec["subject"]: n} if sec.get("subject") else apportion(n, free or {subjects[0]["name"]: 1})
            names = [name for name, c in per_subject.items() for _ in range(c)]
            types = [t for t, c in apportion(n, g["types"]).items() for _ in range(c)]
            random.shuffle(names)
            random.shuffle(types)
            for name, kind in zip(names, types):
                slots.append({"section": sec["name"], "subject": name, "marks": g["marks"], "type": kind, "group": gi})
    full_marks = sum(s["marks"] for s in slots)
    full_minutes = pattern["duration_min"]
    if not selected:
        return slots, full_minutes, full_marks
    chosen = set(selected)
    picked = [s for s in slots if s["subject"] in chosen]
    for name in chosen:                          # a subject with very little weight still gets a usable mini test
        have = [s for s in picked if s["subject"] == name]
        if len(have) < 5:
            donor = next((s for s in slots if s["subject"] == name), None) or {"section": pattern["sections"][-1]["name"], "marks": 1, "group": 0}
            for _ in range(5 - len(have)):
                picked.append({"section": donor["section"], "subject": name, "marks": min(g["marks"] for g in
                               next(sec for sec in pattern["sections"] if sec["name"] == donor["section"])["groups"]),
                               "type": random.choice(["mcq", "mcq", "nat", "msq"]), "group": donor.get("group", 0)})
    if not picked:
        raise ExamError("Choose at least one subject.")
    picked_marks = sum(s["marks"] for s in picked)
    minutes = max(15, int(round(full_minutes * picked_marks / max(1, full_marks) / 5.0)) * 5)
    return picked, min(minutes, full_minutes), picked_marks


def _order(slots):
    """Official order: by section, then by marks group (1-mark questions before 2-mark ones); subjects mixed inside."""
    sec_order = {}
    for s in slots:
        sec_order.setdefault(s["section"], len(sec_order))
    random.shuffle(slots)
    return sorted(slots, key=lambda s: (sec_order[s["section"]], s["group"]))


# ============================================================ 3. writing the questions

DIFFICULTY = {
    "easy": "EASY: direct application of one concept, short working, a well-prepared student gets it right in about a minute.",
    "medium": "MEDIUM: the usual level of the real paper: two or three steps, some conceptual traps in the options.",
    "hard": "HARD: tough multi-concept questions with careful working, close distractors and edge cases, like the hardest 20% of the real paper.",
}


def _subject_hint(subject):
    low = subject.lower()
    for word, hint in ed.SUBJECT_STYLE.items():
        if word in low:
            return hint
    return ""


def _letters(n):
    return "ABCD"[:n]


def _parse_nat(answer):
    low = high = None
    try:
        if isinstance(answer, dict):
            low, high = float(answer.get("low")), float(answer.get("high", answer.get("low")))
        elif isinstance(answer, (list, tuple)) and len(answer) >= 1:
            low, high = float(answer[0]), float(answer[-1])
        else:
            low = high = float(str(answer).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if low > high:
        low, high = high, low
    return {"low": low, "high": high}


def _match_topic(topic, topics):
    t = _clean(topic, 140).lower()
    for name in topics:
        if name.lower() == t:
            return name
    words = set(re.findall(r"[a-z0-9]+", t))
    best, score = topics[0], 0
    for name in topics:
        overlap = len(words & set(re.findall(r"[a-z0-9]+", name.lower())))
        if overlap > score:
            best, score = name, overlap
    return best


_FIXED_OPTION = re.compile(r"\b(all|none|both|neither)\b.*\b(above|these|options?)\b|\b[a-d]\s*(and|&|,)\s*[a-d]\b", re.I)


def _validate(item, slot, topics):
    if not isinstance(item, dict):
        return None
    text = str(item.get("text") or "").strip()
    if len(text) < 15:
        return None
    kind = slot["type"]
    if str(item.get("type") or kind).lower() != kind:
        return None
    q = {"type": kind, "text": text[:2200], "topic": _match_topic(item.get("topic"), topics),
         "explanation": str(item.get("explanation") or "").strip()[:700], "options": None, "answer": None}
    if kind in ("mcq", "msq"):
        options = item.get("options")
        if not isinstance(options, list) or len(options) != 4:
            return None
        options = [re.sub(r"^\(?[A-Da-d][\)\.:]\s+", "", str(o).strip())[:400] for o in options]
        if not all(options):
            return None
        if kind == "mcq":
            ans = str(item.get("answer") or "").strip().upper()[:1]
            if ans not in "ABCD" or not ans:
                return None
            correct = [ans]
        else:
            raw = item.get("answer")
            raw = raw if isinstance(raw, list) else re.findall(r"[A-Da-d]", str(raw or ""))
            correct = sorted({str(a).strip().upper()[:1] for a in raw if str(a).strip().upper()[:1] in list("ABCD")})
            if not correct:
                return None
        if not any(_FIXED_OPTION.search(o) for o in options):     # shuffle so the key letters are evenly spread
            order = list(range(4))
            random.shuffle(order)
            options = [options[i] for i in order]
            old_letters = ["ABCD"[i] for i in order]                # new position k holds old letter old_letters[k]
            correct = sorted("ABCD"[old_letters.index(c)] for c in correct)
        q["options"], q["answer"] = options, correct
    else:
        nat = _parse_nat(item.get("answer"))
        if nat is None:
            return None
        q["answer"] = nat
    return q


def _write_batch(info, subject, difficulty, batch, job, deadline_at):
    """batch = [(slot_index, slot)]. Returns {slot_index: question}. Missing questions are asked for again."""
    got = {}
    topics = subject["topics"]
    exam_style = ed.EXAM_STYLE.get(info["exam_id"], "Write like the real paper of this exam.")
    for attempt in range(4):
        pending = [(i, s) for i, s in batch if i not in got]
        if not pending:
            break
        if time.time() > deadline_at:
            raise ExamError("Writing the paper took too long. Please try again.")
        lines = "\n".join(f"{n}. type={s['type']}  marks={s['marks']}" for n, (_, s) in enumerate(pending, start=1))
        system = (f"You are a senior paper-setter for {info['title']}. You write ORIGINAL questions in the exact style, depth and "
                  "wording of the real past papers. Every question is unambiguous, solvable by hand in 1-3 minutes and has ONE "
                  "verified correct answer: work it out carefully before writing the answer. No images: describe everything in text, "
                  "use markdown tables for data and fenced code blocks for code. " + prompts.MATH_RULE)
        prompt = f"""Exam: {info['title']}
Subject: {subject['name']}
{DIFFICULTY[difficulty]}
{exam_style} {_subject_hint(subject['name'])}

Syllabus topics of this subject (each question's "topic" must be exactly one of these, spread the questions over different topics):
{json.dumps(topics, ensure_ascii=False)}

Write exactly {len(pending)} questions, one per line below, in this order:
{lines}

Type rules:
- mcq: exactly 4 options, exactly ONE correct. "answer": "A", "B", "C" or "D".
- msq: exactly 4 options, ONE OR MORE correct (state "Which of the following is/are ..."). "answer": ["A","C"].
- nat: the answer is a single number. "answer": {{"low": x, "high": y}} = the accepted range (low = high for an integer; for decimals use a small
  range, e.g. 0.46 to 0.47). The question must say how to round (e.g. "rounded off to two decimal places").
Options contain no letters. "explanation": the key working in at most 3 short sentences.

Return only JSON:
{{"questions": [{{"slot": 1, "type": "mcq", "text": "...", "options": ["...","...","...","..."], "answer": "B", "topic": "...", "explanation": "..."}}]}}"""
        try:
            raw = _ai(prompt, system, max_tokens=900 + 520 * len(pending), temperature=0.6, deadline=80)
        except groq.GroqError as err:
            if err.fatal:
                raise ExamError(str(err))
            continue
        items = raw.get("questions") if isinstance(raw, dict) else raw
        for pos, item in enumerate(items if isinstance(items, list) else [], start=1):
            try:
                n = int(item.get("slot", pos))
            except (TypeError, ValueError, AttributeError):
                n = pos
            if not 1 <= n <= len(pending):
                continue
            idx, slot = pending[n - 1]
            if idx in got:
                continue
            q = _validate(item, slot, topics)
            if q:
                got[idx] = q
                with _jobs_lock:
                    job["done"] += 1
    return got


def start_paper(username, info, difficulty, selected=None):
    """Start writing a paper in the background. Returns the paper id; poll job_status() for progress."""
    if not has_api_key():
        raise ExamError("The AI key is not set on the server, so papers cannot be generated. Add GROQ_API_KEY.")
    difficulty = difficulty if difficulty in DIFFICULTY else "medium"
    slots, minutes, marks = plan_slots(info, selected)
    slots = _order(slots)
    pid = uuid.uuid4().hex[:10]
    with _jobs_lock:
        for old in [k for k, j in JOBS.items() if time.time() - j["started"] > 3600]:
            JOBS.pop(old, None)
        JOBS[pid] = {"owner": username, "status": "running", "done": 0, "total": len(slots), "error": "", "started": time.time()}
    threading.Thread(target=_run_job, args=(pid, username, info, difficulty, selected, slots, minutes), daemon=True).start()
    return pid


def _run_job(pid, username, info, difficulty, selected, slots, minutes):
    job = JOBS[pid]
    try:
        deadline_at = time.time() + JOB_LIMIT
        by_subject = {}
        for i, s in enumerate(slots):
            by_subject.setdefault(s["subject"], []).append((i, s))
        subjects = {s["name"]: s for s in info["subjects"]}
        batches = []
        for name, items in by_subject.items():
            for k in range(0, len(items), BATCH):
                batches.append((subjects[name], items[k:k + BATCH]))
        questions = {}
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = [pool.submit(_write_batch, info, subj, difficulty, batch, job, deadline_at) for subj, batch in batches]
            for f in futures:
                questions.update(f.result())
        paper = _assemble(pid, username, info, difficulty, selected, slots, questions, minutes)
        storage.put_doc("exampaper", f"{username}__{pid}", paper)
        _index_add(username, paper)
        with _jobs_lock:
            job["status"] = "ready"
    except (ExamError, groq.GroqError) as err:
        with _jobs_lock:
            job.update(status="error", error=str(err))
    except Exception as err:  # noqa: BLE001
        traceback.print_exc()
        with _jobs_lock:
            job.update(status="error", error="Something went wrong while writing the paper. Please try again.")
        _log(f"job {pid} crashed: {err!r}")


def _assemble(pid, username, info, difficulty, selected, slots, questions, minutes):
    pattern = info["pattern"]
    neg = pattern.get("negative", {})
    out, warnings = [], []
    for i, slot in enumerate(slots):
        q = questions.get(i)
        if not q:
            continue
        no = len(out) + 1
        q.update({"no": no, "id": f"q{no}", "section": slot["section"], "subject": slot["subject"], "marks": slot["marks"],
                  "neg": round(slot["marks"] * float(neg.get(slot["type"], 0)), 4)})
        out.append(q)
    if len(out) < len(slots):
        warnings.append(f"{len(slots) - len(out)} question(s) could not be written and were left out.")
    if not out:
        raise ExamError("The AI could not write the paper. Please try again in a minute.")
    sections = []
    for q in out:
        if q["section"] not in sections:
            sections.append(q["section"])
    total = sum(q["marks"] for q in out)
    minutes = minutes if len(out) == len(slots) else max(15, int(round(minutes * len(out) / len(slots) / 5.0)) * 5)
    return {"id": pid, "owner": username, "exam_id": info["exam_id"], "exam": info["exam"], "paper": info["paper"],
            "title": info["title"] + (" - Full paper" if not selected else " - " + ", ".join(selected)[:80]),
            "difficulty": difficulty, "subjects": selected or [], "full": not selected, "duration_min": minutes,
            "total_marks": total, "negative": neg, "sections": sections, "questions": out, "warnings": warnings,
            "origin": info["origin"], "created": _now(), "rules": pattern.get("rules", [])}


def job_status(username, pid):
    job = JOBS.get(pid)
    if job and job["owner"] == username:
        return {"status": job["status"], "done": min(job["done"], job["total"]), "total": job["total"], "error": job["error"]}
    paper = storage.get_doc("exampaper", f"{username}__{pid}")
    if paper:
        return {"status": "ready", "done": len(paper["questions"]), "total": len(paper["questions"]), "error": ""}
    return {"status": "error", "done": 0, "total": 0, "error": "This paper was not finished (the server restarted). Please generate it again."}


# ============================================================ 4. papers, attempts, grading

def load_paper(username, pid):
    paper = storage.get_doc("exampaper", f"{username}__{pid}")
    if not paper:
        raise ExamError("Paper not found.", 404)
    return paper


def public_paper(paper):
    """What the exam hall may see: no answers, no explanations, no topics."""
    qs = [{k: v for k, v in q.items() if k not in ("answer", "explanation", "topic")} for q in paper["questions"]]
    return {"id": paper["id"], "title": paper["title"], "exam": paper["exam"], "difficulty": paper["difficulty"],
            "duration_min": paper["duration_min"], "total_marks": paper["total_marks"], "sections": paper["sections"],
            "rules": paper.get("rules", []), "questions": qs}


def paper_meta(username, pid):
    """What the instructions screen shows before the clock starts (no questions, no answers)."""
    paper = load_paper(username, pid)
    secs, kinds = {}, {}
    for q in paper["questions"]:
        row = secs.setdefault(q["section"], {"name": q["section"], "questions": 0, "marks": 0})
        row["questions"] += 1
        row["marks"] += q["marks"]
        kinds[q["type"]] = kinds.get(q["type"], 0) + 1
    running = None
    for entry in list_papers(username):
        if entry["id"] == pid:
            for a in entry["attempts"]:
                if a.get("status") == "running":
                    att = _load_attempt(username, a["id"])
                    left = att["started"] + att["duration_s"] - time.time()
                    if att["status"] == "running" and left > -20:
                        running = {"attempt_id": att["id"], "remaining_s": max(0, int(left))}
    return {"id": paper["id"], "title": paper["title"], "exam": paper["exam"], "difficulty": paper["difficulty"],
            "duration_min": paper["duration_min"], "total_marks": paper["total_marks"], "questions": len(paper["questions"]),
            "sections": list(secs.values()), "types": kinds, "rules": paper.get("rules", []), "warnings": paper.get("warnings", []),
            "running": running}


def _index_add(username, paper):
    with storage.update_doc("examindex", username, lambda: {"papers": []}) as doc:
        doc["papers"].insert(0, {"id": paper["id"], "title": paper["title"], "exam": paper["exam"], "paper": paper["paper"],
                                 "difficulty": paper["difficulty"], "created": paper["created"], "full": paper["full"],
                                 "questions": len(paper["questions"]), "total_marks": paper["total_marks"],
                                 "duration_min": paper["duration_min"], "attempts": []})
        doc["papers"] = doc["papers"][:INDEX_LIMIT]


def list_papers(username):
    return (storage.get_doc("examindex", username) or {}).get("papers", [])


def _index_attempt(username, pid, entry):
    with storage.update_doc("examindex", username, lambda: {"papers": []}) as doc:
        for p in doc["papers"]:
            if p["id"] == pid:
                p["attempts"] = [a for a in p["attempts"] if a["id"] != entry["id"]] + [entry]
                p["attempts"] = p["attempts"][-5:]


def _load_attempt(username, aid):
    attempt = storage.get_doc("examattempt", f"{username}__{aid}")
    if not attempt:
        raise ExamError("Attempt not found.", 404)
    return attempt


def _save_attempt(username, attempt):
    storage.put_doc("examattempt", f"{username}__{attempt['id']}", attempt)


def start_attempt(username, pid):
    """Start the exam, or continue the running one. The timer lives on the server, so a refresh cannot reset it."""
    paper = load_paper(username, pid)
    for entry in list_papers(username):
        if entry["id"] == pid:
            for a in entry["attempts"]:
                if a.get("status") == "running":
                    attempt = _load_attempt(username, a["id"])
                    if attempt["status"] == "running":
                        if time.time() >= attempt["started"] + attempt["duration_s"] + 20:
                            return submit_attempt(username, attempt["id"], None) and _view(username, attempt["id"], paper)
                        return _view(username, attempt["id"], paper)
    attempt = {"id": uuid.uuid4().hex[:10], "paper_id": pid, "status": "running", "started": time.time(),
               "duration_s": int(paper["duration_min"]) * 60, "answers": {}, "marked": [], "visited": [], "time_spent": {},
               "current": 0, "result": None}
    _save_attempt(username, attempt)
    _index_attempt(username, pid, {"id": attempt["id"], "status": "running", "started": _now(), "score": None, "max": paper["total_marks"]})
    return _view(username, attempt["id"], paper)


def _view(username, aid, paper):
    attempt = _load_attempt(username, aid)
    if attempt["status"] != "running":
        return {"status": attempt["status"], "attempt_id": aid}
    return {"status": "running", "attempt_id": aid, "server_now": time.time(), "started": attempt["started"],
            "duration_s": attempt["duration_s"], "paper": public_paper(paper),
            "saved": {k: attempt[k] for k in ("answers", "marked", "visited", "time_spent", "current")}}


def _clean_answers(paper, answers):
    qs = {q["id"]: q for q in paper["questions"]}
    out = {}
    for qid, val in (answers if isinstance(answers, dict) else {}).items():
        q = qs.get(qid)
        if not q or val in (None, "", []):
            continue
        if q["type"] == "mcq":
            v = str(val).strip().upper()[:1]
            if v in list("ABCD"):
                out[qid] = v
        elif q["type"] == "msq":
            vals = sorted({str(v).strip().upper()[:1] for v in (val if isinstance(val, list) else [val])} & set("ABCD"))
            if vals:
                out[qid] = vals
        else:
            v = str(val).replace(" ", "")[:20]
            if re.fullmatch(r"-?\d*\.?\d*", v) and re.search(r"\d", v):
                out[qid] = v
    return out


def save_attempt(username, aid, data):
    attempt = _load_attempt(username, aid)
    if attempt["status"] != "running":
        return {"status": attempt["status"]}
    paper = load_paper(username, attempt["paper_id"])
    ids = {q["id"] for q in paper["questions"]}
    attempt["answers"] = _clean_answers(paper, data.get("answers"))
    attempt["marked"] = [q for q in (data.get("marked") or []) if q in ids][:300]
    attempt["visited"] = [q for q in (data.get("visited") or []) if q in ids][:300]
    spent = {}
    for qid, sec in (data.get("time_spent") or {}).items():
        try:
            if qid in ids:
                spent[qid] = max(0, min(int(float(sec)), 20000))
        except (TypeError, ValueError):
            pass
    attempt["time_spent"] = spent
    try:
        attempt["current"] = max(0, min(int(data.get("current") or 0), len(ids) - 1))
    except (TypeError, ValueError):
        attempt["current"] = 0
    _save_attempt(username, attempt)
    return {"status": "running", "server_now": time.time()}


def submit_attempt(username, aid, data):
    attempt = _load_attempt(username, aid)
    if attempt["status"] == "submitted":
        return attempt["result"]
    paper = load_paper(username, attempt["paper_id"])
    if data is not None:
        save_attempt(username, aid, data)
        attempt = _load_attempt(username, aid)
    used = min(attempt["duration_s"], int(time.time() - attempt["started"]))
    result = grade(paper, attempt["answers"], attempt["time_spent"], used)
    attempt.update(status="submitted", result=result, submitted=_now())
    _save_attempt(username, attempt)
    _index_attempt(username, paper["id"], {"id": aid, "status": "submitted", "started": _now(), "score": result["score"], "max": result["max"]})
    return result


def get_result(username, aid):
    attempt = _load_attempt(username, aid)
    if attempt["status"] != "submitted":
        raise ExamError("This exam is still running.", 409)
    paper = load_paper(username, attempt["paper_id"])
    return {"result": attempt["result"], "paper": {"id": paper["id"], "title": paper["title"], "difficulty": paper["difficulty"],
            "duration_min": paper["duration_min"], "exam": paper["exam"]}}


def _grade_one(q, ans):
    """(status, marks) for one question. status: correct, wrong, skipped."""
    if ans in (None, "", []):
        return "skipped", 0.0
    if q["type"] == "mcq":
        return ("correct", float(q["marks"])) if ans == q["answer"][0] else ("wrong", -float(q["neg"]) or 0.0)
    if q["type"] == "msq":
        return ("correct", float(q["marks"])) if sorted(ans) == sorted(q["answer"]) else ("wrong", -float(q["neg"]) or 0.0)
    try:
        value = float(ans)
    except ValueError:
        return "wrong", 0.0
    low, high = q["answer"]["low"], q["answer"]["high"]
    if low == high:
        tol = 0.0 if float(low).is_integer() else 0.01
        low, high = low - tol, high + tol
    return ("correct", float(q["marks"])) if low - 1e-9 <= value <= high + 1e-9 else ("wrong", 0.0)


def _blank(name, **extra):
    return dict({"name": name, "questions": 0, "attempted": 0, "correct": 0, "wrong": 0, "skipped": 0, "marks": 0.0,
                 "max_marks": 0.0, "time_s": 0}, **extra)


def _acc(rows):
    for r in rows:
        r["marks"], r["max_marks"] = round(r["marks"], 2), round(r["max_marks"], 2)
        r["accuracy"] = round(100.0 * r["correct"] / r["attempted"], 1) if r["attempted"] else None
        r["avg_time_s"] = round(r["time_s"] / r["questions"]) if r["questions"] else 0
    return rows


def grade(paper, answers, time_spent, used_s):
    answers = _clean_answers(paper, answers)
    total, max_marks, negative = 0.0, 0.0, 0.0
    by_sec, by_sub, by_topic, by_type, review = {}, {}, {}, {}, []
    for q in paper["questions"]:
        status, got = _grade_one(q, answers.get(q["id"]))
        total += got
        max_marks += q["marks"]
        negative += -got if got < 0 else 0
        spent = int(time_spent.get(q["id"], 0))
        rows = [by_sec.setdefault(q["section"], _blank(q["section"])),
                by_sub.setdefault(q["subject"], _blank(q["subject"])),
                by_topic.setdefault((q["subject"], q["topic"]), _blank(q["topic"], subject=q["subject"])),
                by_type.setdefault(q["type"], _blank(q["type"].upper()))]
        for r in rows:
            r["questions"] += 1
            r["max_marks"] += q["marks"]
            r["marks"] += got
            r["time_s"] += spent
            if status != "skipped":
                r["attempted"] += 1
            r[status] += 1
        review.append({"no": q["no"], "id": q["id"], "section": q["section"], "subject": q["subject"], "topic": q["topic"],
                       "type": q["type"], "marks": q["marks"], "neg": q["neg"], "status": status, "got": round(got, 2),
                       "your": answers.get(q["id"]), "correct": q["answer"], "explanation": q["explanation"],
                       "text": q["text"], "options": q["options"], "time_s": spent})
    attempted = sum(1 for r in review if r["status"] != "skipped")
    correct = sum(1 for r in review if r["status"] == "correct")
    result = {"score": round(total, 2), "max": round(max_marks, 2), "negative_total": round(negative, 2),
              "attempted": attempted, "correct": correct, "wrong": attempted - correct, "skipped": len(review) - attempted,
              "questions": len(review), "accuracy": round(100.0 * correct / attempted, 1) if attempted else None,
              "percent": round(100.0 * total / max_marks, 1) if max_marks else 0, "time_used_s": used_s,
              "by_section": _acc(list(by_sec.values())), "by_subject": _acc(list(by_sub.values())),
              "by_topic": sorted(_acc(list(by_topic.values())), key=lambda r: (r["accuracy"] is None, r["accuracy"] or 0)),
              "by_type": _acc(list(by_type.values())), "review": review}
    result["insights"] = _insights(result)
    return result


def _insights(r):
    tips = []
    if r["negative_total"] >= 1:
        tips.append(f"Wrong answers cost you {r['negative_total']} marks. Guess in MCQs only after removing at least two options.")
    if r["questions"] and r["skipped"] / r["questions"] > 0.3:
        tips.append(f"You left {r['skipped']} of {r['questions']} questions unanswered. Practise the order: easy 1-mark questions first, hard ones later.")
    subs = [s for s in r["by_subject"] if s["attempted"] >= 2 and s["accuracy"] is not None]
    if subs:
        best, worst = max(subs, key=lambda s: s["accuracy"]), min(subs, key=lambda s: s["accuracy"])
        if best is not worst:
            tips.append(f"Strongest subject: {best['name']} ({best['accuracy']}% accuracy). Weakest: {worst['name']} ({worst['accuracy']}%).")
    weak = [t for t in r["by_topic"] if t["attempted"] >= 1 and t["accuracy"] is not None and t["accuracy"] < 50][:4]
    if weak:
        tips.append("Revise first: " + "; ".join(f"{t['name']} ({t['subject']})" for t in weak) + ".")
    slow = [s for s in r["by_subject"] if s["questions"] >= 3 and s["avg_time_s"] > 0]
    if slow:
        s = max(slow, key=lambda x: x["avg_time_s"])
        tips.append(f"You spent the most time per question in {s['name']} (about {s['avg_time_s'] // 60} min {s['avg_time_s'] % 60} s each).")
    nat = next((t for t in r["by_type"] if t["name"] == "NAT"), None)
    if nat and nat["attempted"] >= 2 and nat["accuracy"] is not None and nat["accuracy"] < 40:
        tips.append("Numerical (NAT) answers were weak: practise exact calculations and check the rounding asked in the question.")
    return tips


# ============================================================ 5. study plan

def prepare_course(username, profile, info, days, hours):
    """One ready study plan for the whole paper: every subject is a module, every syllabus topic a lesson, with a day-by-day schedule."""
    name = info["title"]
    existing = next((c for c in storage.list_courses(owner=username) if (c.get("exam") or {}).get("key") == _key(info["exam_id"], info["paper"], info["paper_name"])), None)
    if existing:
        return existing, False
    modules = []
    for i, s in enumerate(info["subjects"]):
        modules.append({"title": s["name"], "level": "Intermediate", "goal": f"Cover the {info['exam']} syllabus of {s['name']}.",
                        "topics": [{"title": t, "summary": f"{s['name']} topic from the {info['exam']} syllabus.", "minutes": 45} for t in s["topics"]]})
    title, description, modules = cl.normalize_syllabus({"title": name, "description": f"Complete {name} preparation: every subject and topic of the syllabus, planned day by day, with a final mock test.", "modules": modules})
    course = cl.new_course(name, "intermediate", hours, days, title, description, modules)
    course.update({"owner": username, "language": "en", "school": {"program": info["exam"], "desc": name},
                   "exam": {"key": _key(info["exam_id"], info["paper"], info["paper_name"]), "exam_id": info["exam_id"], "paper": info["paper"]}})
    course["schedule"] = cl.build_local_schedule(course)
    storage.save_course(course)
    return course, True
