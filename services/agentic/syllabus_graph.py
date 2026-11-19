"""LangGraph Agentic Workflow: Curriculum Architect & Syllabus Designer.
Orchestrates web curriculum research, chapter-wise structuring from beginning to advanced,
and complete roadmap synthesis.
"""
from typing import TypedDict, List, Dict, Any
import json
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from .llm import get_llm
from services import course_logic as cl, prompts, websearch


class SyllabusState(TypedDict):
    subject: str
    desc: str
    level_text: str
    hours: float
    days: int
    language: str
    web_research: List[Dict[str, Any]]
    syllabus_raw: Dict[str, Any]
    title: str
    description: str
    modules: List[Dict[str, Any]]
    roadmap: Dict[str, Any]


def web_curriculum_researcher(state: SyllabusState) -> Dict[str, Any]:
    """Agent node that investigates official university and board curricula online."""
    subject = state.get("subject", "")
    desc = state.get("desc", "")
    web = []
    try:
        web = websearch.search(f"{subject} syllabus curriculum chapters modules topics university course {desc}", general=True)
    except Exception as err:
        print("[syllabus_graph] web search error:", err, flush=True)
    return {"web_research": web}


def chapter_architect_agent(state: SyllabusState) -> Dict[str, Any]:
    """Agent node that designs the chapter-wise syllabus and complete roadmap."""
    subject = state.get("subject", "")
    desc = state.get("desc", "")
    hours = state.get("hours", 2.0)
    days = state.get("days", 60)
    level_text = state.get("level_text", "intermediate")
    language = state.get("language", "en")
    web = state.get("web_research", [])

    system, prompt = prompts.school_syllabus(subject, desc, hours, days, level_text, language, web=web)

    try:
        llm = get_llm(temperature=0.35, max_tokens=6500, json_mode=True)
        messages = [
            SystemMessage(content=system),
            HumanMessage(content=prompt)
        ]
        res = llm.invoke(messages)
        parsed = json.loads(res.content)
    except Exception as err:
        print("[syllabus_graph] architect error:", err, flush=True)
        from services import groq
        parsed = groq.generate(prompt, system=system, json_mode=True, temperature=0.4, max_tokens=6500)

    title, description, modules, roadmap = cl.normalize_syllabus_with_roadmap(parsed)
    return {
        "syllabus_raw": parsed,
        "title": title,
        "description": description,
        "modules": modules,
        "roadmap": roadmap
    }


def create_syllabus_graph():
    workflow = StateGraph(SyllabusState)
    workflow.add_node("curriculum_researcher", web_curriculum_researcher)
    workflow.add_node("chapter_architect", chapter_architect_agent)

    workflow.add_edge(START, "curriculum_researcher")
    workflow.add_edge("curriculum_researcher", "chapter_architect")
    workflow.add_edge("chapter_architect", END)

    return workflow.compile()


syllabus_agent_graph = create_syllabus_graph()
