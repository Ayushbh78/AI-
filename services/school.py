"""The "real school" layer: student profile, subject suggestions, study records, report card and library.

Everything is stored with storage.get_doc / put_doc, so it lives in Supabase when deployed and in the
data folder when run locally. Courses themselves are still the existing course documents.
"""
import hashlib
import re
import uuid
from datetime import date, datetime, timedelta

from . import course_logic as cl
from . import groq, prompts, storage, websearch
from .config import has_api_key

# ---------- what the onboarding form asks ----------
# type "select": pick one.  type "combo": pick a suggestion or type your own.  showIf: only for these values of another field.
CLASSES = [f"Class {n}" for n in range(1, 13)]
CATALOG = [
    {"id": "school", "label": "School", "icon": "🏫", "blurb": "Class 1 to 12",
     "fields": [
         {"id": "level", "label": "Your class", "type": "select", "options": CLASSES, "default": "Class 10"},
         {"id": "board", "label": "Board", "type": "combo",
          "options": ["CBSE", "ICSE / ISC", "UP Board", "Bihar Board", "Maharashtra Board", "Rajasthan Board",
                      "MP Board", "Gujarat Board", "Tamil Nadu Board", "Karnataka Board", "IB / Cambridge"]},
         {"id": "field", "label": "Stream", "type": "combo", "showIf": {"level": ["Class 11", "Class 12"]},
          "options": ["Science (PCM)", "Science (PCB)", "Science (PCMB)", "Commerce", "Arts / Humanities"]},
     ]},
    {"id": "diploma", "label": "Diploma / ITI", "icon": "🛠️", "blurb": "Polytechnic, ITI, certificate",
     "fields": [
         {"id": "level", "label": "Course", "type": "combo", "options": ["Diploma", "Polytechnic", "ITI", "Certificate course"]},
         {"id": "field", "label": "Branch / trade", "type": "combo",
          "options": ["Computer Engineering", "Mechanical Engineering", "Civil Engineering", "Electrical Engineering",
                      "Electronics Engineering", "Electrician", "Fitter"]},
         {"id": "term", "label": "Year", "type": "select", "options": ["Year 1", "Year 2", "Year 3"]},
     ]},
    {"id": "ug", "label": "Graduation", "icon": "🎓", "blurb": "B.Tech, B.Sc, BCA, B.Com, BA ...",
     "fields": [
         {"id": "level", "label": "Degree", "type": "combo",
          "options": ["B.Tech / B.E.", "BCA", "B.Sc", "B.Com", "BA", "BBA", "B.Pharm", "LLB", "MBBS", "B.Ed", "B.Arch"]},
         {"id": "field", "label": "Branch / specialization", "type": "combo",
          "options": ["Computer Science", "Information Technology", "AI & Data Science", "Electronics & Communication",
                      "Electrical", "Mechanical", "Civil", "Physics", "Chemistry", "Mathematics", "Economics",
                      "Accounting & Finance", "Management", "English", "History", "Political Science"]},
         {"id": "term", "label": "Year and semester", "type": "combo",
          "options": [f"Year {y}, Semester {s}" for y, s in
                      ((1, 1), (1, 2), (2, 3), (2, 4), (3, 5), (3, 6), (4, 7), (4, 8))]},
         {"id": "institution", "label": "University / college (optional)", "type": "text"},
     ]},
    {"id": "pg", "label": "Post graduation", "icon": "📚", "blurb": "M.Tech, M.Sc, MBA, MCA, MA ...",
     "fields": [
         {"id": "level", "label": "Degree", "type": "combo",
          "options": ["M.Tech / M.E.", "MCA", "M.Sc", "MBA", "M.Com", "MA", "LLM", "M.Pharm", "MD / MS", "PhD"]},
         {"id": "field", "label": "Specialization", "type": "combo",
          "options": ["Computer Science", "Data Science", "Artificial Intelligence", "VLSI / Embedded", "Finance",
                      "Marketing", "Human Resources", "Operations", "Physics", "Chemistry", "Mathematics", "Economics"]},
         {"id": "term", "label": "Year and semester", "type": "combo",
          "options": ["Year 1, Semester 1", "Year 1, Semester 2", "Year 2, Semester 3", "Year 2, Semester 4"]},
         {"id": "institution", "label": "University / college (optional)", "type": "text"},
     ]},
    {"id": "exam", "label": "Competitive exam", "icon": "🎯", "blurb": "JEE, NEET, UPSC, SSC, GATE, CAT ...",
     "fields": [
         {"id": "level", "label": "Exam", "type": "combo",
          "options": ["JEE Main & Advanced", "NEET UG", "UPSC Civil Services", "SSC CGL", "GATE", "CAT", "CLAT",
                      "Banking (IBPS / SBI)", "NDA", "CUET", "State PSC", "Railway (RRB)"]},
         {"id": "field", "label": "Branch / optional subject (if any)", "type": "text"},
         {"id": "term", "label": "Target year or attempt", "type": "text"},
     ]},
    {"id": "skill", "label": "Skills & hobbies", "icon": "💡", "blurb": "Coding, languages, career skills",
     "fields": [
         {"id": "level", "label": "Your level", "type": "select", "options": ["Beginner", "Intermediate", "Advanced"]},
         {"id": "field", "label": "What do you want to learn?", "type": "combo",
          "options": ["Programming", "Data Science", "Web Development", "Spoken English", "Digital Marketing",
                      "Finance & Investing", "Design", "Electronics"]},
     ]},
]
STAGES = {s["id"]: s for s in CATALOG}
LANGUAGES = ("en",)   # English only
KINDS = ("Core", "Elective", "Practical", "Skill", "Exam prep")

# Used when the AI cannot be reached, so onboarding never dead-ends.
FALLBACK = {
    "school": [("Mathematics", "Core"), ("Science", "Core"), ("English", "Core"), ("Hindi", "Core"),
               ("Social Science", "Core"), ("Computer Science", "Elective"), ("General Knowledge", "Skill")],
    "diploma": [("Engineering Mathematics", "Core"), ("Engineering Physics", "Core"), ("Programming Basics", "Core"),
                ("Communication Skills", "Skill"), ("Workshop Practice", "Practical")],
    "ug": [("Engineering Mathematics", "Core"), ("Data Structures and Algorithms", "Core"),
           ("Artificial Intelligence", "Elective"), ("Machine Learning", "Elective"),
           ("Communication Skills", "Skill"), ("Aptitude and Reasoning", "Skill")],
    "pg": [("Research Methods", "Core"), ("Advanced Mathematics", "Core"), ("Machine Learning", "Elective"),
           ("Academic Writing", "Skill")],
    "exam": [("Quantitative Aptitude", "Exam prep"), ("Logical Reasoning", "Exam prep"), ("General Awareness", "Exam prep"),
             ("English Language", "Exam prep"), ("Mock Test Practice", "Exam prep")],
    "skill": [("Programming Basics", "Skill"), ("Problem Solving", "Skill"), ("Communication Skills", "Skill")],
}


def _clean(value, limit=80):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


# ---------- profile ----------

def get_profile(username):
    return storage.get_doc("profile", username)


def describe(p):
    """One sentence about the student, used in every AI prompt."""
    stage, level, field, term = p.get("stage"), p.get("level", ""), p.get("field", ""), p.get("term", "")
    board, inst = p.get("board", ""), p.get("institution", "")
    if stage == "school":
        text = f"School student in {level}" + (f", {board} board" if board else "") + (f", {field} stream" if field else "")
    elif stage == "diploma":
        text = f"{level or 'Diploma'} student" + (f" in {field}" if field else "") + (f", {term}" if term else "")
    elif stage == "ug":
        text = f"Undergraduate student doing {level or 'a bachelor degree'}" + (f" in {field}" if field else "") + \
               (f", {term}" if term else "") + (f" at {inst}" if inst else "")
    elif stage == "pg":
        text = f"Postgraduate student doing {level or 'a master degree'}" + (f" in {field}" if field else "") + \
               (f", {term}" if term else "") + (f" at {inst}" if inst else "")
    elif stage == "exam":
        text = f"Competitive exam aspirant preparing for {level or 'an exam'}" + (f" ({field})" if field else "") + \
               (f", target {term}" if term else "")
    else:
        text = f"Self-learner ({level or 'beginner'} level)" + (f" who wants to learn {field}" if field else "")
    return text + "."


def short_label(p):
    """Short badge text such as 'B.Tech / B.E., Year 2, Semester 3' for the dashboard."""
    bits = [p.get("level"), p.get("field") if p.get("stage") in ("ug", "pg", "diploma", "school") else "", p.get("term")]
    return ", ".join(b for b in bits if b)[:90]


def level_for(p):
    stage, lvl, term = p.get("stage"), str(p.get("level", "")), str(p.get("term", ""))
    if stage == "school":
        m = re.search(r"(\d+)", lvl)
        return "beginner" if (int(m.group(1)) if m else 8) <= 8 else "mid"
    if stage in ("ug", "diploma"):
        m = re.search(r"(\d)", term)
        year = int(m.group(1)) if m else 1
        return "beginner" if year <= 1 else "mid" if year <= 3 else "advanced"
    if stage == "pg":
        return "advanced"
    if stage == "skill":
        return {"intermediate": "mid", "advanced": "advanced"}.get(lvl.lower(), "beginner")
    return "mid"


def save_profile(username, data):
    stage = _clean(data.get("stage"), 12)
    if stage not in STAGES:
        raise ValueError("Choose what you are studying: school, graduation, post graduation and so on.")
    fields = {f["id"]: f for f in STAGES[stage]["fields"]}
    profile = {"stage": stage}
    for fid in ("level", "field", "term", "board", "institution"):
        profile[fid] = _clean(data.get(fid), 80) if fid in fields else ""
    first = STAGES[stage]["fields"][0]
    if not profile["level"] and first["id"] == "level":
        raise ValueError(f"Please fill in: {first['label']}.")
    profile["goal"] = _clean(data.get("goal"), 200)
    try:
        profile["daily_hours"] = max(0.5, min(12, float(data.get("daily_hours") or 2)))
        profile["plan_days"] = max(7, min(365, int(float(data.get("plan_days") or 60))))
    except (TypeError, ValueError):
        raise ValueError("Study hours and days must be numbers.")
    language = data.get("language")
    with storage.update_doc("profile", username) as p:
        p.update(profile)
        p["language"] = language if language in LANGUAGES else p.get("language", "en")
        p.pop("skipped", None)
        p.setdefault("created", cl.now_iso())
        p["updated"] = cl.now_iso()
        p["onboarded"] = True
        saved = dict(p)
    return saved


def skip_onboarding(username):
    with storage.update_doc("profile", username) as p:
        if not p.get("onboarded"):
            p["skipped"] = True
        p["language"] = "en"   # older profiles that chose Hindi are shown in English now
        return dict(p)


def set_language(username, language):
    if language not in LANGUAGES:
        raise ValueError("Unknown language.")
    with storage.update_doc("profile", username) as p:
        p["language"] = language
    return language


def language_of(username):
    return "en"   # English only (no database read needed)


# ---------- subject suggestions ----------

def _normalize_subjects(raw):
    items = raw.get("subjects") if isinstance(raw, dict) else raw
    out, seen = [], set()
    for item in items or []:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict):
            continue
        name = _clean(item.get("name"), 70)
        if len(name) < 2 or name.lower() in seen:
            continue
        seen.add(name.lower())
        kind = _clean(item.get("kind"), 20).title()
        out.append({"name": name, "kind": kind if kind in KINDS else "Core", "why": _clean(item.get("why"), 140)})
    return out[:18]


def suggest(profile, refresh=False):
    """Subjects for this student. Returns (list, source) where source is 'ai' or 'offline'."""
    desc = describe(profile)
    key = hashlib.sha1((desc + profile.get("goal", "")).lower().encode()).hexdigest()[:24]
    if not refresh:
        cached = storage.get_doc("suggest", key)
        if cached and cached.get("subjects"):
            return cached["subjects"], "ai"
    if has_api_key():
        web = websearch.search(f"{desc} syllabus subjects list", general=True)
        system, prompt = prompts.suggest_subjects(desc, profile.get("goal", ""), "en", web)
        try:
            raw = groq.generate(prompt, system=system, json_mode=True, temperature=0.4, max_tokens=3000)
            subjects = _normalize_subjects(raw)
            if len(subjects) >= 3:
                storage.put_doc("suggest", key, {"subjects": subjects, "desc": desc, "created": cl.now_iso()})
                return subjects, "ai"
        except groq.GroqError as err:
            print("[school] subject suggestions fell back to the built-in list:", err, flush=True)
    fallback = FALLBACK.get(profile.get("stage"), FALLBACK["skill"])
    return [{"name": n, "kind": k, "why": ""} for n, k in fallback], "offline"


# ---------- study records (activity log) ----------

def log(username, kind, title, minutes=0, score=None, course_id=None, course_title=None):
    """Remember one thing the student did. Never raises: records must not break studying."""
    try:
        with storage.update_doc("activity", username, lambda: {"events": []}) as doc:
            doc["events"].append({"t": cl.now_iso(), "kind": kind, "title": _clean(title, 120), "minutes": int(minutes or 0),
                                  "score": score, "course_id": course_id, "course": _clean(course_title, 100)})
            del doc["events"][:-600]
    except Exception as err:  # noqa: BLE001
        print("[school] could not save activity:", err, flush=True)


def activity(username):
    events = (storage.get_doc("activity", username) or {}).get("events", [])
    by_day = {}
    for e in events:
        by_day[e["t"][:10]] = by_day.get(e["t"][:10], 0) + (e.get("minutes") or 0)
    today = date.today()
    last14 = []
    for i in range(13, -1, -1):
        d = today - timedelta(days=i)
        last14.append({"date": d.isoformat(), "label": d.strftime("%a")[0] if i else "Today", "day": d.strftime("%d %b"),
                       "minutes": by_day.get(d.isoformat(), 0)})
    active = {e["t"][:10] for e in events}
    cursor = today if today.isoformat() in active else today - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in active:
        streak += 1
        cursor -= timedelta(days=1)
    week = sum(by_day.get((today - timedelta(days=i)).isoformat(), 0) for i in range(7))
    return {"events": events, "last14": last14, "streak": streak, "week_minutes": week,
            "total_minutes": sum(by_day.values()), "recent": events[-15:][::-1], "active_days": len(active)}


# ---------- grades, dashboard, report card ----------

def grade(mastery):
    if mastery is None:
        return "-"
    return "A+" if mastery >= 90 else "A" if mastery >= 80 else "B+" if mastery >= 70 else "B" if mastery >= 60 \
        else "C" if mastery >= 50 else "D"


def my_courses(username):
    return storage.list_courses(owner=username)


def subject_row(c):
    st = cl.stats(c)
    idx = cl.current_day_index(c)
    day = c["schedule"][idx] if idx is not None and c.get("schedule") else None
    next_item = next((i for i in day["items"] if not i["done"]), None) if day else None
    results = [q["result"] for q in (c.get("quizzes") or {}).values() if q.get("result")]
    return {"course": c, "stats": st, "grade": grade(st["mastery"]), "day": day, "next_item": next_item,
            "finished": bool(c.get("schedule")) and idx is None, "tests": len(results),
            "best": max((r["percent"] for r in results), default=None)}


def dashboard(username):
    rows = [subject_row(c) for c in my_courses(username)]
    rows.sort(key=lambda r: r["course"].get("created", ""))
    total = sum(r["stats"]["total"] for r in rows)
    done = sum(r["stats"]["done"] for r in rows)
    scores = [r["stats"]["mastery"] for r in rows if r["stats"]["mastery"] is not None]
    act = activity(username)
    weak = [(r["course"], t) for r in rows for t in r["stats"]["weak"]][:6]
    overall = {"subjects": len(rows), "total": total, "done": done, "percent": round(100 * done / total) if total else 0,
               "mastery": round(sum(scores) / len(scores)) if scores else None}
    overall["grade"] = grade(overall["mastery"])
    return {"rows": rows, "overall": overall, "activity": act, "weak": weak, "badges": badges(rows, act, overall)}


def badges(rows, act, overall):
    best = max((r["best"] or 0 for r in rows), default=0)
    earned = [
        ("🚀", "First step", "Complete your first topic", overall["done"] >= 1),
        ("📘", "Ten topics", "Complete 10 topics", overall["done"] >= 10),
        ("🔥", "3-day streak", "Study 3 days in a row", act["streak"] >= 3),
        ("⚡", "Week warrior", "Study 7 days in a row", act["streak"] >= 7),
        ("🏆", "Quiz ace", "Score 90% or more in a quiz", best >= 90),
        ("🎓", "Subject finished", "Complete every topic of a subject",
         any(r["stats"]["total"] and r["stats"]["done"] == r["stats"]["total"] for r in rows)),
    ]
    return [{"icon": i, "name": n, "how": h, "earned": ok} for i, n, h, ok in earned]


def report_card(username):
    """Everything for the Progress page: per-subject records with topic-by-topic status and test history."""
    data = dashboard(username)
    for row in data["rows"]:
        c = row["course"]
        quizzes = sorted(((q["created"], q["kind"], q["result"]["percent"], q["result"]["score"], q["result"]["total"])
                          for q in (c.get("quizzes") or {}).values() if q.get("result")), reverse=True)
        row["history"] = [{"when": w[:10], "kind": "Test" if k == "test" else "Quiz", "percent": p, "score": s, "total": t}
                          for w, k, p, s, t in quizzes[:8]]
    return data


# ---------- enrolling in a subject ----------

def split_hours(profile, count):
    total = float(profile.get("daily_hours") or 2)
    return max(0.5, min(6, round(total / max(1, count) * 2) / 2))


def build_course(username, profile, name, hours, days):
    """Create one course for a chosen subject using LangGraph Syllabus Agent."""
    desc, level = describe(profile), level_for(profile)
    language = profile.get("language", "en")
    level_text = prompts.LEVEL_TEXT.get(level if level in prompts.LEVEL_TEXT else "intermediate", "a learner at this level")

    from services.agentic import syllabus_agent_graph

    state = {
        "subject": name,
        "desc": desc,
        "level_text": level_text,
        "hours": float(hours or 2.0),
        "days": int(days or 60),
        "language": language,
        "web_research": [],
        "syllabus_raw": {},
        "title": "",
        "description": "",
        "modules": [],
        "roadmap": {}
    }

    graph_res = syllabus_agent_graph.invoke(state)

    title = graph_res.get("title") or name
    description = graph_res.get("description") or f"Comprehensive course on {name}"
    modules = graph_res.get("modules") or []
    roadmap = graph_res.get("roadmap") or {}

    course = cl.new_course(name, level, hours, days, title, description, modules, roadmap=roadmap)
    course.update({"owner": username, "language": language, "school": {"program": short_label(profile), "desc": desc}})
    course["schedule"] = cl.build_local_schedule(course)
    storage.save_course(course)
    return course


def enrolled_names(username):
    return {c.get("subject", "").strip().lower() for c in my_courses(username)}


# ---------- library ----------

LIBRARY_LIMIT = 150
LIB_TYPES = ("notes", "book", "paper")


def lib_add(username, kind, title, content, meta=None):
    item = {"id": uuid.uuid4().hex[:10], "type": kind, "title": _clean(title, 140) or "Untitled",
            "content": content, "meta": meta or {}, "created": cl.now_iso(), "bookmarked": False}
    with storage.update_doc("library", username, lambda: {"items": []}) as doc:
        doc["items"].insert(0, item)
        if len(doc["items"]) > LIBRARY_LIMIT:
            keep = [i for i in doc["items"] if i.get("bookmarked")]
            rest = [i for i in doc["items"] if not i.get("bookmarked")]
            doc["items"] = sorted(keep + rest[:max(0, LIBRARY_LIMIT - len(keep))], key=lambda i: i["created"], reverse=True)
    return item


def lib_list(username):
    items = (storage.get_doc("library", username) or {}).get("items", [])
    return [{k: v for k, v in i.items() if k != "content"} for i in items]


def lib_get(username, item_id):
    for item in (storage.get_doc("library", username) or {}).get("items", []):
        if item["id"] == item_id:
            return item
    return None


def lib_delete(username, item_id):
    with storage.update_doc("library", username, lambda: {"items": []}) as doc:
        doc["items"] = [i for i in doc["items"] if i["id"] != item_id]


def lib_bookmark(username, item_id):
    with storage.update_doc("library", username, lambda: {"items": []}) as doc:
        for item in doc["items"]:
            if item["id"] == item_id:
                item["bookmarked"] = not item.get("bookmarked")
                return item["bookmarked"]
    return None


# ---------- exam paper clean-up ----------

def normalize_paper(raw, marks):
    if not isinstance(raw, dict) or not isinstance(raw.get("sections"), list):
        raise groq.GroqError("Groq did not return a question paper. Please try again.")
    sections, number, total = [], 0, 0
    for sec in raw["sections"]:
        if not isinstance(sec, dict) or not isinstance(sec.get("questions"), list):
            continue
        questions = []
        for q in sec["questions"]:
            if not isinstance(q, dict) or not _clean(q.get("text"), 900):
                continue
            kind = q.get("type") if q.get("type") in ("mcq", "short", "long", "numerical") else "short"
            options = q.get("options") if isinstance(q.get("options"), list) else None
            if kind == "mcq":
                options = [re.sub(r"^[A-Da-d][\)\.:]\s+", "", _clean(o, 220)) for o in (options or [])]
                if len(options) != 4 or not all(options):
                    kind, options = "short", None
            else:
                options = None
            try:
                mark = max(0.5, min(30, float(q.get("marks") or 1)))
            except (TypeError, ValueError):
                mark = 1
            mark = int(mark) if float(mark).is_integer() else mark
            number += 1
            total += mark
            questions.append({"no": number, "type": kind, "text": str(q["text"]).strip()[:900], "marks": mark,
                              "options": options, "answer": str(q.get("answer") or "").strip()[:1500]})
        if questions:
            sections.append({"name": _clean(sec.get("name"), 90) or "Section", "instructions": _clean(sec.get("instructions"), 220),
                             "questions": questions})
    if not sections:
        raise groq.GroqError("Groq returned an empty question paper. Please try again.")
    instructions = [_clean(i, 200) for i in (raw.get("instructions") or []) if _clean(i, 200)][:8]
    return {"title": _clean(raw.get("title"), 120), "subtitle": _clean(raw.get("subtitle"), 140),
            "instructions": instructions, "sections": sections, "total_marks": total, "asked_marks": marks,
            "question_count": number}
