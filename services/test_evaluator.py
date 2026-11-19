"""Comprehensive Test Evaluator & LLM Answer Checker.

Evaluates student answers:
- Subjective written answers: Evaluated by LLM with detailed rubrics,
  marks awarded, key strengths, missed concepts, and model answers.
- Objective / MCQs: Instant grading with explanation.
- Updates student mastery and logs results for adaptive learning.
"""
import json
import uuid
from datetime import datetime

from . import groq, prompts, storage
from .config import has_api_key


def grade_subjective_answer(question_text, student_answer, max_marks=5, expected_points=None, model_answer=None, language="en"):
    """
    Use LangGraph Examiner Agent to evaluate a student's complete written answer.
    """
    from services.agentic import examiner_agent_graph

    state = {
        "question_text": question_text,
        "student_answer": student_answer or "",
        "max_marks": float(max_marks),
        "expected_points": expected_points or ["Accuracy", "Clarity", "Core technical mechanisms"],
        "model_answer": model_answer or "",
        "language": language,
        "marks_awarded": 0.0,
        "strengths": "",
        "missed_points": "",
        "model_answer_out": "",
        "feedback": ""
    }

    res = examiner_agent_graph.invoke(state)
    return {
        "marks_awarded": res.get("marks_awarded", 0.0),
        "max_marks": max_marks,
        "strengths": res.get("strengths", ""),
        "missed_points": res.get("missed_points", ""),
        "model_answer": res.get("model_answer_out", model_answer or ""),
        "feedback": res.get("feedback", "")
    }


def evaluate_test_submission(test_id, student_answers, username=None, language="en"):
    """
    Grade a complete test submission containing multiple questions (MCQ + Subjective).
    student_answers is a dict: {question_id: answer_value}
    - For MCQ, answer_value is option index (0..3).
    - For Subjective, answer_value is the student's written text string.
    """
    test_obj = storage.get_doc("tests", test_id)
    if not test_obj:
        raise ValueError("Test not found or expired.")

    questions = test_obj.get("questions", [])
    graded_questions = []
    total_obtained = 0.0
    total_max = 0

    for q in questions:
        qid = q["id"]
        q_type = q.get("type", "subjective")
        max_marks = q.get("max_marks", 5 if q_type == "subjective" else 1)
        total_max += max_marks
        ans = student_answers.get(qid)

        if q_type == "mcq":
            try:
                chosen_idx = int(ans) if ans is not None else None
            except (ValueError, TypeError):
                chosen_idx = None

            correct_idx = q.get("answer_index", 0)
            is_correct = (chosen_idx == correct_idx)
            marks = float(max_marks) if is_correct else 0.0
            total_obtained += marks

            graded_questions.append({
                "id": qid,
                "type": "mcq",
                "question": q["question"],
                "options": q.get("options", []),
                "chosen_index": chosen_idx,
                "correct_index": correct_idx,
                "is_correct": is_correct,
                "marks_awarded": marks,
                "max_marks": max_marks,
                "explanation": q.get("explanation", "")
            })
        else:
            # Subjective question checked by LLM
            sub_text = str(ans or "").strip()
            eval_res = grade_subjective_answer(
                question_text=q["question"],
                student_answer=sub_text,
                max_marks=max_marks,
                expected_points=q.get("expected_points"),
                model_answer=q.get("model_answer"),
                language=language
            )
            total_obtained += eval_res["marks_awarded"]

            graded_questions.append({
                "id": qid,
                "type": "subjective",
                "question": q["question"],
                "student_answer": sub_text,
                "marks_awarded": eval_res["marks_awarded"],
                "max_marks": max_marks,
                "strengths": eval_res["strengths"],
                "missed_points": eval_res["missed_points"],
                "model_answer": eval_res["model_answer"],
                "feedback": eval_res["feedback"]
            })

    percent = round(100.0 * (total_obtained / total_max)) if total_max else 0
    grade = "A+" if percent >= 90 else "A" if percent >= 80 else "B+" if percent >= 70 else "B" if percent >= 60 else "C" if percent >= 50 else "D"

    overall_feedback = "Excellent performance! You demonstrated thorough conceptual understanding." if percent >= 85 else \
        "Good effort! You grasp the main concepts; review the suggestions and model answers to maximize your score." if percent >= 60 else \
        "Needs revision. Several core concepts require review. Check the model answers and practice with the Book Teacher."

    summary = {
        "test_id": test_id,
        "title": test_obj.get("title", "Test Evaluation"),
        "book_id": test_obj.get("book_id"),
        "total_obtained": round(total_obtained, 1),
        "total_max": total_max,
        "percent": percent,
        "grade": grade,
        "overall_feedback": overall_feedback,
        "questions": graded_questions,
        "graded_at": datetime.now().isoformat(timespec="seconds")
    }

    # Save result in storage
    storage.put_doc("test_results", test_id, summary)

    # Log to school activity if username given
    if username:
        from . import school
        school.log(username, "test", f"Test: {test_obj.get('title', 'Test')}",
                   minutes=max(10, round(len(questions) * 3)),
                   score=percent, course_id=test_obj.get("book_id"),
                   course_title=test_obj.get("title"))

    return summary
