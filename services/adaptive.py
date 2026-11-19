"""Adaptive Learning Engine: Personalizes student learning paths based on performance,
mastery modeling, spaced repetition decay, and dynamic difficulty adjustment.
"""
from datetime import date, datetime, timedelta
import math
import uuid

from . import course_logic as cl
from . import groq, prompts, storage
from .config import has_api_key


def calculate_retention(last_practice_date_str, base_mastery):
    """
    Ebbinghaus Forgetting Curve model:
    Calculates estimated retention percentage based on days elapsed since last review.
    R = e^(-t / S), where S is stability factor based on base mastery.
    """
    if not last_practice_date_str or base_mastery is None:
        return base_mastery or 0

    try:
        last_d = date.fromisoformat(last_practice_date_str[:10])
        days_elapsed = max(0, (date.today() - last_d).days)
    except Exception:
        return base_mastery

    # Stability factor increases with higher base mastery
    stability = max(5.0, (base_mastery / 10.0) * 4.0)
    retention_factor = math.exp(-days_elapsed / stability)
    current_retention = round(base_mastery * retention_factor)
    return max(10, min(100, current_retention))


def get_mastery_level(score):
    """Categorize score into 4 clear pedagogical mastery tiers."""
    if score is None:
        return {"code": "untested", "label": "Not Started", "emoji": "⚪", "color": "muted", "tier": 0}
    if score >= 80:
        return {"code": "mastered", "label": "Mastered", "emoji": "🌟", "color": "ok", "tier": 3}
    if score >= 60:
        return {"code": "proficient", "label": "Proficient", "emoji": "🚀", "color": "accent", "tier": 2}
    if score >= 40:
        return {"code": "developing", "label": "Developing", "emoji": "📖", "color": "warn", "tier": 1}
    return {"code": "needs_focus", "label": "Needs Focus", "emoji": "⚠️", "color": "bad", "tier": 0}


def get_adaptive_profile(username):
    """
    Build a comprehensive adaptive learning profile for the student:
    - Mastery Matrix (topic-by-topic status across all courses)
    - Retention & Spaced Repetition analysis
    - Identified Weak Spots & Critical Gaps
    - Personalized AI Diagnosis & Next Best Steps
    """
    courses = storage.list_courses(owner=username)
    all_topics_data = []
    weak_topics = []
    proficient_topics = []
    mastered_topics = []
    needs_review = []

    for c in courses:
        for m in c.get("modules", []):
            for t in m.get("topics", []):
                mastery = t.get("mastery")
                attempts = t.get("attempts", 0)
                level = get_mastery_level(mastery)
                
                # Check recent practice date
                last_studied = t.get("last_studied")
                retention = calculate_retention(last_studied, mastery) if mastery is not None else None

                item = {
                    "course_id": c["id"],
                    "course_title": c["subject"],
                    "module_title": m["title"],
                    "topic_id": t["id"],
                    "topic_title": t["title"],
                    "mastery": mastery,
                    "retention": retention,
                    "attempts": attempts,
                    "level": level,
                    "status": t.get("status", "todo")
                }
                all_topics_data.append(item)

                if level["code"] in ("needs_focus", "developing"):
                    weak_topics.append(item)
                elif level["code"] == "proficient":
                    proficient_topics.append(item)
                elif level["code"] == "mastered":
                    mastered_topics.append(item)

                if retention is not None and retention < 55 and mastery is not None and mastery >= 60:
                    needs_review.append(item)

    # Sort weak topics: lowest mastery first
    weak_topics.sort(key=lambda x: x["mastery"] if x["mastery"] is not None else -1)

    total_topics = len(all_topics_data)
    tested_topics = [t for t in all_topics_data if t["mastery"] is not None]
    avg_mastery = round(sum(t["mastery"] for t in tested_topics) / len(tested_topics)) if tested_topics else 0

    # Determine recommended difficulty for new tests
    if avg_mastery >= 75:
        recommended_difficulty = "hard"
        difficulty_label = "Advanced (Analytical & Synthesis)"
    elif avg_mastery >= 50:
        recommended_difficulty = "medium"
        difficulty_label = "Intermediate (Application & Concepts)"
    else:
        recommended_difficulty = "easy"
        difficulty_label = "Foundational (Core Concepts & Hints)"

    # Generate Personalized Recommendations
    recommendations = []
    if weak_topics:
        top_weak = weak_topics[0]
        recommendations.append({
            "type": "targeted_test",
            "priority": "High",
            "icon": "🎯",
            "title": f"Revise {top_weak['topic_title']}",
            "desc": f"Your current mastery is {top_weak['mastery'] or 0}%. Take a 5-question adaptive test to strengthen core concepts.",
            "action_url": f"/courses/{top_weak['course_id']}/test",
            "course_id": top_weak["course_id"],
            "topic_id": top_weak["topic_id"]
        })
    if len(weak_topics) > 1:
        second_weak = weak_topics[1]
        recommendations.append({
            "type": "book_teacher",
            "priority": "Medium",
            "icon": "📖",
            "title": f"Learn with Book Teacher: {second_weak['topic_title']}",
            "desc": "Open the Book Teacher to get an intuitive step-by-step explanation directly from textbook passages.",
            "action_url": "/books"
        })
    if needs_review:
        rev = needs_review[0]
        recommendations.append({
            "type": "spaced_repetition",
            "priority": "Medium",
            "icon": "⏳",
            "title": f"Spaced Repetition: {rev['topic_title']}",
            "desc": f"You previously mastered this, but retention has slipped to ~{rev['retention']}%. Quick 3-minute review recommended.",
            "action_url": f"/courses/{rev['course_id']}/learn/{rev['topic_id']}"
        })

    if not recommendations:
        recommendations.append({
            "type": "explore",
            "priority": "Normal",
            "icon": "🚀",
            "title": "Continue Your Syllabus",
            "desc": "You are performing solidly across all current topics! Continue your daily study plan.",
            "action_url": "/study"
        })

    return {
        "total_topics": total_topics,
        "tested_topics_count": len(tested_topics),
        "average_mastery": avg_mastery,
        "mastery_counts": {
            "mastered": len(mastered_topics),
            "proficient": len(proficient_topics),
            "developing": len([w for w in weak_topics if w["level"]["code"] == "developing"]),
            "needs_focus": len([w for w in weak_topics if w["level"]["code"] == "needs_focus"])
        },
        "recommended_difficulty": recommended_difficulty,
        "difficulty_label": difficulty_label,
        "weak_topics": weak_topics[:8],
        "mastered_topics": mastered_topics[:6],
        "needs_review": needs_review[:5],
        "recommendations": recommendations,
        "matrix": all_topics_data
    }


def generate_adaptive_test(username, course_id=None, count=6, test_type="mixed", language="en"):
    """
    Generates a smart adaptive test dynamically calibrated to the student's weakest areas.
    """
    profile = get_adaptive_profile(username)
    weak = profile.get("weak_topics", [])

    if course_id:
        target_course = storage.load_course(course_id)
        if not target_course:
            raise ValueError("Course not found.")
        course_topics = [t for _, t in cl.all_topics(target_course)]
        # Filter weak topics belonging to this course
        chosen_topics = [w for w in weak if w["course_id"] == course_id]
        if not chosen_topics:
            chosen_topics = [{"topic_id": t["id"], "topic_title": t["title"], "mastery": t.get("mastery", 50)} for t in course_topics[:count]]
    else:
        chosen_topics = weak[:count]
        if not chosen_topics and profile.get("matrix"):
            chosen_topics = profile["matrix"][:count]

    topic_names = [t["topic_title"] for t in chosen_topics[:count]]
    difficulty = profile.get("recommended_difficulty", "medium")

    system = f"""You are the Adaptive Examiner of an intelligent AI learning system.
Create a calibrated test designed to help the student overcome their specific knowledge gaps.

Student Target Topics: {', '.join(topic_names)}
Calibrated Difficulty: {difficulty} (Level adapted to student's current proficiency)
Test Type: {test_type} (Supports both subjective written questions and conceptual MCQs)
Question Count: {count}

Rules:
1. For topics with lower mastery, test the foundational definition or fundamental principle with clear cues.
2. For topics with higher mastery, present application problems or analytical scenarios.
3. Subjective questions must ask for 2-4 sentences of clear reasoning or steps. Max marks: 5.
4. MCQs must have 4 distinct options and an explanation. Max marks: 1.
5. Return ONLY a JSON object:
{{
  "title": "Smart Adaptive Test: Targeted Revision",
  "difficulty": "{difficulty}",
  "total_marks": {count * 3},
  "questions": [
    {{
      "id": "q1",
      "type": "subjective",
      "topic": "...",
      "question": "...",
      "max_marks": 5,
      "expected_points": ["point 1", "point 2"],
      "model_answer": "..."
    }},
    {{
      "id": "q2",
      "type": "mcq",
      "topic": "...",
      "question": "...",
      "options": ["A", "B", "C", "D"],
      "answer_index": 0,
      "max_marks": 1,
      "explanation": "..."
    }}
  ]
}}
{prompts.lang_rule(language)}"""

    prompt = f"Generate {count} adaptive questions covering: {', '.join(topic_names)}"

    if has_api_key():
        raw = groq.generate(prompt, system=system, json_mode=True, temperature=0.5, max_tokens=3500)
    else:
        # Offline fallback
        raw = {
            "title": "Smart Adaptive Test: Targeted Revision",
            "difficulty": difficulty,
            "total_marks": 10,
            "questions": [
                {
                    "id": "q1",
                    "type": "subjective",
                    "topic": topic_names[0] if topic_names else "Core Concepts",
                    "question": f"Explain the fundamental mechanism and importance of {topic_names[0] if topic_names else 'this subject'}.",
                    "max_marks": 5,
                    "expected_points": ["Definition", "Working mechanism", "Practical example"],
                    "model_answer": "Students should clearly define the principle, outline the sequence of events or rules, and provide a concrete example."
                },
                {
                    "id": "q2",
                    "type": "mcq",
                    "topic": topic_names[-1] if topic_names else "General Concepts",
                    "question": "Which of the following represents the optimal approach to solving problems in this domain?",
                    "options": ["Step-by-step conceptual derivation", "Guessing without checking units", "Memorizing without understanding", "Skipping validation"],
                    "answer_index": 0,
                    "max_marks": 1,
                    "explanation": "Structured conceptual understanding ensures consistent problem-solving accuracy."
                }
            ]
        }

    test_id = f"atest_{uuid.uuid4().hex[:8]}"
    questions = raw.get("questions", [])
    clean_questions = []
    total_marks = 0
    for idx, q in enumerate(questions, start=1):
        q_type = q.get("type", "subjective")
        marks = int(q.get("max_marks", 5 if q_type == "subjective" else 1))
        total_marks += marks
        item = {
            "id": f"q{idx}",
            "type": q_type,
            "topic": q.get("topic", "General"),
            "question": q.get("question", f"Question {idx}"),
            "max_marks": marks
        }
        if q_type == "mcq":
            item["options"] = q.get("options", ["A", "B", "C", "D"])[:4]
            item["answer_index"] = int(q.get("answer_index", 0))
            item["explanation"] = q.get("explanation", "")
        else:
            item["expected_points"] = q.get("expected_points", ["Accuracy", "Clarity"])
            item["model_answer"] = q.get("model_answer", "")
        clean_questions.append(item)

    test_record = {
        "test_id": test_id,
        "title": raw.get("title", "Smart Adaptive Test"),
        "difficulty": difficulty,
        "total_marks": total_marks,
        "questions": clean_questions,
        "created": datetime.now().isoformat(timespec="seconds")
    }
    storage.put_doc("tests", test_id, test_record)

    # Return public version
    public_questions = []
    for q in clean_questions:
        pq = {
            "id": q["id"],
            "type": q["type"],
            "topic": q.get("topic"),
            "question": q["question"],
            "max_marks": q["max_marks"]
        }
        if q["type"] == "mcq":
            pq["options"] = q["options"]
        public_questions.append(pq)

    return {
        "test_id": test_id,
        "title": test_record["title"],
        "difficulty": difficulty,
        "total_marks": total_marks,
        "questions": public_questions
    }
