"""AI विद्यालय - run with:  python app.py   then open http://127.0.0.1:5000"""
import gzip
import os
import re
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

from flask import Flask, g, jsonify, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, URLSafeTimedSerializer

from services import course_logic as cl
from services import db, emailer, groq, mockllm, otp, prompts, rag, school, storage, websearch
from services import knowledge as kb
from services.config import get_setting, has_api_key, has_search_key

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600  # unversioned static files: 1 hour (versioned ?v= files get 1 year below)
app.config["MAX_CONTENT_LENGTH"] = 25 * 1024 * 1024  # 25 MB uploads
app.secret_key = storage.secret_key()
REMEMBER_DAYS = 90
app.permanent_session_lifetime = timedelta(days=REMEMBER_DAYS)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_REFRESH_EACH_REQUEST"] = True   # every visit pushes the 90 days forward
# Render (and most hosts) serve over https: mark the cookie secure there. Set COOKIE_SECURE=0 to turn it off.
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("COOKIE_SECURE", "1" if os.environ.get("RENDER") else "0") == "1"
_remember = URLSafeTimedSerializer(app.secret_key, salt="vidyalaya-remember")
REMEMBER_COOKIE = "vidyalaya_remember"
print("Storage: " + ("DATABASE (Postgres). Everything is saved there." if db.enabled()
                     else "local files in the data folder. On a cloud host these are erased on restart: set DATABASE_URL."),
      flush=True)
storage.ensure_default_users()  # bijay, ayush and pragyansh (password 12345)

LEVELS = {"beginner": "Beginner", "some": "Knows the basics", "intermediate": "Intermediate",
          "mid": "Mid", "advanced": "Advanced", "all": "All levels"}
LLM_LEVEL = {"beginner": "beginner", "mid": "intermediate", "advanced": "intermediate", "all": "beginner"}
MODES = ("professor", "tutor", "socratic")
ALLOWED_UPLOADS = (".pdf", ".txt", ".md")
USERNAME_RE = re.compile(r"^[a-z0-9_.]{3,20}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,120}\.[^@\s.]{2,}$")
PUBLIC_ENDPOINTS = {"index", "static", "api_login", "api_logout", "api_resume", "health",
                    "ping", "api_signup_start", "api_signup_verify", "api_otp_resend", "api_forgot_start", "api_forgot_verify",
                    "api_login_otp_start", "api_login_otp_verify"}
BACKUP_SECONDS = 15  # the AI is only a backup: never make the student wait longer than this
WEB_SECONDS = 25     # when a web lookup is added, allow a little longer
DIRECT_RULE = (" Reply with the direct answer only, in one to three short sentences. Do not say where the answer "
               "comes from and never mention notes, sources or excerpts.")
WEB_RULE = (" Web excerpts from study sites may be given after the question. Use them as background, answer "
            "in your own words in the style described above, and never copy sentences from them or mention "
            "excerpts or websites. If they do not help, answer from your own knowledge.")
NO_SOURCE_RULE = (" Never tell the student where the information comes from: no source, reference or website lines, "
                  "no links, and no mention of excerpts, notes or searching.")
COURSE_DESC = "Structured lessons, worked examples and quizzes, from the basics to advanced."
GREETING_RE = re.compile(r"^(hi+|hello+|hey+|good (morning|afternoon|evening)|namaste)[!. ]*$")


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


# ---------- helpers ----------

def grounded(message, notes):
    """The question plus the best matching facts, given to the AI silently as background."""
    facts = [n["a"] if n["kind"] != "fact" else f"{n['q']} {n['a']}" for n in notes[:3]]
    if not facts:
        return message
    return message + "\n\nFacts you can rely on (use them silently, do not mention them):\n" + "\n".join("- " + f for f in facts)


def offline_first():
    """OFFLINE_FIRST=1 in .env brings back the old order (built-in data first). Default: Groq + web search always."""
    return get_setting("OFFLINE_FIRST", "0").strip().lower() in ("1", "true", "yes", "on")


def web_answer(message, system, history, topic_hint="", max_tokens=900):
    """Backup answer: look the question up on study sites (GeeksforGeeks etc.), then let Groq explain it.

    Falls back to a plain Groq answer when no search key is set or the search finds nothing.
    """
    pages = websearch.search(f"{message} {topic_hint}".strip()) if has_search_key() else []
    prompt = message
    if pages:
        prompt += "\n\nWeb excerpts (background only):\n" + websearch.as_context(pages)
    rule = (WEB_RULE if pages else "") + NO_SOURCE_RULE
    answer = groq.generate(prompt, system=system + rule, history=history, temperature=0.6,
                           max_tokens=max_tokens, deadline=WEB_SECONDS if pages else BACKUP_SECONDS).strip()
    return answer


def remember_token(username):
    """A signed, long-lived 'stay logged in' token for this person."""
    return _remember.dumps(username)


def username_from_token(token):
    try:
        return _remember.loads(str(token or ""), max_age=REMEMBER_DAYS * 86400)
    except BadSignature:
        return None


def login_session(username):
    session.permanent = True
    session["user"] = username


def current_user():
    if "user" not in g:
        g.user = storage.get_user(session.get("user")) if session.get("user") else None
        if g.user is None:
            session.pop("user", None)
            # The login cookie is gone (phone cleared it, app restarted, server slept): use the backup cookie.
            name = username_from_token(request.cookies.get(REMEMBER_COOKIE))
            if name:
                g.user = storage.get_user(name)
                if g.user is not None:
                    login_session(g.user["username"])
    return g.user


def tidy(course):
    """Older saved courses may still carry the old wording. Clean it up when showing them."""
    course["title"] = str(course.get("title") or "").replace(": rote learning", "").replace("rote learning", "").strip()
    desc = str(course.get("description") or "")
    if "offline" in desc.lower() and "flashcards" in desc.lower():
        course["description"] = COURSE_DESC
    return course


def get_course(cid):
    return tidy(storage.load_course(cid))


def wants_json():
    return request.path.startswith("/api/")


def source_refs(hits):
    return [{"n": i, "name": h["doc"], "page": h["page"], "snippet": h["text"][:220]}
            for i, h in enumerate(hits, start=1)]


def clamp(value, low, high):
    return max(low, min(high, value))


def is_rote(course):
    return course.get("engine") == "rote"


COMPRESSIBLE = ("text/html", "text/css", "application/javascript", "text/javascript", "application/json", "image/svg+xml")


def compress_response(response):
    """gzip text responses (pages, CSS, JS, JSON): 3-5x fewer bytes on a slow phone connection."""
    try:
        if (response.status_code != 200 or response.mimetype not in COMPRESSIBLE or "Content-Encoding" in response.headers
                or "gzip" not in request.headers.get("Accept-Encoding", "").lower()):
            return response
        response.direct_passthrough = False
        data = response.get_data()
        if len(data) < 600:
            return response
        response.set_data(gzip.compress(data, compresslevel=5))
        response.headers["Content-Encoding"] = "gzip"
        response.headers["Vary"] = "Accept-Encoding"
        response.headers.pop("ETag", None)
    except Exception:  # noqa: BLE001  never break a page because of compression
        pass
    return response


@app.after_request
def no_page_cache(response):
    """Pages are never reused from the browser's back/forward cache, so Back always shows fresh courses."""
    if response.mimetype == "text/html":
        response.headers["Cache-Control"] = "no-store"
    elif request.endpoint == "static" and request.args.get("v") and response.status_code == 200:
        # The address changes whenever a file changes (asset_v), so the phone can keep its copy: pages open instantly.
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    compress_response(response)
    # Backup "stay logged in" cookie (90 days, refreshed on every visit)
    user = g.get("user")
    if user and request.endpoint != "static" and not getattr(g, "forget_me", False):
        response.set_cookie(REMEMBER_COOKIE, remember_token(user["username"]), max_age=REMEMBER_DAYS * 86400,
                            httponly=True, samesite="Lax", secure=app.config["SESSION_COOKIE_SECURE"])
    return response


@app.context_processor
def inject_globals():
    return {"has_key": has_api_key(), "user": current_user(),
            "db_on": db.enabled() and db.connected()}


@app.get("/health")
def health():
    """Open /health in the browser: shows whether data is really being saved to the database."""
    info = {"app": "ok", "storage": "database" if db.enabled() else "files"}
    try:
        stamp = cl.now_iso()
        storage.put_doc("health", "ping", {"t": stamp})            # write ...
        info["saved_and_read_back"] = (storage.get_doc("health", "ping", {}) or {}).get("t") == stamp   # ... and read
    except Exception as exc:  # noqa: BLE001
        print("Health check failed:", exc, flush=True)
        info.update(saved_and_read_back=False, error="Storage is not working. See the server log.")
        return jsonify(info), 503
    if db.enabled() and not db.connected():
        info["saved_and_read_back"] = False
        return jsonify(info), 503
    return jsonify(info)


@app.get("/ping")
def ping():
    """For a free uptime monitor: keeps the free Render server awake without touching the database."""
    return "ok", 200, {"Cache-Control": "no-store", "Content-Type": "text/plain"}


@app.before_request
def require_login():
    """Everything except the home page (which shows the login window) needs a signed-in user."""
    if request.endpoint is None or request.endpoint in PUBLIC_ENDPOINTS:
        return None
    user = current_user()
    if user is None:
        if wants_json():
            return jsonify(error="Please log in first."), 401
        return redirect(url_for("index", next=request.full_path.rstrip("?")))
    cid = (request.view_args or {}).get("cid")
    if cid:
        owner = storage.load_course(cid).get("owner")
        if owner and owner != user["username"]:
            raise storage.CourseNotFound(cid)
    return None


@app.template_filter("pretty_date")
def pretty_date(value):
    try:
        return date.fromisoformat(value).strftime("%a %d %b")
    except (TypeError, ValueError):
        return value or ""


@app.template_filter("level_label")
def level_label(value):
    return LEVELS.get(value, value)


_ASSET_V = {"at": 0, "v": 0}


@app.context_processor
def asset_version():
    """Changes whenever a script or style file changes, so browsers never show an old copy."""
    now = time.time()
    if now - _ASSET_V["at"] > 5:
        root = Path(app.static_folder)
        _ASSET_V.update(at=now, v=int(max((f.stat().st_mtime for f in root.rglob("*") if f.is_file()), default=0)))
    return {"asset_v": _ASSET_V["v"]}


@app.template_filter("hours_label")
def hours_label(value):
    return f"{value:g}"


# ---------- error handlers ----------

@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error=str(err)), err.status


@app.errorhandler(groq.GroqError)
def handle_groq_error(err):
    return jsonify(error=str(err)), err.status


@app.errorhandler(storage.CourseNotFound)
def handle_missing_course(err):
    if wants_json():
        return jsonify(error="That course no longer exists."), 404
    return render_template("message.html", title="Course not found",
                           text="This course does not exist. It may have been deleted."), 404


@app.errorhandler(404)
def handle_404(err):
    if wants_json():
        return jsonify(error="Not found."), 404
    return render_template("message.html", title="Page not found", text="There is nothing at this address."), 404


@app.errorhandler(413)
def handle_too_large(err):
    return jsonify(error="That file is too large. The limit is 25 MB."), 413


@app.errorhandler(Exception)
def handle_unexpected(err):
    """Anything unexpected: log it, and always answer the browser so the page never hangs."""
    from werkzeug.exceptions import HTTPException
    if isinstance(err, HTTPException):
        return err
    import traceback
    traceback.print_exc()
    if wants_json():
        return jsonify(error=f"Something went wrong on the server: {err.__class__.__name__}: {err}"), 500
    return render_template("message.html", title="Something went wrong",
                           text="The server hit an error. Check the terminal window for details."), 500


@app.errorhandler(500)
def handle_500(err):
    if wants_json():
        return jsonify(error="Something went wrong on the server. Check the terminal window for details."), 500
    return render_template("message.html", title="Something went wrong",
                           text="The server hit an error. Check the terminal window for details."), 500


# ---------- pages ----------

@app.get("/")
def index():
    user = current_user()
    if user is None:
        return render_template("index.html", rows=[], subjects=[], level_choices=[])
    profile = school.get_profile(user["username"]) or {}
    if not profile.get("onboarded") and not profile.get("skipped"):
        return redirect(url_for("school.welcome"))
    mine = [tidy(c) for c in storage.list_courses(owner=user["username"], include_unowned=True)]
    rows = [{"course": c, "stats": cl.stats(c)} for c in mine]
    return render_template("index.html", rows=rows, subjects=kb.subject_options(), level_choices=kb.LEVEL_CHOICES)


@app.get("/course/<cid>")
def course_page(cid):
    course = get_course(cid)
    day_index = cl.current_day_index(course)
    today = course["schedule"][day_index] if day_index is not None else None
    next_item = next((i for i in today["items"] if not i["done"]), None) if today else None
    materials = [{"id": m["id"], "name": m["name"], "pages": m.get("pages", 1), "chunks": len(m["chunks"])}
                 for m in storage.load_materials(cid)]
    return render_template(
        "course.html", c=course, stats=cl.stats(course), today=today, next_item=next_item,
        materials=materials, finished=bool(course["schedule"]) and day_index is None)


@app.get("/course/<cid>/learn/<tid>")
def learn_page(cid, tid):
    course = get_course(cid)
    found = cl.find_topic(course, tid)
    if not found:
        raise storage.CourseNotFound(tid)
    module, topic = found
    prev_id, next_id = cl.neighbours(course, tid)
    boot = {
        "courseId": cid, "topicId": tid,
        "lesson": kb.lesson(topic["kb"]) if is_rote(course) and topic.get("kb") else course["lessons"].get(tid),
        "rote": is_rote(course),
        "chat": course["chat"].get(tid, []),
        "autoQuiz": request.args.get("mode") == "quiz",
        "mastery": topic.get("mastery"),
        "done": topic["status"] == "done",
    }
    return render_template("lesson.html", c=course, m=module, t=topic, prev_id=prev_id, next_id=next_id, boot=boot)


@app.get("/course/<cid>/test")
def test_page(cid):
    course = get_course(cid)
    modules = [{"id": m["id"], "title": m["title"], "topicIds": [t["id"] for t in m["topics"]]}
               for m in course["modules"]]
    return render_template("test.html", c=course, boot={"courseId": cid, "modules": modules})


# ---------- API: login ----------

@app.post("/api/login")
def api_login():
    """Password login. The first box may be the username or the e-mail address."""
    data = request.get_json(silent=True) or {}
    user = storage.check_login(data.get("username") or data.get("identifier"), data.get("password"))
    if not user:
        raise ApiError("Wrong email or password.", 401)
    return logged_in(user)


def logged_in(user):
    login_session(user["username"])
    g.user = user
    return jsonify(ok=True, name=user["name"], token=remember_token(user["username"]))


# ---------- API: e-mail codes (sign up, forgot password, login with code) ----------

def clean_email(value):
    email = str(value or "").strip().lower()
    if len(email) > 150 or not EMAIL_RE.match(email):
        raise ApiError("Please type a valid e-mail address.")
    return email


def mask_email(email):
    name, _, domain = email.partition("@")
    return (name[:1] + "***" + name[-1:] if len(name) > 2 else name[:1] + "***") + "@" + domain


def send_code(purpose, email, payload=None):
    """Make a code and e-mail it. Wrong e-mail provider settings or limits become clear messages."""
    ip = (request.headers.get("X-Forwarded-For", "") or request.remote_addr or "?").split(",")[0].strip()
    try:
        otp.ip_guard(ip)
        code = otp.issue(purpose, email, payload)
    except otp.OtpError as exc:
        raise ApiError(str(exc), exc.status)
    try:
        emailer.send_code(email, code, purpose)
    except emailer.MailError as exc:
        otp.forget(purpose, email)
        raise ApiError(str(exc), 503)
    return jsonify(ok=True, email=mask_email(email), cooldown=otp.COOLDOWN)


def check_code(purpose, email, code):
    try:
        return otp.verify(purpose, email, code)
    except otp.OtpError as exc:
        raise ApiError(str(exc), exc.status)


@app.post("/api/signup/start")
def api_signup_start():
    data = request.get_json(silent=True) or {}
    name = " ".join(str(data.get("name") or "").split())[:40]
    password = str(data.get("password") or "")
    email = clean_email(data.get("email"))
    if len(name) < 2:
        raise ApiError("Please type your full name.")
    if len(password) < 5:
        raise ApiError("Password must be at least 5 characters.")
    if storage.find_username_by_email(email):
        raise ApiError("This e-mail already has an account. Please log in.", 409)
    from werkzeug.security import generate_password_hash
    return send_code("signup", email, {"name": name, "email": email, "pw": generate_password_hash(password)})


@app.post("/api/signup/verify")
def api_signup_verify():
    data = request.get_json(silent=True) or {}
    email = clean_email(data.get("email"))
    info = check_code("signup", email, data.get("code"))
    if not isinstance(info, dict) or info.get("email") != email:
        raise ApiError("Please start sign up again.")
    user = None
    for _ in range(3):   # the internal id is made automatically; retry in the rare case two people get the same one
        try:
            user = storage.create_user(storage.make_username(email), name=info["name"], email=email, password_hash=info["pw"])
            break
        except storage.UserExists:
            if storage.find_username_by_email(email):
                raise ApiError("This e-mail already has an account. Please log in.", 409)
    if user is None:
        raise ApiError("Could not create the account. Please try again.", 409)
    return logged_in(user)


@app.post("/api/otp/resend")
def api_otp_resend():
    """Send the code again. Sign up keeps the details typed earlier; the other two only answer for real accounts."""
    data = request.get_json(silent=True) or {}
    purpose = data.get("purpose")
    email = clean_email(data.get("email"))
    if purpose == "signup":
        info = otp.payload_of("signup", email)
        if not info:
            raise ApiError("Please start sign up again.")
        return send_code("signup", email, info)
    if purpose in ("reset", "login"):
        return code_for_existing(purpose, email)
    raise ApiError("Unknown request.")


def code_for_existing(purpose, email):
    """Same answer whether or not the e-mail has an account, so nobody can use this to find out who is registered."""
    if storage.find_username_by_email(email):
        return send_code(purpose, email)
    ip = (request.headers.get("X-Forwarded-For", "") or request.remote_addr or "?").split(",")[0].strip()
    try:
        otp.ip_guard(ip)
    except otp.OtpError as exc:
        raise ApiError(str(exc), exc.status)
    return jsonify(ok=True, email=mask_email(email), cooldown=otp.COOLDOWN)


@app.post("/api/forgot/start")
def api_forgot_start():
    return code_for_existing("reset", clean_email((request.get_json(silent=True) or {}).get("email")))


@app.post("/api/forgot/verify")
def api_forgot_verify():
    data = request.get_json(silent=True) or {}
    email = clean_email(data.get("email"))
    password = str(data.get("password") or "")
    if len(password) < 5:
        raise ApiError("Password must be at least 5 characters.")
    check_code("reset", email, data.get("code"))
    username = storage.find_username_by_email(email)
    if not username or not storage.set_password(username, password):
        raise ApiError("This e-mail has no account.", 404)
    return logged_in(storage.get_user(username))


@app.post("/api/login/otp/start")
def api_login_otp_start():
    return code_for_existing("login", clean_email((request.get_json(silent=True) or {}).get("email")))


@app.post("/api/login/otp/verify")
def api_login_otp_verify():
    data = request.get_json(silent=True) or {}
    email = clean_email(data.get("email"))
    check_code("login", email, data.get("code"))
    username = storage.find_username_by_email(email)
    if not username:
        raise ApiError("This e-mail has no account.", 404)
    return logged_in(storage.get_user(username))


@app.post("/api/resume")
def api_resume():
    """The phone sends its saved token; if it is valid the person is logged in again without typing anything."""
    data = request.get_json(silent=True) or {}
    name = username_from_token(data.get("token"))
    user = storage.get_user(name) if name else None
    if not user:
        raise ApiError("Please log in again.", 401)
    login_session(user["username"])
    g.user = user
    return jsonify(ok=True, name=user["name"], token=remember_token(user["username"]))


@app.post("/api/logout")
def api_logout():
    session.pop("user", None)
    g.forget_me = True
    g.user = None
    resp = jsonify(ok=True)
    resp.delete_cookie(REMEMBER_COOKIE)
    return resp


# ---------- API: home chat ----------

@app.post("/api/chat")
def api_chat():
    user = current_user()
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()[:1000]
    if not message:
        raise ApiError("Type a message first.")
    history = [{"role": "user" if t.get("role") == "user" else "model", "text": str(t.get("text"))[:1500]}
               for t in (data.get("history") or [])[-8:] if isinstance(t, dict) and t.get("text")]

    if GREETING_RE.match(message.lower()):
        return jsonify(answer=f"Hi {user['name']}! Ask me anything about AI, Machine Learning, DSA, Calculus or Engineering Maths.")

    system = (f"You are the friendly study assistant of AI विद्यालय, chatting with {user['name']}. "
              "Answer clearly, like a good teacher, in plain language, in under 250 words, with a short example "
              "when it helps. " + prompts.MATH_RULE + prompts.FORMAT_RULE)

    if offline_first():
        notes = mockllm.retrieve(message, k=20)
        answer = mockllm.answer(message, notes, "professor").strip()
        if answer == mockllm.NO_ANSWER and has_api_key():
            try:
                answer = web_answer(message, system, history)
            except groq.GroqError as err:
                print("[chat] Groq backup unavailable:", err, flush=True)
        return jsonify(answer=answer)

    # Default: search the web (if a Tavily key is set) and answer with Groq. Errors are shown, so the API can be tested.
    return jsonify(answer=web_answer(message, system, history))


# ---------- API: courses ----------

@app.get("/api/health")
def api_health():
    ok, message = groq.check()
    return jsonify(ok=ok, message=message), (200 if ok else 503)


@app.post("/api/courses")
def api_create_course():
    data = request.get_json(silent=True) or {}
    chosen = str(data.get("subject") or "").strip()
    level = data.get("level") if data.get("level") in ("beginner", "mid", "advanced", "all") else "beginner"
    try:
        hours = clamp(float(data.get("hours") or 2), 0.5, 12)
        days = clamp(int(float(data.get("days") or 14)), 1, 180)
    except (TypeError, ValueError):
        raise ApiError("Hours and days must be numbers.")

    # Built-in subjects are built straight from the course library; anything else goes to Groq.
    if kb.has_subject(chosen):
        title, description, modules = kb.build_course(chosen, level)
        course = cl.new_course(kb.subject_name(chosen), level, hours, days, title, description, modules)
        course["engine"], course["kb_subject"] = "rote", chosen
        course["owner"] = current_user()["username"]
        course["schedule"] = cl.build_local_schedule(course)
        storage.save_course(course)
        return jsonify(id=course["id"])

    subject = kb.subject_name(chosen) if kb.has_subject(chosen) else chosen
    if chosen == "other":
        subject = str(data.get("custom") or "")
    subject = " ".join(subject.split())[:80]
    if len(subject) < 2:
        raise ApiError("Enter a subject, for example Machine Learning or Calculus.")

    gem_level = LLM_LEVEL.get(level, "beginner")
    system, prompt = prompts.syllabus(subject, gem_level, hours, days)
    raw = groq.generate(prompt, system=system, json_mode=True, temperature=0.6)
    title, description, modules = cl.normalize_syllabus(raw)
    course = cl.new_course(subject, gem_level, hours, days, title, description, modules)
    course["owner"] = current_user()["username"]
    # Plan the schedule locally and instantly. This avoids a second slow Groq call;
    # the "Plan with AI" button on the course page can still re-plan it with Groq.
    course["schedule"] = cl.build_local_schedule(course)
    storage.save_course(course)
    return jsonify(id=course["id"])


@app.post("/api/courses/<cid>/schedule")
def api_schedule(cid):
    course = get_course(cid)
    if is_rote(course):
        with storage.update(cid) as c:
            c["schedule"] = cl.build_local_schedule(c)
        return jsonify(ok=True, source="local")
    system, prompt = prompts.schedule(course, cl.all_topics(course))
    raw = None
    try:
        raw = groq.generate(prompt, system=system, json_mode=True, temperature=0.4)
    except groq.GroqError as err:
        if err.fatal:
            raise
    with storage.update(cid) as c:
        schedule = cl.normalize_schedule(raw, c) if raw is not None else None
        source = "groq" if schedule else "local"
        c["schedule"] = schedule or cl.build_local_schedule(c)
    return jsonify(ok=True, source=source)


@app.delete("/api/courses/<cid>")
def api_delete_course(cid):
    get_course(cid)
    storage.delete_course(cid)
    return jsonify(ok=True)


# ---------- API: study material ----------

@app.post("/api/courses/<cid>/materials")
def api_upload_material(cid):
    get_course(cid)
    upload = request.files.get("file")
    if not upload or not upload.filename:
        raise ApiError("Choose a file first.")
    name = Path(upload.filename).name[:80]
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_UPLOADS:
        raise ApiError("Upload a PDF, TXT or MD file.")
    try:
        pages = rag.extract(upload.stream, ext)
    except ValueError as err:
        raise ApiError(str(err))
    except Exception:
        raise ApiError("That file could not be read. Try another PDF or a text file.")
    chunks = rag.chunk_pages(pages)
    if not chunks:
        raise ApiError("No readable text found in that file. Scanned PDFs (images of pages) are not supported.")

    materials = storage.load_materials(cid)
    if sum(len(m["chunks"]) for m in materials) + len(chunks) > rag.MAX_CHUNKS_PER_COURSE:
        raise ApiError("This course already has a lot of material. Delete a file before adding another.")
    materials.append({"id": uuid.uuid4().hex[:8], "name": name, "pages": len(pages),
                      "chunks": chunks, "added": cl.now_iso()})
    storage.save_materials(cid, materials)
    return jsonify(ok=True, chunks=len(chunks))


@app.delete("/api/courses/<cid>/materials/<mid>")
def api_delete_material(cid, mid):
    get_course(cid)
    materials = [m for m in storage.load_materials(cid) if m["id"] != mid]
    storage.save_materials(cid, materials)
    return jsonify(ok=True)


# ---------- API: teaching ----------

@app.post("/api/courses/<cid>/topics/<tid>/lesson")
def api_lesson(cid, tid):
    course = get_course(cid)
    found = cl.find_topic(course, tid)
    if not found:
        raise ApiError("Topic not found.", 404)
    module, topic = found
    if is_rote(course) and topic.get("kb") and not has_api_key():
        return jsonify(kb.lesson(topic["kb"]))
    refresh = bool((request.get_json(silent=True) or {}).get("refresh"))
    cached = course["lessons"].get(tid)
    if cached and not refresh:
        return jsonify(cached)

    from services.agentic import professor_agent_graph

    hits = rag.search(storage.load_materials(cid), f"{topic['title']} {topic['summary']} {module['title']}", k=4)
    previous, upcoming = cl.previous_and_upcoming(course, tid)

    state = {
        "subject": course["subject"],
        "program_desc": (course.get("school") or {}).get("desc") or "University Curriculum",
        "module_title": module["title"],
        "module_goal": module.get("goal", ""),
        "topic_title": topic["title"],
        "topic_summary": topic.get("summary", ""),
        "student_level": course.get("level", "intermediate"),
        "language": course.get("language", "en"),
        "previous_topics": previous or [],
        "upcoming_topics": upcoming or [],
        "excerpts": hits or [],
        "web_research": [],
        "lecture_content": "",
        "verification_status": ""
    }

    graph_res = professor_agent_graph.invoke(state)
    text = graph_res.get("lecture_content", "")
    lesson = {"markdown": text.strip(), "sources": source_refs(hits), "created": cl.now_iso()}
    with storage.update(cid) as c:
        c["lessons"][tid] = lesson
    return jsonify(lesson)


@app.post("/api/courses/<cid>/ask")
def api_ask(cid):
    course = get_course(cid)
    data = request.get_json(silent=True) or {}
    message = str(data.get("message") or "").strip()[:2000]
    if not message:
        raise ApiError("Type a question first.")
    found = cl.find_topic(course, data.get("topic_id"))
    if not found:
        raise ApiError("Topic not found.", 404)
    _, topic = found
    mode = "professor"

    if is_rote(course) and offline_first():
        notes = mockllm.retrieve(message, subject=course.get("kb_subject"), topic_key=topic.get("kb"), k=20)
        sources = []  # built-in answers are shown plainly, with no "from the notes" labels
        answer = mockllm.answer(message, notes, mode).strip()
        if answer == mockllm.NO_ANSWER and has_api_key():
            history = [{"role": turn["role"], "text": turn["text"]} for turn in course["chat"].get(topic["id"], [])[-8:]]
            try:
                answer = web_answer(message, prompts.ask(course, topic, mode), history, topic_hint=topic["title"])
            except groq.GroqError as err:
                print("[ask] Groq backup unavailable:", err, flush=True)
    elif is_rote(course):
        # Built-in course, online mode: Groq + web search answer directly.
        sources = []
        history = [{"role": turn["role"], "text": turn["text"]} for turn in course["chat"].get(topic["id"], [])[-8:]]
        answer = web_answer(message, prompts.ask(course, topic, mode), history,
                            topic_hint=f"{topic['title']} {course['subject']}", max_tokens=1500)
    else:
        hits = rag.search(storage.load_materials(cid), f"{message} {topic['title']}", k=3)
        history = [{"role": turn["role"], "text": turn["text"]} for turn in course["chat"].get(topic["id"], [])[-8:]]
        if hits or not has_search_key():
            answer = groq.generate(prompts.ask_message(message, hits), system=prompts.ask(course, topic, mode),
                                   history=history, temperature=0.7, max_tokens=2048).strip()
        else:  # no uploaded material for this question: look it up on study sites
            answer = web_answer(message, prompts.ask(course, topic, mode), history,
                                topic_hint=f"{topic['title']} {course['subject']}", max_tokens=1500)
        sources = source_refs(hits)
    with storage.update(cid) as c:
        log = c["chat"].setdefault(topic["id"], [])
        log.append({"role": "user", "text": message})
        log.append({"role": "model", "text": answer, "sources": sources})
        del log[:-30]
    return jsonify(answer=answer, sources=sources)


@app.post("/api/courses/<cid>/topics/<tid>/complete")
def api_complete(cid, tid):
    with storage.update(cid) as c:
        found = cl.find_topic(c, tid)
        if not found:
            raise ApiError("Topic not found.", 404)
        first_time = found[1]["status"] != "done"
        found[1]["status"] = "done"
        cl.mark_items(c, tid, ("learn", "practice"))
        next_id = cl.next_topic_id(c, tid)
        finished = (found[1]["title"], found[1].get("minutes", 30), c["id"], c["title"])
    if first_time:
        school.log(current_user()["username"], "topic", f"Completed: {finished[0]}", minutes=finished[1],
                   course_id=finished[2], course_title=finished[3])
    target = url_for("learn_page", cid=cid, tid=next_id) if next_id else url_for("course_page", cid=cid)
    return jsonify(ok=True, next_url=target)


# ---------- API: quizzes and tests ----------

@app.post("/api/courses/<cid>/quiz")
def api_quiz(cid):
    course = get_course(cid)
    data = request.get_json(silent=True) or {}
    all_topics = cl.all_topics(course)
    wanted = [t for t in (data.get("topic_ids") or []) if isinstance(t, str)]
    chosen = [(m, t) for m, t in all_topics if t["id"] in wanted] or all_topics
    try:
        count = clamp(int(data.get("count") or 4), 3, 12)
    except (TypeError, ValueError):
        count = 4
    kind = "test" if data.get("kind") == "test" else "lesson"

    if is_rote(course):
        questions = kb.make_questions([(t["id"], t["kb"]) for _, t in chosen if t.get("kb")], count)
        if not questions:
            raise ApiError("No questions are available for this topic.")
    else:
        system, prompt = prompts.quiz(course, chosen, count)
        raw = groq.generate(prompt, system=system, json_mode=True, temperature=0.6)
        valid_ids = [t["id"] for _, t in chosen]
        questions = cl.normalize_questions(raw, valid_ids, count)
        if not questions:
            raise groq.GroqError("Groq could not write usable questions. Please try again.")

    quiz_id = uuid.uuid4().hex[:8]
    with storage.update(cid) as c:
        c["quizzes"][quiz_id] = {"questions": questions, "kind": kind, "created": cl.now_iso()}
        if len(c["quizzes"]) > 15:
            for old in sorted(c["quizzes"], key=lambda k: c["quizzes"][k]["created"])[:-15]:
                del c["quizzes"][old]
    public = [{"topic_id": q["topic_id"], "question": q["question"], "options": q["options"]} for q in questions]
    return jsonify(quiz_id=quiz_id, questions=public)


@app.post("/api/courses/<cid>/quiz/<qid>/grade")
def api_grade(cid, qid):
    answers = (request.get_json(silent=True) or {}).get("answers")
    if not isinstance(answers, list):
        raise ApiError("No answers were sent.")
    logged = None
    with storage.update(cid) as c:
        quiz = c["quizzes"].get(qid)
        if not quiz:
            raise ApiError("This quiz has expired. Start a new one.", 404)
        if quiz.get("result"):
            return jsonify(quiz["result"])

        details, per_topic = [], {}
        for i, q in enumerate(quiz["questions"]):
            chosen = answers[i] if i < len(answers) and isinstance(answers[i], int) else None
            correct = chosen == q["answer_index"]
            details.append({"correct": correct, "chosen": chosen, "answer_index": q["answer_index"],
                            "explanation": q["explanation"]})
            ok, total = per_topic.get(q["topic_id"], (0, 0))
            per_topic[q["topic_id"]] = (ok + (1 if correct else 0), total + 1)

        topics, notes = cl.apply_quiz_result(c, per_topic, quiz["kind"])
        score = sum(1 for d in details if d["correct"])
        total = len(details)
        result = {"score": score, "total": total, "percent": round(100 * score / total) if total else 0,
                  "questions": details, "topics": topics, "notes": notes}
        quiz["result"] = result
        logged = (c["id"], c["title"], quiz["kind"], result["percent"], total)
    if logged:
        is_test = logged[2] == "test"
        school.log(current_user()["username"], "test" if is_test else "quiz",
                   f"{'Test' if is_test else 'Quiz'}: {logged[1]}", minutes=15 if is_test else max(5, round(logged[4] * 1.5)),
                   score=logged[3], course_id=logged[0], course_title=logged[1])
    return jsonify(result)


@app.post("/api/courses/<cid>/test_comprehensive")
def api_course_comprehensive_test(cid):
    course = get_course(cid)
    data = request.get_json(silent=True) or {}
    all_topics = cl.all_topics(course)
    wanted = [t for t in (data.get("topic_ids") or []) if isinstance(t, str)]
    chosen = [(m, t) for m, t in all_topics if t["id"] in wanted] or all_topics
    count = clamp(int(data.get("count") or 5), 2, 12)
    test_type = data.get("test_type", "mixed")
    
    topic_titles = [t["title"] for _, t in chosen]
    system = f"""You are the senior examiner for the subject: {course['subject']}.
Generate a comprehensive test for the student with {count} questions.
Topics: {', '.join(topic_titles)}
Test Type: {test_type} (subjective, mcq, or mixed)

For subjective questions:
- "type": "subjective"
- "question": clear question requiring 2-4 sentences of conceptual explanation, problem solving or derivation.
- "max_marks": 5
- "expected_points": list of 3-4 key points/concepts expected.
- "model_answer": exemplary full-mark answer.

For mcq questions:
- "type": "mcq"
- "question": conceptual question.
- "options": 4 options.
- "answer_index": 0 to 3.
- "max_marks": 1
- "explanation": brief rationale.

Return ONLY JSON:
{{
  "title": "Comprehensive Test: {course['subject']}",
  "total_marks": 20,
  "questions": [...]
}}"""
    prompt = f"Set {count} questions covering: {', '.join(topic_titles)}"
    if has_api_key():
        try:
            raw = groq.generate(prompt, system=system, json_mode=True, temperature=0.5, max_tokens=3500)
        except Exception:
            raw = None
    else:
        raw = None

    if not raw or not isinstance(raw, dict) or not raw.get("questions"):
        raw = {
            "title": f"Test: {course['subject']}",
            "questions": [
                {
                    "id": "q1",
                    "type": "subjective",
                    "question": f"Explain the fundamental principles and applications of {topic_titles[0] if topic_titles else 'this subject'}.",
                    "max_marks": 5,
                    "expected_points": ["Clear definitions", "Key equations or rules", "Practical application"],
                    "model_answer": "A comprehensive answer should define the topic, state relevant laws or formulas, and give a clear practical example."
                }
            ]
        }
    test_id = f"ctest_{uuid.uuid4().hex[:8]}"
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
        "course_id": cid,
        "title": raw.get("title", f"Test: {course['subject']}"),
        "total_marks": total_marks,
        "questions": clean_questions,
        "created": cl.now_iso()
    }
    storage.put_doc("tests", test_id, test_record)

    public_questions = []
    for q in clean_questions:
        pq = {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            "max_marks": q["max_marks"]
        }
        if q["type"] == "mcq":
            pq["options"] = q["options"]
        public_questions.append(pq)

    return jsonify(test_id=test_id, title=test_record["title"], total_marks=total_marks, questions=public_questions)


import school_routes  # noqa: E402  (onboarding, My Study, Progress, Notes, Books, Exam Paper, Library)

school_routes.init(app, ApiError=ApiError, current_user=current_user, clamp=clamp)
import exam_routes  # noqa: E402  (exams: syllabus, mock papers, exam hall, results)
exam_routes.init(app, ApiError=ApiError, current_user=current_user)


if __name__ == "__main__":
    print("AI विद्यालय is running. Open http://127.0.0.1:5000 in your browser.")
    kb.data()  # load the built-in course notes now so the first click is instant
    print("Chat and built-in subjects answer from offline data. Groq is optional: a backup for questions the")
    print("offline data cannot answer, and for custom subjects.")
    print("Web lookup (GeeksforGeeks etc.): " + ("ON" if has_search_key() else "OFF (add TAVILY_API_KEY in .env to turn it on)"))
    if not has_api_key():
        print("No Groq key set. That is fine: everything built in works without it.")
    else:
        import threading

        def _startup_check():
            ok, message = groq.check()
            print(("OK: " if ok else "PROBLEM: ") + message, flush=True)
        threading.Thread(target=_startup_check, daemon=True).start()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
