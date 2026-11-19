"""Pages and API for the "school" features: onboarding, My Study, Progress, Notes, Books, Exam Paper, Library.

Registered from app.py with init(app, ...). Uses the same login, error handling and AI helpers as the rest of the app.
"""
from pathlib import Path

from flask import Blueprint, g, jsonify, redirect, render_template, request, url_for

from services import course_logic as cl
from services import adaptive, book_teacher, exam_data, groq, lab_service, prompts, rag, school, storage, test_evaluator, websearch
from services import knowledge as kb
from services.config import has_api_key, has_search_key

bp = Blueprint("school", __name__)
_deps = {}

def init(app, **deps):
    _deps.update(deps)
    app.register_blueprint(bp)

    @app.template_filter("mins")
    def mins_filter(value):
        value = int(value or 0)
        return f"{value // 60}h {value % 60}m" if value >= 60 else f"{value}m"

    @app.template_filter("when")
    def when_filter(value):
        from datetime import date, datetime
        try:
            moment = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return value or ""
        days = (date.today() - moment.date()).days
        label = "Today" if days == 0 else "Yesterday" if days == 1 else moment.strftime("%d %b")
        return f"{label}, {moment.strftime('%I:%M %p').lstrip('0').lower()}"

    @app.context_processor
    def school_context():
        return {"lang": "en", "tr": (lambda text: text)}   # the app is English only


def _user():
    return _deps["current_user"]()


def _err(message, status=400):
    return _deps["ApiError"](message, status)


def _json():
    return request.get_json(silent=True) or {}


def _text(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _lang(value, profile=None):
    return "en"   # the app is English only


def _need_ai():
    if not has_api_key():
        raise _err("The AI key is not set on the server, so this tool cannot run. Add GROQ_API_KEY and try again.", 400)


# ---------- pages ----------

@bp.get("/welcome")
def welcome():
    user = _user()
    profile = school.get_profile(user["username"]) or {}
    mode = request.args.get("mode", "")
    if mode == "subjects" and not profile.get("onboarded"):
        mode = ""
    return render_template("onboarding.html", catalog=school.CATALOG, profile=profile, mode=mode,
                           boot={"catalog": school.CATALOG, "profile": profile, "mode": mode, "ai": has_api_key()})


@bp.get("/study")
def study():
    user = _user()
    profile = school.get_profile(user["username"]) or {}
    return render_template("study.html", profile=profile, badge=school.short_label(profile),
                           data=school.dashboard(user["username"]))


@bp.get("/progress")
def progress():
    user = _user()
    profile = school.get_profile(user["username"]) or {}
    return render_template("progress.html", profile=profile, badge=school.short_label(profile),
                           data=school.report_card(user["username"]))


def _tool_context(user):
    profile = school.get_profile(user["username"]) or {}
    courses = school.my_courses(user["username"])
    ideas = []
    for c in courses:
        for _, t in cl.all_topics(c):
            if t["status"] != "done":
                ideas.append({"topic": t["title"], "subject": c["subject"]})
                break
    return {"profile": profile, "target": school.short_label(profile),
            "subjects": [c["subject"] for c in courses], "ideas": ideas[:6], "language": profile.get("language", "en"),
            "has_ai": has_api_key(), "has_web": has_search_key()}


@bp.get("/notes")
def notes_page():
    return render_template("notes.html", ctx=_tool_context(_user()))


@bp.get("/books")
def books_page():
    return render_template("books.html", ctx=_tool_context(_user()))


@bp.get("/exam")
def exam_page():
    ctx = _tool_context(_user())
    ctx["catalog"] = [{"id": e["id"], "name": e["name"], "full": e["full"], "icon": e["icon"], "paper_label": e["paper_label"],
                       "papers": e["papers"]} for e in exam_data.EXAMS]
    return render_template("paper.html", ctx=ctx)


@bp.get("/library")
def library_page():
    return render_template("library.html", items=school.lib_list(_user()["username"]))


# ---------- profile, language ----------

@bp.post("/api/school/profile")
def api_profile():
    try:
        profile = school.save_profile(_user()["username"], _json())
    except ValueError as err:
        raise _err(str(err))
    return jsonify(ok=True, profile=profile)


@bp.post("/api/school/skip")
def api_skip():
    school.skip_onboarding(_user()["username"])
    return jsonify(ok=True)


# ---------- subjects ----------

@bp.post("/api/school/suggest")
def api_suggest():
    user = _user()
    profile = school.get_profile(user["username"])
    if not profile or not profile.get("stage"):
        raise _err("Tell us what you study first.")
    subjects, source = school.suggest(profile, refresh=bool(_json().get("refresh")))
    enrolled = school.enrolled_names(user["username"])
    for s in subjects:
        s["enrolled"] = s["name"].strip().lower() in enrolled
    builtin = [{"id": sid, "name": name, "enrolled": name.strip().lower() in enrolled} for sid, name in kb.subject_options()]
    return jsonify(subjects=subjects, source=source, builtin=builtin, summary=school.describe(profile),
                   hours=profile.get("daily_hours", 2), days=profile.get("plan_days", 60), ai=has_api_key())


@bp.post("/api/school/enroll")
def api_enroll():
    """Create the course for ONE chosen subject. The page calls this once per subject so it can show progress."""
    user = _user()
    profile = school.get_profile(user["username"])
    if not profile or not profile.get("stage"):
        raise _err("Tell us what you study first.")
    data = _json()
    name = _text(data.get("name"), 80)
    if len(name) < 2:
        raise _err("Enter a subject name.")
    if name.lower() in school.enrolled_names(user["username"]):
        raise _err(f"You are already enrolled in {name}.", 409)
    try:
        count = max(1, min(12, int(data.get("count") or 1)))
    except (TypeError, ValueError):
        count = 1
    hours = school.split_hours(profile, count)
    days = int(profile.get("plan_days") or 60)
    builtin = data.get("builtin")

    if builtin and kb.has_subject(builtin) and not has_api_key():
        # Built-in subjects used only when offline without an AI key
        level = school.level_for(profile)
        title, description, modules = kb.build_course(builtin, level)
        course = cl.new_course(kb.subject_name(builtin), level, hours, days, title, description, modules)
        course["engine"], course["kb_subject"] = "rote", builtin
        course.update({"owner": user["username"], "language": profile.get("language", "en"),
                       "school": {"program": school.short_label(profile), "desc": school.describe(profile)}})
        course["schedule"] = cl.build_local_schedule(course)
        storage.save_course(course)
    else:
        _need_ai()
        course = school.build_course(user["username"], profile, name, hours, days)

    # Check if subject has a practical/lab requirement; if so, auto-enroll companion practical course
    practical_course = None
    is_practical = False
    try:
        from services.agentic import practical_agent_graph
        from services import lab_service

        practical_state = {
            "subject": name,
            "desc": school.describe(profile),
            "level_text": school.level_for(profile),
            "is_practical": False,
            "practical_type": "none",
            "practical_title": "",
            "practical_description": "",
            "primary_language": "python",
            "reasoning": "",
            "modules": [],
            "starter_exercises": []
        }
        practical_analysis = practical_agent_graph.invoke(practical_state)
        if practical_analysis.get("is_practical"):
            is_practical = True
            practical_course = lab_service.create_practical_companion_course(
                user["username"], profile, course, practical_analysis
            )
            school.log(user["username"], "enrolled", f"Auto-enrolled companion practical lab: {practical_course['subject']}",
                       course_id=practical_course["id"], course_title=practical_course["title"])
    except Exception as err:
        print("[school_routes] Error in practical auto-enrollment:", err, flush=True)

    school.log(user["username"], "enrolled", f"Enrolled in {course['subject']}", course_id=course["id"],
               course_title=course["title"])
    
    return jsonify(
        ok=True,
        id=course["id"],
        title=course["title"],
        is_practical=is_practical,
        practical_course={
            "id": practical_course["id"],
            "title": practical_course["title"],
            "type": practical_course.get("practical_type", "coding"),
            "language": practical_course.get("primary_language", "python")
        } if practical_course else None
    )


# ---------- Topic Notes ----------

@bp.post("/api/notes")
def api_notes():
    user = _user()
    data = _json()
    topic = _text(data.get("topic"), 160)
    if len(topic) < 2:
        raise _err("Type a topic first, for example: Photosynthesis or Binary Search Trees.")
    profile = school.get_profile(user["username"]) or {}
    target = _text(data.get("target"), 140) or school.describe(profile).rstrip(".")
    depth = "detailed" if data.get("depth") == "detailed" else "quick"
    language = _lang(data.get("language"), profile)
    _need_ai()
    web = websearch.search(f"{topic} {target} notes explained") if has_search_key() else []
    system, prompt = prompts.notes(topic, target, depth, language, web)
    text = groq.generate(prompt, system=system, temperature=0.5, max_tokens=5000).strip()
    item = school.lib_add(user["username"], "notes", topic, text,
                          {"target": target, "language": language, "depth": depth, "web": bool(web)})
    school.log(user["username"], "notes", f"Notes: {topic}")
    return jsonify(ok=True, id=item["id"], title=topic, markdown=text, web=bool(web))


# ---------- Book Summarizer ----------

def _book_excerpt(upload):
    name = Path(upload.filename).name[:80]
    ext = Path(name).suffix.lower()
    if ext not in (".pdf", ".txt", ".md"):
        raise _err("Upload a PDF, TXT or MD file.")
    try:
        pages = rag.extract(upload.stream, ext)
    except ValueError as err:
        raise _err(str(err))
    except Exception:
        raise _err("That file could not be read. Try another PDF or a text file.")
    text = " ".join(" ".join(t.split()) for _, t in pages).strip()
    if len(text) < 200:
        raise _err("No readable text found in that file. Scanned PDFs (pictures of pages) are not supported.")
    if len(text) > 12000:    # keep the beginning, the middle and the end so the whole book is represented
        mid = len(text) // 2
        text = text[:5000] + "\n[...]\n" + text[mid - 1750:mid + 1750] + "\n[...]\n" + text[-3500:]
    return Path(name).stem.replace("_", " ").replace("-", " "), text


@bp.post("/api/books")
def api_books():
    user = _user()
    if request.files.get("file"):
        form, upload = request.form, request.files["file"]
        fallback_title, excerpt = _book_excerpt(upload)
    else:
        form, fallback_title, excerpt = _json(), "", None
    title = _text(form.get("title"), 140) or _text(fallback_title, 140)
    if len(title) < 2:
        raise _err("Type the book name, or upload the book as a PDF.")
    author = _text(form.get("author"), 100)
    style = "chapterwise" if form.get("style") == "chapterwise" else "short"
    profile = school.get_profile(user["username"]) or {}
    language = _lang(form.get("language"), profile)
    _need_ai()
    web = websearch.search(f"{title} {author} book summary chapters key ideas", general=True) if has_search_key() else []
    system, prompt = prompts.book(title, author, style, language, web, excerpt)
    text = groq.generate(prompt, system=system, temperature=0.4, max_tokens=5000).strip()
    item = school.lib_add(user["username"], "book", title, text,
                          {"author": author, "style": style, "language": language, "uploaded": bool(excerpt)})
    school.log(user["username"], "book", f"Book: {title}")
    return jsonify(ok=True, id=item["id"], title=title, markdown=text)


# ---------- Exam Paper ----------

@bp.post("/api/paper")
def api_paper():
    user = _user()
    data = _json()
    subject = _text(data.get("subject"), 100)
    if len(subject) < 2:
        raise _err("Choose or type a subject.")
    topics = _text(data.get("topics"), 300)
    pattern = _text(data.get("pattern"), 140)
    profile = school.get_profile(user["username"]) or {}
    try:
        marks = _deps["clamp"](int(float(data.get("marks") or 50)), 10, 100)
        minutes = _deps["clamp"](int(float(data.get("minutes") or 90)), 20, 200)
    except (TypeError, ValueError):
        raise _err("Marks and time must be numbers.")
    difficulty = data.get("difficulty") if data.get("difficulty") in ("easy", "medium", "hard") else "medium"
    language = _lang(data.get("language"), profile)
    _need_ai()
    web = websearch.search(f"{subject} {pattern} sample question paper pattern marking scheme", general=True) \
        if has_search_key() and pattern else []
    system, prompt = prompts.paper(subject, topics, pattern or school.describe(profile).rstrip("."), marks, minutes,
                                   difficulty, language, web)
    raw = groq.generate(prompt, system=system, json_mode=True, temperature=0.5, max_tokens=7000)
    paper = school.normalize_paper(raw, marks)
    paper.update({"minutes": minutes, "difficulty": difficulty, "subject": subject})
    item = school.lib_add(user["username"], "paper", f"{subject} paper ({paper['total_marks']} marks)", paper,
                          {"subject": subject, "pattern": pattern, "marks": paper["total_marks"], "language": language})
    school.log(user["username"], "paper", f"Paper: {subject}")
    return jsonify(ok=True, id=item["id"], paper=paper)


# ---------- Library ----------

@bp.get("/api/library")
def api_library():
    return jsonify(items=school.lib_list(_user()["username"]))


@bp.get("/api/library/<item_id>")
def api_library_item(item_id):
    item = school.lib_get(_user()["username"], item_id)
    if not item:
        raise _err("That item was deleted.", 404)
    return jsonify(item)


@bp.post("/api/library/<item_id>/bookmark")
def api_library_bookmark(item_id):
    state = school.lib_bookmark(_user()["username"], item_id)
    if state is None:
        raise _err("That item was deleted.", 404)
    return jsonify(ok=True, bookmarked=state)


@bp.delete("/api/library/<item_id>")
def api_library_delete(item_id):
    school.lib_delete(_user()["username"], item_id)
    return jsonify(ok=True)


# ---------- Book Teacher (RAG Classroom) ----------

@bp.get("/api/books/list")
def api_books_list():
    user = _user()
    return jsonify(books=book_teacher.list_books(user["username"]))


@bp.post("/api/books/upload")
def api_books_upload():
    user = _user()
    if not request.files.get("file"):
        raise _err("Upload a PDF, TXT or MD book file.")
    upload = request.files["file"]
    title = _text(request.form.get("title"), 140)
    author = _text(request.form.get("author"), 100)
    category = _text(request.form.get("category"), 50) or "My Uploads"
    try:
        book = book_teacher.add_uploaded_book(user["username"], upload.stream, upload.filename, title, author, category)
    except ValueError as err:
        raise _err(str(err))
    except Exception as err:
        raise _err(f"Failed to process book: {err}")
    school.log(user["username"], "book", f"Indexed Book: {book['title']}")
    return jsonify(ok=True, book=book)


@bp.post("/api/books/teach")
def api_books_teach():
    user = _user()
    data = _json()
    book_id = _text(data.get("book_id"), 60)
    topic = _text(data.get("topic"), 200)
    if not book_id:
        raise _err("Select a book first.")
    if not topic:
        raise _err("Enter a topic or chapter to learn.")
    mode = data.get("mode") if data.get("mode") in ("teach", "doubt", "socratic") else "teach"
    profile = school.get_profile(user["username"]) or {}
    language = _lang(data.get("language"), profile)
    _need_ai()
    try:
        result = book_teacher.teach_from_book(user["username"], book_id, topic, mode=mode, language=language)
    except ValueError as err:
        raise _err(str(err))
    school.log(user["username"], "book", f"Book Teacher: {topic}", minutes=10, course_title=result.get("book_title"))
    return jsonify(ok=True, **result)


@bp.post("/api/books/generate_test")
def api_books_generate_test():
    user = _user()
    data = _json()
    book_id = _text(data.get("book_id"), 60)
    if not book_id:
        raise _err("Select a book first.")
    scope = _text(data.get("scope"), 100) or "all"
    count = _deps["clamp"](int(data.get("count") or 5), 2, 12)
    test_type = data.get("test_type") if data.get("test_type") in ("subjective", "mcq", "mixed") else "mixed"
    profile = school.get_profile(user["username"]) or {}
    language = _lang(data.get("language"), profile)
    _need_ai()
    try:
        test_data = book_teacher.generate_book_test_data(user["username"], book_id, scope, count=count, test_type=test_type, language=language)
    except ValueError as err:
        raise _err(str(err))
    return jsonify(ok=True, **test_data)


# ---------- Test Evaluation (LLM Answer Checking) ----------

@bp.post("/api/test/evaluate")
def api_test_evaluate():
    user = _user()
    data = _json()
    test_id = _text(data.get("test_id"), 60)
    answers = data.get("answers")
    if not test_id or not isinstance(answers, dict):
        raise _err("Invalid test submission.")
    profile = school.get_profile(user["username"]) or {}
    language = _lang(data.get("language"), profile)
    try:
        result = test_evaluator.evaluate_test_submission(test_id, answers, username=user["username"], language=language)
    except ValueError as err:
        raise _err(str(err), 404)
    return jsonify(ok=True, **result)


# ---------- Adaptive Learning Hub ----------

@bp.get("/adaptive")
def adaptive_page():
    user = _user()
    profile = school.get_profile(user["username"]) or {}
    adaptive_data = adaptive.get_adaptive_profile(user["username"])
    return render_template("adaptive.html", profile=profile, badge=school.short_label(profile),
                           data=adaptive_data)


@bp.get("/api/adaptive/profile")
def api_adaptive_profile():
    user = _user()
    data = adaptive.get_adaptive_profile(user["username"])
    return jsonify(ok=True, **data)


@bp.post("/api/adaptive/test")
def api_adaptive_test():
    user = _user()
    data = _json()
    course_id = _text(data.get("course_id"), 60) or None
    count = _deps["clamp"](int(data.get("count") or 6), 2, 12)
    test_type = data.get("test_type") if data.get("test_type") in ("subjective", "mcq", "mixed") else "mixed"
    profile = school.get_profile(user["username"]) or {}
    language = _lang(data.get("language"), profile)
    _need_ai()
    try:
        test_obj = adaptive.generate_adaptive_test(user["username"], course_id=course_id, count=count, test_type=test_type, language=language)
    except ValueError as err:
        raise _err(str(err))
    return jsonify(ok=True, **test_obj)


# =====================================================================
# Coding Space & Practical Laboratory Routes
# =====================================================================

@bp.get("/lab")
def lab_hub():
    """Practical Lab & Coding Space Hub: lists all enrolled practical courses or opens playground."""
    user = _user()
    profile = school.get_profile(user["username"]) or {}
    all_courses = school.my_courses(user["username"])
    practical_courses = [
        c for c in all_courses
        if c.get("is_practical_lab") or c.get("is_practical") or c.get("practical_course_id")
    ]
    # If user has practical courses, render the lab workspace with the first one or selector
    return render_template(
        "lab.html",
        ctx=_tool_context(user),
        profile=profile,
        practical_courses=practical_courses,
        active_course=practical_courses[0] if practical_courses else None,
        exercises=lab_service.get_lab_exercises(practical_courses[0]) if practical_courses else []
    )


@bp.get("/lab/<cid>")
def lab_workspace(cid):
    """Dedicated Coding Space & Practical Studio for a specific course."""
    user = _user()
    profile = school.get_profile(user["username"]) or {}
    all_courses = school.my_courses(user["username"])
    course = next((c for c in all_courses if c.get("id") == cid), None)
    if not course:
        # Check if course exists in storage
        course = storage.get_course(cid)
    if not course:
        raise _err("Course not found.", 404)

    # If it's a theoretical course with a practical companion, offer both
    practical_courses = [
        c for c in all_courses
        if c.get("is_practical_lab") or c.get("is_practical") or c.get("practical_course_id")
    ]
    exercises = lab_service.get_lab_exercises(course)

    return render_template(
        "lab.html",
        ctx=_tool_context(user),
        profile=profile,
        practical_courses=practical_courses,
        active_course=course,
        exercises=exercises
    )


@bp.post("/api/lab/run")
def api_lab_run():
    """Executes student code in the live sandbox (Python, SQL, JavaScript, HTML)."""
    user = _user()
    data = _json()
    language = _text(data.get("language"), 30) or "python"
    code = data.get("code") or ""
    stdin = data.get("stdin") or ""
    result = lab_service.run_code(language=language, code=code, stdin=stdin)
    return jsonify(**result)


@bp.post("/api/lab/review")
def api_lab_review():
    """Agentic AI evaluation and grading of student code against the laboratory problem."""
    user = _user()
    data = _json()
    code = data.get("code") or ""
    aim = _text(data.get("aim"), 500) or "Complete the implementation."
    exercise_title = _text(data.get("exercise_title"), 200) or "Practical Exercise"
    language = _text(data.get("language"), 30) or "python"

    if not code.strip():
        raise _err("Please write some code before requesting an AI review.")

    _need_ai()
    from services.agentic import evaluate_student_code
    review = evaluate_student_code(code=code, aim=aim, exercise_title=exercise_title, language=language)
    review["ok"] = True
    return jsonify(**review)


@bp.post("/api/lab/debug")
def api_lab_debug():
    """Socratic debugging agent providing progressive hints without spoiling the solution."""
    user = _user()
    data = _json()
    code = data.get("code") or ""
    error_message = data.get("error_message") or ""
    aim = _text(data.get("aim"), 500) or "Complete the implementation."
    language = _text(data.get("language"), 30) or "python"

    _need_ai()
    from services.agentic import debug_student_code
    debug_info = debug_student_code(code=code, error_message=error_message, aim=aim, language=language)
    debug_info["ok"] = True
    return jsonify(**debug_info)


@bp.post("/api/lab/generate_exercise")
def api_lab_generate_exercise():
    """Synthesizes an on-demand practical exercise for any syllabus topic."""
    user = _user()
    data = _json()
    course_id = _text(data.get("course_id"), 60)
    topic = _text(data.get("topic"), 150) or "General Algorithms"
    language = _text(data.get("language"), 30) or "python"

    _need_ai()
    course = storage.get_course(course_id) if course_id else {}
    subject = course.get("subject", "Computer Science") if course else "Computer Science"
    new_ex = lab_service.generate_custom_exercise(subject=subject, topic=topic, language=language)

    if course and "lab_exercises" in course:
        course["lab_exercises"].append(new_ex)
        storage.save_course(course)

    return jsonify(ok=True, exercise=new_ex)


@bp.post("/api/lab/save")
def api_lab_save():
    """Saves student's draft code for the exercise."""
    user = _user()
    data = _json()
    course_id = _text(data.get("course_id"), 60)
    exercise_id = _text(data.get("exercise_id"), 60)
    code = data.get("code") or ""
    if course_id and exercise_id:
        lab_service.save_student_lab_draft(user["username"], course_id, exercise_id, code)
    return jsonify(ok=True)


@bp.get("/api/lab/draft/<cid>/<eid>")
def api_lab_get_draft(cid, eid):
    """Retrieves student's draft code for the exercise."""
    user = _user()
    code = lab_service.get_student_lab_draft(user["username"], cid, eid)
    return jsonify(ok=True, code=code)

