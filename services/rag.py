"""Small local retrieval system (TF-IDF). No vector database, no embeddings API, works offline."""
import math
import re
from collections import Counter

STOP = set("""a an the and or of to in on for with is are was were be been it this that these those as at by from into
than then so such can could should would will may might do does did not no you your we our they their he she his her
its i me my what which who whom how why when where about over under between also if but because while during each
any all more most other some""".split())

CHUNK_SIZE = 900
CHUNK_OVERLAP = 150
MAX_CHUNKS_PER_COURSE = 4000

_token_cache = {}


def tokenize(text):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


def extract(stream, ext):
    """Return a list of (page_number, text) from a PDF or a plain text file."""
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(stream)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError("This PDF is password protected.")
        pages = []
        for number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            pages.append((number, text))
        return pages
    raw = stream.read()
    text = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
    return [(1, text)]


def chunk_pages(pages):
    chunks = []
    for page_no, text in pages:
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 40:
            continue
        start = 0
        while start < len(text):
            end = min(start + CHUNK_SIZE, len(text))
            if end < len(text):
                cut = text.rfind(". ", start + CHUNK_SIZE // 2, end)
                if cut != -1:
                    end = cut + 1
            piece = text[start:end].strip()
            if piece:
                chunks.append({"page": page_no, "text": piece})
            if end >= len(text):
                break
            start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def search(materials, query, k=4):
    """Return the k best chunks for the query: [{doc, page, text, score}]."""
    q_terms = set(tokenize(query))
    if not q_terms or not materials:
        return []

    entries = []
    for doc in materials:
        for index, chunk in enumerate(doc.get("chunks", [])):
            key = (doc["id"], index)
            if key not in _token_cache:
                _token_cache[key] = Counter(tokenize(chunk["text"]))
            entries.append((doc["name"], chunk, _token_cache[key]))
    if not entries:
        return []

    total = len(entries)
    df = Counter()
    for _, _, tokens in entries:
        for term in q_terms:
            if term in tokens:
                df[term] += 1

    scored = []
    for name, chunk, tokens in entries:
        length = sum(tokens.values()) or 1
        score = 0.0
        for term in q_terms:
            tf = tokens.get(term, 0)
            if tf:
                idf = math.log(1 + total / (1 + df[term]))
                score += (tf / length) * idf * 100
        if score > 0:
            scored.append({"doc": name, "page": chunk["page"], "text": chunk["text"], "score": round(score, 3)})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:k]
