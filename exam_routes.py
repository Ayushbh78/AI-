"""Pages and API for real-exam preparation and mock tests (GATE, JEE, NEET, CAT ...).

Pages:  /exams (syllabus + study plan)   /exam-hall/<paper>   /exam-result/<attempt>
The Exam Paper page (/exam) uses the same /api/exams/... endpoints.  Logic lives in services/exams.py.
"""
from flask import Blueprint, jsonify, render_template, request

from services import exam_data, exams, school, storage
from services.config import has_api_key, has_search_key

bp = Blueprint("exams", __name__)
_deps = {}


def init(app, **deps):
    _deps.update(deps)
    app.register_blueprint(bp)


def _user():
    return _deps["current_user"]()


def _err(message, status=400):
    return _deps["ApiError"](message, status)


def _data():
    return request.get_json(silent=True) or {}


def _wrap(fn):
    """Turn the engine's ExamError into the app's normal JSON error."""
    try:
        return fn()
    except exams.ExamError as exc:
        raise _err(str(exc), exc.status)


def _catalog():
    return [{"id": e["id"], "name": e["name"], "full": e["full"], "icon": e["icon"], "paper_label": e["paper_label"],
             "papers": e["papers"]} for e in exam_data.EXAMS]


def _ctx():
    return {"catalog": _catalog(), "has_ai": has_api_key(), "has_web": has_search_key()}


def _info_payload(info):
    return {"exam_id": info["exam_id"], "exam": info["exam"], "paper": info["paper"], "paper_name": info["paper_name"],
            "title": info["title"], "origin": info["origin"], "pattern_origin": info["pattern_origin"], "notes": info["notes"],
            "sources": info["sources"], "summary": exams.pattern_summary(info),
            "subjects": [{"name": s["name"], "marks": s["weight"], "topics": s["topics"]} for s in info["subjects"]]}


# ---------------------------------------------------------------- pages

@bp.get("/exams")
def exams_page():
    return render_template("exams.html", ctx=_ctx(), profile=school.get_profile(_user()["username"]) or {})


@bp.get("/exam-hall/<pid>")
def hall(pid):
    user = _user()
    paper = _wrap(lambda: exams.load_paper(user["username"], pid))
    return render_template("exam_hall.html", pid=paper["id"], title=paper["title"], user_name=user["name"])


@bp.get("/exam-result/<aid>")
def result_page(aid):
    return render_template("exam_result.html", aid=aid)


# ---------------------------------------------------------------- api

@bp.post("/api/exams/info")
def api_info():
    d = _data()
    info = _wrap(lambda: exams.get_info(d.get("exam_id"), d.get("paper"), d.get("custom"), bool(d.get("refresh"))))
    return jsonify(ok=True, info=_info_payload(info))


@bp.post("/api/exams/generate")
def api_generate():
    user, d = _user(), _data()
    if d.get("difficulty") not in ("easy", "medium", "hard"):
        raise _err("Choose easy, medium or hard.")
    info = _wrap(lambda: exams.get_info(d.get("exam_id"), d.get("paper"), d.get("custom")))
    names = {s["name"] for s in info["subjects"]}
    selected = [s for s in (d.get("subjects") or []) if s in names] or None
    pid = _wrap(lambda: exams.start_paper(user["username"], info, d["difficulty"], selected))
    return jsonify(ok=True, paper_id=pid)


@bp.get("/api/exams/paper/<pid>/status")
def api_status(pid):
    return jsonify(ok=True, **exams.job_status(_user()["username"], pid))


@bp.get("/api/exams/paper/<pid>/meta")
def api_meta(pid):
    return jsonify(ok=True, **_wrap(lambda: exams.paper_meta(_user()["username"], pid)))


@bp.get("/api/exams/papers")
def api_papers():
    return jsonify(ok=True, papers=exams.list_papers(_user()["username"]))


@bp.post("/api/exams/prepare")
def api_prepare():
    user, d = _user(), _data()
    info = _wrap(lambda: exams.get_info(d.get("exam_id"), d.get("paper"), d.get("custom")))
    profile = school.get_profile(user["username"]) or {}
    try:
        days = max(7, min(365, int(float(d.get("days") or profile.get("plan_days") or 90))))
        hours = max(0.5, min(12, float(d.get("hours") or profile.get("daily_hours") or 3)))
    except (TypeError, ValueError):
        raise _err("Days and hours must be numbers.")
    course, created = exams.prepare_course(user["username"], profile, info, days, hours)
    return jsonify(ok=True, created=created, course_id=course["id"], url=f"/course/{course['id']}")


@bp.post("/api/exams/attempt/start")
def api_attempt_start():
    return jsonify(ok=True, **_wrap(lambda: exams.start_attempt(_user()["username"], _data().get("paper_id"))))


@bp.post("/api/exams/attempt/<aid>/save")
def api_attempt_save(aid):
    return jsonify(ok=True, **_wrap(lambda: exams.save_attempt(_user()["username"], aid, _data())))


@bp.post("/api/exams/attempt/<aid>/submit")
def api_attempt_submit(aid):
    _wrap(lambda: exams.submit_attempt(_user()["username"], aid, _data()))
    return jsonify(ok=True, url=f"/exam-result/{aid}")


@bp.get("/api/exams/attempt/<aid>/result")
def api_attempt_result(aid):
    return jsonify(ok=True, **_wrap(lambda: exams.get_result(_user()["username"], aid)))
