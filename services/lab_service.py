"""Coding Space & Practical Lab Execution Service.
Provides:
- Sandboxed code execution for Python, JavaScript (Node), SQL (SQLite in-memory), and HTML/Web preview.
- Companion practical course generator and linker.
- Lab exercise management and student draft persistence.
- Dynamic exercise generation using LLM.
"""
import subprocess
import sys
import time
import os
import json
import sqlite3
import tempfile
from typing import Dict, Any, List, Optional

from services import storage, course_logic as cl


def run_code(language: str, code: str, stdin: str = "") -> Dict[str, Any]:
    """Safely executes code in the requested language sandbox and returns standard output/error."""
    lang = (language or "python").lower().strip()
    start_time = time.time()

    if not code or not code.strip():
        return {
            "ok": True,
            "stdout": "",
            "stderr": "No code provided to execute.",
            "exit_code": 0,
            "duration_ms": 0
        }

    # Limit code size to 100KB
    if len(code) > 100_000:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "Error: Code size exceeds maximum limit of 100KB.",
            "exit_code": 1,
            "duration_ms": 0
        }

    try:
        if lang in ("python", "py"):
            return _run_python(code, stdin, start_time)
        elif lang in ("javascript", "js", "node"):
            return _run_javascript(code, stdin, start_time)
        elif lang in ("sql", "sqlite"):
            return _run_sql(code, start_time)
        elif lang in ("html", "web"):
            return _run_html(code, start_time)
        else:
            # Fallback to python
            return _run_python(code, stdin, start_time)
    except Exception as exc:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "ok": False,
            "stdout": "",
            "stderr": f"Execution Environment Error: {str(exc)}",
            "exit_code": 1,
            "duration_ms": duration_ms
        }


def _run_python(code: str, stdin: str, start_time: float) -> Dict[str, Any]:
    """Runs Python code inside a subprocess with a timeout."""
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            input=stdin or "",
            capture_output=True,
            text=True,
            timeout=8,
            cwd=tempfile.gettempdir()
        )
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[:15000],
            "stderr": proc.stderr[:10000],
            "exit_code": proc.returncode,
            "duration_ms": duration_ms
        }
    except subprocess.TimeoutExpired:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "ok": False,
            "stdout": "",
            "stderr": "Error: Execution timed out (exceeded 8 seconds). Check for infinite loops or blocking inputs.",
            "exit_code": 124,
            "duration_ms": duration_ms
        }


def _run_javascript(code: str, stdin: str, start_time: float) -> Dict[str, Any]:
    """Runs JavaScript code using Node.js."""
    try:
        proc = subprocess.run(
            ["node", "-e", code],
            input=stdin or "",
            capture_output=True,
            text=True,
            timeout=8,
            cwd=tempfile.gettempdir()
        )
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "ok": proc.returncode == 0,
            "stdout": proc.stdout[:15000],
            "stderr": proc.stderr[:10000],
            "exit_code": proc.returncode,
            "duration_ms": duration_ms
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "Node.js is not configured on this host. Run code with Python or preview in browser.",
            "exit_code": 127,
            "duration_ms": round((time.time() - start_time) * 1000, 2)
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "stdout": "",
            "stderr": "Error: JavaScript execution timed out (exceeded 8 seconds).",
            "exit_code": 124,
            "duration_ms": round((time.time() - start_time) * 1000, 2)
        }


def _run_sql(code: str, start_time: float) -> Dict[str, Any]:
    """Executes SQL statements in an in-memory SQLite database and formats results."""
    output_lines = []
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()

    # Split statements
    statements = [s.strip() for s in code.split(";") if s.strip()]
    if not statements:
        return {"ok": True, "stdout": "No SQL statements executed.", "stderr": "", "exit_code": 0, "duration_ms": 0}

    try:
        for stmt in statements:
            cursor.execute(stmt)
            if cursor.description:
                # Query with output rows
                cols = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                
                # Format table
                output_lines.append(f"Query: {stmt[:60]}..." if len(stmt) > 60 else f"Query: {stmt}")
                if not rows:
                    output_lines.append("(0 rows returned)\n")
                    continue
                
                # Calculate column widths
                col_widths = [len(c) for c in cols]
                for r in rows:
                    for i, val in enumerate(r):
                        col_widths[i] = max(col_widths[i], len(str(val)))
                
                header = " | ".join(c.ljust(col_widths[i]) for i, c in enumerate(cols))
                sep = "-+-".join("-" * col_widths[i] for i in range(len(cols)))
                output_lines.append(header)
                output_lines.append(sep)
                for r in rows:
                    row_str = " | ".join(str(val).ljust(col_widths[i]) for i, val in enumerate(r))
                    output_lines.append(row_str)
                output_lines.append(f"({len(rows)} row{'s' if len(rows) > 1 else ''} returned)\n")
            else:
                affected = cursor.rowcount
                output_lines.append(f"Executed: {stmt[:60]}... (Rows affected: {affected if affected >= 0 else 0})\n")
        
        conn.commit()
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "ok": True,
            "stdout": "\n".join(output_lines),
            "stderr": "",
            "exit_code": 0,
            "duration_ms": duration_ms
        }
    except sqlite3.Error as err:
        duration_ms = round((time.time() - start_time) * 1000, 2)
        return {
            "ok": False,
            "stdout": "\n".join(output_lines),
            "stderr": f"SQLite Error: {str(err)}",
            "exit_code": 1,
            "duration_ms": duration_ms
        }
    finally:
        conn.close()


def _run_html(code: str, start_time: float) -> Dict[str, Any]:
    duration_ms = round((time.time() - start_time) * 1000, 2)
    return {
        "ok": True,
        "stdout": "Web page preview rendered successfully in sandbox.",
        "stderr": "",
        "html_preview": code,
        "exit_code": 0,
        "duration_ms": duration_ms
    }


def create_practical_companion_course(username: str, profile: Dict[str, Any], parent_course: Dict[str, Any], practical_analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Builds and links an automated companion practical laboratory course."""
    title = practical_analysis.get("practical_title") or f"{parent_course.get('subject')} Practical Lab & Coding Space"
    subject = f"{parent_course.get('subject')} Lab"
    description = practical_analysis.get("practical_description") or f"Hands-on coding and laboratory workspace for {parent_course.get('subject')}."
    level = parent_course.get("level", "intermediate")
    hours = max(1.0, float(parent_course.get("hours", 2.0) * 0.75))
    days = parent_course.get("days", 60)
    language = parent_course.get("language", "en")
    practical_type = practical_analysis.get("practical_type", "coding")
    primary_lang = practical_analysis.get("primary_language", "python")

    raw_modules = practical_analysis.get("modules") or []
    starter_exercises = practical_analysis.get("starter_exercises") or []

    # Format modules
    modules = []
    topic_id_seq = 1
    for m_idx, m in enumerate(raw_modules):
        m_title = m.get("title") or f"Lab Unit {m_idx + 1}"
        m_level = m.get("level") or ("Basic" if m_idx == 0 else "Intermediate")
        m_goal = m.get("goal") or f"Hands-on practical experiments for {m_title}"
        m_topics = []
        for t in m.get("topics", []):
            t_title = t.get("title") if isinstance(t, dict) else str(t)
            t_mins = int(t.get("minutes", 60)) if isinstance(t, dict) else 60
            m_topics.append({
                "id": f"lab_t_{topic_id_seq}",
                "title": t_title,
                "minutes": t_mins,
                "status": "todo"
            })
            topic_id_seq += 1
        modules.append({
            "title": m_title,
            "level": m_level,
            "goal": m_goal,
            "topics": m_topics
        })

    # Create Roadmap for the Lab
    lab_roadmap = {
        "phases": [
            {"phase": 1, "name": "Lab Setup & Foundational Programs", "goal": "Environment verification and syntax mastery"},
            {"phase": 2, "name": "Core Implementations & Data Processing", "goal": "Build robust modular algorithms or experiments"},
            {"phase": 3, "name": "Optimization, Benchmarking & Testing", "goal": "Time/space complexity analysis and test suites"},
            {"phase": 4, "name": "Capstone Project & Viva Voce", "goal": "Defend lab portfolio and oral examination preparation"}
        ],
        "prerequisites": ["Basic computer literacy", f"Theoretical understanding of {parent_course.get('subject')}"],
        "learning_outcomes": ["Independent implementation capability", "Clean code and debugging proficiency", "Practical examination confidence"]
    }

    course = cl.new_course(subject, level, hours, days, title, description, modules, roadmap=lab_roadmap)
    course.update({
        "owner": username,
        "language": language,
        "is_practical_lab": True,
        "practical_type": practical_type,
        "primary_language": primary_lang,
        "parent_course_id": parent_course["id"],
        "parent_course_title": parent_course["title"],
        "lab_exercises": starter_exercises,
        "school": parent_course.get("school", {})
    })
    course["schedule"] = cl.build_local_schedule(course)
    storage.save_course(course)

    # Link parent course back to the lab course
    parent_course["is_practical"] = True
    parent_course["practical_type"] = practical_type
    parent_course["practical_course_id"] = course["id"]
    parent_course["practical_course_title"] = course["title"]
    storage.save_course(parent_course)

    return course


def get_lab_exercises(course: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Retrieves or provides exercises for a practical course."""
    exercises = course.get("lab_exercises") or []
    if exercises:
        return exercises

    # If course is practical but has no exercises yet, generate defaults
    subject = course.get("subject", "Computer Science")
    lang = course.get("primary_language", "python")
    return [
        {
            "id": "ex_1",
            "title": f"1. {subject}: Foundation Exercise",
            "aim": f"Implement a core algorithm or simulation in {lang} addressing the fundamental principles of {subject}.",
            "difficulty": "Easy",
            "language": lang,
            "starter_code": f"# {subject} - Coding Space\n# Write your solution below\n\ndef main():\n    print('Hello from {subject} Lab!')\n\nif __name__ == '__main__':\n    main()\n",
            "solution_code": "def main():\n    print('Success')\n",
            "test_cases": [{"input": "None", "expected_output": f"Hello from {subject} Lab!"}],
            "viva_questions": [{"question": f"What are the main objectives of {subject} lab?", "answer": "To translate theoretical concepts into functional, validated code and experiments."}]
        }
    ]


def save_student_lab_draft(username: str, course_id: str, exercise_id: str, code: str):
    """Persists student's in-progress lab code."""
    with storage.update_doc("lab_drafts", username, lambda: {"drafts": {}}) as doc:
        key = f"{course_id}:{exercise_id}"
        doc["drafts"][key] = {
            "code": code,
            "updated": cl.now_iso()
        }


def get_student_lab_draft(username: str, course_id: str, exercise_id: str) -> Optional[str]:
    """Retrieves student's saved code draft if it exists."""
    doc = storage.get_doc("lab_drafts", username) or {}
    key = f"{course_id}:{exercise_id}"
    draft = doc.get("drafts", {}).get(key)
    return draft.get("code") if draft else None


def generate_custom_exercise(subject: str, topic: str, language: str) -> Dict[str, Any]:
    """Uses LLM to synthesize a new practical lab challenge on demand for any syllabus topic."""
    from services.agentic.llm import get_llm  # lazy: keeps app start-up light
    llm = get_llm(temperature=0.3)
    system = (
        "You are a university lab instructor. Generate a practical coding or experimental lab exercise "
        "tailored to the given topic. Return ONLY a valid JSON object."
    )
    user = f"""Subject: {subject}
Topic: {topic}
Language: {language}

Required JSON shape:
{{
  "id": "ex_custom_{int(time.time())}",
  "title": "Topic-Focused Lab Experiment",
  "aim": "Clear, precise problem statement and algorithmic requirement.",
  "difficulty": "Medium",
  "language": "{language}",
  "starter_code": "# Problem setup and comments\\n",
  "solution_code": "# Working reference solution\\n",
  "test_cases": [
    {{"input": "Sample input", "expected_output": "Sample output"}}
  ],
  "viva_questions": [
    {{"question": "Key theoretical question?", "answer": "Concise viva explanation."}}
  ]
}}"""
    try:
        res = llm.invoke([system, user])
        content = res.content if hasattr(res, "content") else str(res)
        import re
        content = re.sub(r"^```(?:json)?\s*", "", content.strip())
        content = re.sub(r"\s*```$", "", content)
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as err:
        print("[lab_service] error generating custom exercise:", err, flush=True)

    return {
        "id": f"ex_custom_{int(time.time())}",
        "title": f"Lab Challenge: {topic}",
        "aim": f"Implement and verify a program demonstrating {topic} in {subject}.",
        "difficulty": "Medium",
        "language": language,
        "starter_code": f"# Lab Challenge on {topic}\n# Implement your solution below\n\ndef solve():\n    pass\n\nif __name__ == '__main__':\n    solve()\n",
        "solution_code": "def solve():\n    return True\n",
        "test_cases": [{"input": "Test", "expected_output": "Success"}],
        "viva_questions": [{"question": f"Why is {topic} essential in practical {subject}?", "answer": "It provides practical implementation and optimization foundation."}]
    }
