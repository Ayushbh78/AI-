"""LangGraph Agentic Workflow: AI Examiner & Evaluation Agent.
Grades complete student written answers, evaluates conceptual depth, and generates structured rubrics.
"""
from typing import TypedDict, List, Dict, Any
import json
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from .llm import get_llm
from services import prompts


class ExaminerState(TypedDict):
    question_text: str
    student_answer: str
    max_marks: float
    expected_points: List[str]
    model_answer: str
    language: str
    marks_awarded: float
    strengths: str
    missed_points: str
    model_answer_out: str
    feedback: str


def evaluate_single_answer_node(state: ExaminerState) -> Dict[str, Any]:
    """Agent node that evaluates a subjective written answer against rubrics."""
    q_text = state.get("question_text", "")
    ans = state.get("student_answer", "").strip()
    max_m = state.get("max_marks", 5.0)
    expected = state.get("expected_points", ["Accuracy", "Clarity"])
    ref_model = state.get("model_answer", "")
    language = state.get("language", "en")

    if not ans:
        return {
            "marks_awarded": 0.0,
            "strengths": "No answer was provided.",
            "missed_points": "The answer was submitted blank.",
            "model_answer_out": ref_model or "A complete explanation was required.",
            "feedback": "Please attempt to explain your understanding."
        }

    points_str = "\n".join(f"- {p}" for p in expected)
    system_prompt = f"""SYSTEM PROMPT: AI VIDYALAYA – SENIOR EXAMINER & ACADEMIC EVALUATOR

You are a rigorous, fair, and encouraging university examiner checking a student's answer.
Evaluate the student's answer objectively against the question and marking criteria.

Marking Rules:
1. Max Marks for this question: {max_m}.
2. Award marks proportionally based on correctness, depth of explanation, accurate terminology, and clarity.
3. Be fair: If the student expressed the right concepts in their own words, award appropriate marks.
4. If the answer is completely wrong or irrelevant, award 0.
5. Provide:
   - "marks_awarded": number between 0 and {max_m} (can include decimals like 3.5).
   - "strengths": 1-2 sentences on what the student understood and explained accurately.
   - "missed_points": 1-2 sentences pointing out missing definitions, steps, or misconceptions.
   - "model_answer": a concise, exemplary answer showing how to achieve full marks.
   - "feedback": one encouraging concluding comment.

Return ONLY a JSON object:
{{
  "marks_awarded": 4.0,
  "strengths": "...",
  "missed_points": "...",
  "model_answer": "...",
  "feedback": "..."
}}
{prompts.lang_rule(language)}"""

    user_prompt = f"""Question ({max_m} Marks):
{q_text}

Key Criteria / Expected Points:
{points_str}

Reference Model Answer (if any):
{ref_model or 'Standard syllabus expectation'}

Student's Written Answer:
\"\"\"{ans}\"\"\"
"""

    try:
        llm = get_llm(temperature=0.2, max_tokens=1500, json_mode=True)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        res = llm.invoke(messages)
        parsed = json.loads(res.content)
        awarded = float(parsed.get("marks_awarded", max_m * 0.7))
        awarded = max(0.0, min(float(max_m), round(awarded, 1)))

        return {
            "marks_awarded": awarded,
            "strengths": parsed.get("strengths", "Good effort demonstrating conceptual awareness."),
            "missed_points": parsed.get("missed_points", "Could add more specific definitions and keywords."),
            "model_answer_out": parsed.get("model_answer", ref_model or "Standard model answer."),
            "feedback": parsed.get("feedback", "Keep practicing structured answers!")
        }
    except Exception as err:
        print("[examiner_graph] agent error:", err, flush=True)
        # Fallback grading
        words = len(ans.split())
        ratio = min(1.0, max(0.2, words / 35.0))
        return {
            "marks_awarded": round(max_m * ratio, 1),
            "strengths": "Your answer addresses the prompt with relevant explanation.",
            "missed_points": "Review the core textbook chapter to ensure all key formulas and points are covered.",
            "model_answer_out": ref_model or "Standard model answer covers core mechanisms and definitions.",
            "feedback": "Answer reviewed."
        }


def create_examiner_graph():
    workflow = StateGraph(ExaminerState)
    workflow.add_node("evaluator", evaluate_single_answer_node)
    workflow.add_edge(START, "evaluator")
    workflow.add_edge("evaluator", END)
    return workflow.compile()


examiner_agent_graph = create_examiner_graph()
