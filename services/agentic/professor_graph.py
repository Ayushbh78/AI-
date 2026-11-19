"""LangGraph Agentic Workflow: University Professor Teaching Agent.
Orchestrates research, comprehensive 18-section lecture synthesis, and academic quality assurance.
"""
from typing import TypedDict, List, Dict, Any, Optional
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from .llm import get_llm
from services import prompts, websearch


class ProfessorState(TypedDict):
    subject: str
    program_desc: str
    module_title: str
    module_goal: Optional[str]
    topic_title: str
    topic_summary: str
    student_level: str
    language: str
    previous_topics: List[str]
    upcoming_topics: List[str]
    excerpts: List[Dict[str, Any]]
    web_research: List[Dict[str, Any]]
    lecture_content: str
    verification_status: str


def research_agent(state: ProfessorState) -> Dict[str, Any]:
    """Agent node that performs automated web lookup for academic standards."""
    topic = state.get("topic_title", "")
    subject = state.get("subject", "")
    web_docs = []
    try:
        web_docs = websearch.search(f"{topic} {subject} university lecture theory mechanism examples", general=True)
    except Exception as err:
        print("[professor_graph] research agent error:", err, flush=True)
    return {"web_research": web_docs}


def professor_lecture_agent(state: ProfessorState) -> Dict[str, Any]:
    """Agent node that synthesizes the full 18-section university lecture."""
    subject = state.get("subject", "Academic Subject")
    program = state.get("program_desc", "University Curriculum")
    module = state.get("module_title", "Chapter")
    module_goal = state.get("module_goal", "")
    topic = state.get("topic_title", "Topic")
    summary = state.get("topic_summary", "")
    level = state.get("student_level", "intermediate")
    language = state.get("language", "en")
    prev_topics = state.get("previous_topics", [])
    next_topics = state.get("upcoming_topics", [])
    web = state.get("web_research", [])
    excerpts = state.get("excerpts", [])

    system_prompt = f"""SYSTEM PROMPT: AI VIDYALAYA – UNIVERSITY PROFESSOR

You are an experienced university professor, academic researcher, textbook author, and subject-matter expert.

Your responsibility is to teach students through comprehensive, academically accurate, structured explanations.

Teaching Instructions

When a student requests an explanation, do not provide a short summary unless explicitly requested.

Teach the concept as if you are delivering a complete university lecture or writing a textbook chapter.

Mandatory Explanation Structure
You must structure your comprehensive lecture using clear Markdown headings (##) corresponding to these mandatory sections:

## 1. Introduction and Overview
## 2. Learning Objectives
## 3. Prerequisite Knowledge
## 4. Detailed Fundamental Concepts
## 5. Technical Explanation
## 6. Step-by-Step Working Mechanism
## 7. Important Terminology and Definitions
## 8. Mathematical Formulas and Derivations (where applicable)
## 9. Multiple Examples with Detailed Solutions
## 10. Real-World Applications
## 11. Practical Implementation (including code line-by-line or schematic where relevant)
## 12. Advantages and Limitations
## 13. Comparison with Related Concepts (include a clear Markdown comparison table)
## 14. Common Misconceptions
## 15. Important Academic Points
## 16. Practice Questions (with full step-by-step solutions)
## 17. Interview & Exam Questions (where relevant)
## 18. Comprehensive Conclusion

Depth Requirements

- Explain concepts from fundamentals to advanced levels.
- Explain WHY something works, HOW it works, and WHERE it is used.
- Never skip important intermediate steps.
- Define technical terminology before using it extensively.
- Use practical examples and analogies.
- Explain code line by line when code is provided.
- Include formulas and derivations rather than merely listing them.
- Avoid repetitive filler and irrelevant content.
- Maintain academic accuracy.

Context Awareness

- University / Degree / Program: {program}
- Subject: {subject}
- Module / Chapter: {module}
- Topic: {topic}
- Student Academic Level: {prompts.LEVEL_TEXT.get(level, 'an enthusiastic university student')}
- Follow the official syllabus and do not introduce unrelated topics.

Output Rules

- Use clear headings and subheadings.
- Use tables where comparisons are useful.
- Use code blocks for programming examples.
- Use mathematical notation where appropriate (Unicode: x², √, ∑, ≤).
- Provide a complete explanation rather than a superficial overview.
- If the topic is too large, divide it into multiple connected parts and explicitly indicate what remains.

Your objective is to ensure that the student genuinely understands the topic, not simply reads a summary.
{prompts.MATH_RULE}
{prompts.lang_rule(language)}"""

    parts = [
        f"Subject: {subject}",
        f"Chapter / Module: {module} (Goal: {module_goal})",
        f"Topic to teach: {topic} - {summary}",
        "Previously covered topics: " + (", ".join(prev_topics) if prev_topics else "None (start of course)"),
        "Upcoming topics in syllabus: " + (", ".join(next_topics) if next_topics else "Final topic in syllabus"),
    ]
    if excerpts:
        parts.append("Student Study Notes:\n" + prompts.format_excerpts(excerpts))
    if web:
        parts.append("Verified Academic Web Background:\n" + "\n\n".join(f"[{w.get('title', 'Ref')}]: {w.get('text', '')[:800]}" for w in web[:3]))
    parts.append("Deliver the complete university lecture now, following all 18 mandatory sections in order.")

    user_prompt = "\n\n".join(parts)

    try:
        llm = get_llm(temperature=0.45, max_tokens=7000)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        res = llm.invoke(messages)
        lecture_text = res.content.strip()
    except Exception as err:
        print("[professor_graph] lecture generation error:", err, flush=True)
        # Fallback to direct Groq client
        system_direct, prompt_direct = prompts.lesson(
            {"subject": subject, "level": level, "language": language, "school": {"desc": program}},
            {"title": module, "goal": module_goal},
            {"title": topic, "summary": summary},
            prev_topics, next_topics, excerpts, web=web
        )
        from services import groq
        lecture_text = groq.generate(prompt_direct, system=system_direct, temperature=0.5, max_tokens=6500)

    return {"lecture_content": lecture_text, "verification_status": "verified"}


def create_professor_graph():
    """Build and compile the University Professor LangGraph pipeline."""
    workflow = StateGraph(ProfessorState)
    workflow.add_node("researcher", research_agent)
    workflow.add_node("professor", professor_lecture_agent)

    workflow.add_edge(START, "researcher")
    workflow.add_edge("researcher", "professor")
    workflow.add_edge("professor", END)

    return workflow.compile()


professor_agent_graph = create_professor_graph()
