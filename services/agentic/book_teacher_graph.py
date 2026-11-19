"""LangGraph Agentic Workflow: RAG Book Teacher Agent.
Orchestrates retrieval, passage evaluation, and structured teaching with page citations.
"""
from typing import TypedDict, List, Dict, Any
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from .llm import get_llm
from services import prompts, rag


class BookTeacherState(TypedDict):
    book_title: str
    book_author: str
    book_chunks: List[Dict[str, Any]]
    topic: str
    mode: str
    language: str
    retrieved_docs: List[Dict[str, Any]]
    citations: List[Dict[str, Any]]
    evaluation: str
    teaching_lecture: str


def retriever_agent(state: BookTeacherState) -> Dict[str, Any]:
    """Retrieve relevant book passages using TF-IDF RAG."""
    chunks = state.get("book_chunks", [])
    topic = state.get("topic", "")
    title = state.get("book_title", "")

    doc = [{"id": "target_book", "name": title, "chunks": chunks}]
    retrieved = rag.search(doc, topic, k=6)

    # Fallback to initial chunks if query has low TF-IDF matches
    if not retrieved and chunks:
        retrieved = [{"doc": title, "page": c.get("page", 1), "text": c.get("text", ""), "score": 1.0} for c in chunks[:4]]

    citations = [
        {
            "page": r["page"],
            "excerpt": r["text"][:280] + ("..." if len(r["text"]) > 280 else ""),
            "score": round(float(r.get("score", 1.0)), 2)
        }
        for r in retrieved
    ]
    return {"retrieved_docs": retrieved, "citations": citations}


def relevance_evaluator_agent(state: BookTeacherState) -> Dict[str, Any]:
    """Agentic critique: evaluates whether retrieved passages contain adequate depth."""
    docs = state.get("retrieved_docs", [])
    if not docs:
        return {"evaluation": "empty"}
    total_chars = sum(len(d.get("text", "")) for d in docs)
    eval_status = "sufficient" if total_chars > 300 else "sparse"
    return {"evaluation": eval_status}


def professor_book_tutor_agent(state: BookTeacherState) -> Dict[str, Any]:
    """LangChain + ChatGroq generation node delivering the university lecture grounded in the book."""
    title = state.get("book_title", "Textbook")
    author = state.get("book_author", "the author")
    topic = state.get("topic", "General Concepts")
    mode = state.get("mode", "teach")
    language = state.get("language", "en")
    docs = state.get("retrieved_docs", [])

    context_str = "\n\n".join(f"[Page {d['page']}]: {d['text']}" for d in docs)

    system_prompt = f"""SYSTEM PROMPT: AI VIDYALAYA – UNIVERSITY PROFESSOR & BOOK TEACHER

You are an experienced university professor, textbook author, and subject-matter expert teaching directly from the book: "{title}" by {author}.

Your responsibility is to teach students through comprehensive, academically accurate, structured explanations based on the content of this book.

Teaching Instructions:
- Deliver a complete university-level lecture grounded in the book's text.
- Do not provide a brief summary unless explicitly requested.
- Explicitly cite the page numbers when introducing definitions, formulas, laws, or key examples (e.g. "According to Page 5...").

Lecture Structure:
## 1. Introduction and Chapter Context
## 2. Learning Objectives
## 3. Prerequisite Knowledge
## 4. Fundamental Concepts (from the Book)
## 5. Technical Explanation & Working Mechanism
## 6. Important Terminology and Definitions
## 7. Mathematical Formulas and Derivations (where applicable)
## 8. Worked Examples with Step-by-Step Solutions
## 9. Real-World Applications & Implementations
## 10. Common Misconceptions & Exam Points
## 11. Practice & Comprehension Check Questions
## 12. Conclusion & Summary

Depth Requirements:
- Explain WHY something works, HOW it works, and WHERE it is used.
- Ground your explanation firmly on the excerpts provided below from the book.
- Never invent citations. Use the provided book excerpts.
{prompts.MATH_RULE}
{prompts.lang_rule(language)}"""

    if mode == "socratic":
        user_prompt = f"""The student wants to explore this concept from the book: "{topic}".
Act as a Socratic teacher: do not simply give away the answer. Guide the student using insights from the book text below. Ask 2-3 thought-provoking questions and provide a brief hint.

Book Excerpts for reference:
{context_str}"""
    elif mode == "doubt":
        user_prompt = f"""The student has a specific doubt regarding the book: "{topic}".
Explain the answer clearly and directly based on the book excerpts below. Clarify common misconceptions.

Book Excerpts for reference:
{context_str}"""
    else:  # 'teach' mode
        user_prompt = f"""Teach a complete, engaging university lecture on the topic/chapter: "{topic}".
Explain the core concepts, principles, solved examples, and real-world intuition using the provided book excerpts.

Book Excerpts for reference:
{context_str}"""

    try:
        llm = get_llm(temperature=0.4, max_tokens=5000)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
        res = llm.invoke(messages)
        lecture_text = res.content.strip()
    except Exception as err:
        print("[book_teacher_graph] agent fallback:", err, flush=True)
        # Fallback using raw groq client
        lecture_text = prompts.book(title, author, "chapterwise", language, excerpt=context_str)[1]

    return {"teaching_lecture": lecture_text}


def create_book_teacher_graph():
    """Build and compile the LangGraph Agent Workflow."""
    workflow = StateGraph(BookTeacherState)
    workflow.add_node("retriever", retriever_agent)
    workflow.add_node("evaluator", relevance_evaluator_agent)
    workflow.add_node("professor_tutor", professor_book_tutor_agent)

    workflow.add_edge(START, "retriever")
    workflow.add_edge("retriever", "evaluator")
    workflow.add_edge("evaluator", "professor_tutor")
    workflow.add_edge("professor_tutor", END)

    return workflow.compile()


# Pre-compiled agent graph
book_teacher_agent_graph = create_book_teacher_graph()
