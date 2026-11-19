"""Course rules: validating Groq output, schedules, mastery, and adaptive revision."""
import re
import uuid
from datetime import date, datetime, timedelta

from .groq import GroqError

LEVEL_TAGS = ("Basic", "Intermediate", "Advanced")
ITEM_TYPES = ("learn", "practice", "quiz", "revise", "test")
DEFAULT_MINUTES = {"quiz": 15, "practice": 25, "revise": 20, "test": 30}
ITEM_LABEL = {"learn": "Learn", "practice": "Practice", "quiz": "Quick quiz", "revise": "Revise"}
WEAK_BELOW = 60


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _s(value, limit):
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _minutes(value, default=45):
    try:
        return max(15, min(120, int(float(value))))
    except (TypeError, ValueError):
        return default


# ---------- syllabus ----------

def normalize_syllabus(raw):
    if isinstance(raw, list):
        raw = {"modules": raw}
    if not isinstance(raw, dict) or not isinstance(raw.get("modules"), list):
        raise GroqError("Groq did not return a syllabus. Please try again.")

    mods = raw["modules"]
    modules, topic_no = [], 0
    for index, mod in enumerate(mods):
        if not isinstance(mod, dict):
            continue
        title = _s(mod.get("title"), 90)
        topics_raw = mod.get("topics")
        if not title or not isinstance(topics_raw, list):
            continue
        level = str(mod.get("level", "")).strip().title()
        if level not in LEVEL_TAGS:
            position = index / max(1, len(mods))
            level = LEVEL_TAGS[0] if position < 0.34 else LEVEL_TAGS[1] if position < 0.67 else LEVEL_TAGS[2]
        topics = []
        for item in topics_raw:
            if isinstance(item, str):
                item = {"title": item}
            if not isinstance(item, dict) or not _s(item.get("title"), 100):
                continue
            topic_no += 1
            topics.append({
                "id": f"t{topic_no}",
                "title": _s(item.get("title"), 100),
                "summary": _s(item.get("summary"), 220),
                "minutes": _minutes(item.get("minutes")),
                "status": "todo",
                "mastery": None,
                "attempts": 0,
            })
        if topics:
            modules.append({
                "id": f"m{len(modules) + 1}", "title": title, "level": level,
                "goal": _s(mod.get("goal"), 200), "topics": topics,
            })
    if not modules:
        raise GroqError("Groq returned an empty syllabus. Please try again.")
    return _s(raw.get("title"), 100), _s(raw.get("description"), 400), modules


def normalize_syllabus_with_roadmap(raw):
    title, description, modules = normalize_syllabus(raw)
    raw_roadmap = raw.get("roadmap") if isinstance(raw, dict) and isinstance(raw.get("roadmap"), dict) else {}
    roadmap = {
        "phases": raw_roadmap.get("phases", [
            {"phase": 1, "name": "Foundations & Prerequisites", "goal": "Establish strong foundational definitions and core principles."},
            {"phase": 2, "name": "Core Principles & Mechanics", "goal": "Master step-by-step working mechanisms and laws."},
            {"phase": 3, "name": "Advanced Theory & Complex Problem Solving", "goal": "Tackle advanced derivations, algorithms and edge cases."},
            {"phase": 4, "name": "Synthesis, Real-world Applications & Mastery", "goal": "Apply knowledge to practical implementations and exam preparation."}
        ]),
        "prerequisites": raw_roadmap.get("prerequisites", ["Fundamental analytical reasoning and domain prerequisites"]),
        "learning_outcomes": raw_roadmap.get("learning_outcomes", [f"Deep conceptual and practical mastery of {title or 'the subject'}"])
    }
    return title, description, modules, roadmap


def new_course(subject, level, hours, days, title, description, modules, roadmap=None):
    return {
        "id": uuid.uuid4().hex[:8],
        "subject": subject,
        "title": title or subject,
        "description": description,
        "level": level,
        "hours": hours,
        "days": days,
        "created": now_iso(),
        "roadmap": roadmap,
        "modules": modules,
        "schedule": [],
        "lessons": {},
        "chat": {},
        "quizzes": {},
        "_seq": 0,
    }


# ---------- lookups ----------

def all_topics(course):
    return [(m, t) for m in course["modules"] for t in m["topics"]]


def find_topic(course, tid):
    for module, topic in all_topics(course):
        if topic["id"] == tid:
            return module, topic
    return None


def stats(course):
    topics = [t for _, t in all_topics(course)]
    total = len(topics)
    done = sum(1 for t in topics if t["status"] == "done")
    scores = [t["mastery"] for t in topics if t.get("mastery") is not None]
    return {
        "total": total,
        "done": done,
        "percent": round(100 * done / total) if total else 0,
        "mastery": round(sum(scores) / len(scores)) if scores else None,
        "weak": [t for t in topics if t.get("mastery") is not None and t["mastery"] < WEAK_BELOW],
    }


def neighbours(course, tid):
    topics = all_topics(course)
    ids = [t["id"] for _, t in topics]
    i = ids.index(tid)
    prev_id = ids[i - 1] if i > 0 else None
    next_id = ids[i + 1] if i + 1 < len(ids) else None
    return prev_id, next_id


def previous_and_upcoming(course, tid):
    titles = [t["title"] for _, t in all_topics(course)]
    ids = [t["id"] for _, t in all_topics(course)]
    i = ids.index(tid)
    return titles[max(0, i - 5):i], titles[i + 1:i + 4]


def next_topic_id(course, tid):
    ordered = [t for _, t in all_topics(course)]
    ids = [t["id"] for t in ordered]
    start = ids.index(tid) + 1
    for topic in ordered[start:]:
        if topic["status"] != "done":
            return topic["id"]
    return None


# ---------- schedule ----------

def _make_item(course, kind, topic=None, minutes=None):
    course["_seq"] = course.get("_seq", 0) + 1
    if kind == "test":
        title, topic_id, default = "Final test", None, DEFAULT_MINUTES["test"]
    else:
        title = f"{ITEM_LABEL[kind]}: {topic['title']}"
        topic_id = topic["id"]
        default = topic["minutes"] if kind == "learn" else DEFAULT_MINUTES[kind]
    return {
        "id": f"i{course['_seq']}", "type": kind, "topic_id": topic_id, "title": title,
        "minutes": minutes or default, "done": False,
    }


def _finalize(course, days):
    """Number the days, add dates, and keep progress for topics already finished."""
    start = date.today()
    topic_done = {t["id"]: t["status"] == "done" for _, t in all_topics(course)}
    for number, day in enumerate(days, start=1):
        day["day"] = number
        day["date"] = (start + timedelta(days=number - 1)).isoformat()
        for item in day["items"]:
            if item["type"] == "learn" and topic_done.get(item["topic_id"]):
                item["done"] = True
    return days


def normalize_schedule(raw, course):
    """Turn Groq's schedule into a safe one. Returns None if it can't be trusted."""
    if not isinstance(raw, dict) or not isinstance(raw.get("days"), list):
        return None
    topic_map = {t["id"]: t for _, t in all_topics(course)}
    seen, days = set(), []
    for day in raw["days"][:course["days"]]:
        if not isinstance(day, dict) or not isinstance(day.get("items"), list):
            continue
        items = []
        for entry in day["items"]:
            if not isinstance(entry, dict):
                continue
            kind, tid = entry.get("type"), entry.get("topic_id")
            if kind not in ITEM_TYPES:
                continue
            if kind == "test":
                items.append(_make_item(course, "test"))
                continue
            if tid not in topic_map:
                continue
            if kind == "learn":
                if tid in seen:
                    continue
                seen.add(tid)
            items.append(_make_item(course, kind, topic_map[tid]))
        if items:
            days.append({"focus": _s(day.get("focus"), 120), "tip": _s(day.get("tip"), 200), "items": items})

    if not days or len(seen) != len(topic_map):
        return None
    if len(days) < max(1, int(course["days"] * 0.6)):
        return None
    return _finalize(course, days)


def build_local_schedule(course):
    """Plain, predictable schedule used when Groq's version can't be used."""
    topics = all_topics(course)
    count = len(topics)
    wanted = max(1, course["days"])
    content_days = wanted - 1 if wanted >= 3 else wanted
    content_days = max(1, min(content_days, count))
    base, extra = divmod(count, content_days)

    days, index = [], 0
    for d in range(content_days):
        size = base + (1 if d < extra else 0)
        items, modules_today = [], []
        last_topic = None
        for _ in range(size):
            module, topic = topics[index]
            index += 1
            items.append(_make_item(course, "learn", topic))
            last_topic = topic
            if module["title"] not in modules_today:
                modules_today.append(module["title"])
        if last_topic:
            items.append(_make_item(course, "quiz", last_topic))
        days.append({"focus": " and ".join(modules_today)[:120], "tip": "", "items": items})

    final_items = [_make_item(course, "test")]
    if wanted >= 3 or not days:
        days.append({"focus": "Final test", "tip": "", "items": final_items})
    else:
        days[-1]["items"].extend(final_items)
    return _finalize(course, days)


def current_day_index(course):
    for i, day in enumerate(course.get("schedule", [])):
        if any(not item["done"] for item in day["items"]):
            return i
    return None


def mark_items(course, tid, kinds):
    for day in course.get("schedule", []):
        for item in day["items"]:
            if item["topic_id"] == tid and item["type"] in kinds:
                item["done"] = True


def add_revision(course, tid):
    """Put a revision session on the next study day. Returns that day number."""
    schedule = course.get("schedule", [])
    if not schedule:
        return None
    for day in schedule:
        for item in day["items"]:
            if item["type"] == "revise" and item["topic_id"] == tid and not item["done"]:
                return day["day"]

    current = current_day_index(course)
    target = (current + 1) if current is not None else len(schedule)
    if target >= len(schedule):
        last_date = date.fromisoformat(schedule[-1]["date"])
        schedule.append({
            "day": len(schedule) + 1, "date": (last_date + timedelta(days=1)).isoformat(),
            "focus": "Revision", "tip": "", "items": [],
        })
    _, topic = find_topic(course, tid)
    schedule[target]["items"].insert(0, _make_item(course, "revise", topic))
    return schedule[target]["day"]


# ---------- quizzes and mastery ----------

def normalize_questions(raw, valid_ids, count):
    items = raw.get("questions") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return []
    questions = []
    for q in items:
        if not isinstance(q, dict):
            continue
        text, options = _s(q.get("question"), 400), q.get("options")
        if not text or not isinstance(options, list) or len(options) != 4:
            continue
        options = [re.sub(r"^[A-Da-d][\)\.:]\s+", "", _s(o, 220)) for o in options]
        if not all(options):
            continue
        try:
            answer = int(q.get("answer_index"))
        except (TypeError, ValueError):
            continue
        if not 0 <= answer <= 3:
            continue
        tid = q.get("topic_id")
        if tid not in valid_ids:
            tid = valid_ids[len(questions) % len(valid_ids)]
        questions.append({
            "topic_id": tid, "question": text, "options": options,
            "answer_index": answer, "explanation": _s(q.get("explanation"), 400),
        })
    return questions[:count]


def apply_quiz_result(course, per_topic, kind):
    """per_topic: {topic_id: (correct, total)}. Updates mastery and adds revision when weak."""
    notes, summaries = [], []
    for tid, (correct, total) in per_topic.items():
        found = find_topic(course, tid)
        if not found or not total:
            continue
        _, topic = found
        score = round(100 * correct / total)
        old = topic.get("mastery")
        topic["mastery"] = score if old is None else round(old * 0.4 + score * 0.6)
        topic["attempts"] = topic.get("attempts", 0) + 1
        mark_items(course, tid, ("quiz", "revise"))
        if score < WEAK_BELOW:
            day = add_revision(course, tid)
            if day:
                notes.append(f"You scored {score}% on {topic['title']}, so a revision session was added on day {day}.")
        summaries.append({"id": tid, "title": topic["title"], "score": score, "mastery": topic["mastery"]})
    if kind == "test":
        for day in course.get("schedule", []):
            for item in day["items"]:
                if item["type"] == "test":
                    item["done"] = True
    return summaries, notes
