"""Agentic AI Suite: LangChain and LangGraph Multi-Agent Systems.

Everything here is loaded on first use (lazy), so the app starts fast and uses little memory on a phone-sized server.
`from services.agentic import book_teacher_agent_graph` still works exactly as before.
"""
import importlib

_LAZY = {
    "get_llm": ".llm",
    "book_teacher_agent_graph": ".book_teacher_graph",
    "professor_agent_graph": ".professor_graph",
    "examiner_agent_graph": ".examiner_graph",
    "syllabus_agent_graph": ".syllabus_graph",
    "practical_agent_graph": ".practical_graph",
    "evaluate_student_code": ".practical_graph",
    "debug_student_code": ".practical_graph",
}

__all__ = list(_LAZY)


def __getattr__(name):
    if name in _LAZY:
        value = getattr(importlib.import_module(_LAZY[name], __name__), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
