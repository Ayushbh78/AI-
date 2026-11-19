"""LangChain & LangGraph LLM Interface for Groq.
Provides initialized ChatGroq instances with automatic fallback and temperature controls.
"""
from langchain_groq import ChatGroq
from services.config import get_setting, has_api_key

DEFAULT_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODELS = ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]


def get_llm(temperature=0.4, max_tokens=6000, json_mode=False, model_name=None):
    """Return a configured ChatGroq instance for LangChain and LangGraph agent pipelines."""
    key = get_setting("GROQ_API_KEY")
    if not key:
        raise ValueError("GROQ_API_KEY is not configured in .env.")

    model = model_name or get_setting("GROQ_MODEL", DEFAULT_MODEL)

    kwargs = {
        "api_key": key,
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": 60,
        "max_retries": 2
    }
    if json_mode:
        kwargs["model_kwargs"] = {"response_format": {"type": "json_object"}}

    return ChatGroq(**kwargs)
