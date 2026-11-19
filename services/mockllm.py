"""A small simulated LLM with real retrieval (RAG) over the built-in notes. Runs locally.

Honest description: there is no neural network here. The "model" retrieves the best matching notes
(BM25 keyword score + hashed-embedding cosine similarity) and writes the answer from templates.
Everything that calls it is labelled as simulated.
"""
import math
import re
import threading
import time
import uuid
import zlib
from collections import Counter

from . import knowledge as kb

MODEL_CHAT, MODEL_EMBED, MODEL_RAG = "campus-llm-1", "campus-embed-1", "campus-rag-1"
DIMS = 128
MIN_SCORE = 1.2

STOP = set("""a an the and or of to in on for with is are was were be been it this that these those as at by from into
than then so such can could should would will may might do does did not no you your we our they their he she his her
its i me my what which who whom how why when where about over under between also if but because while during each
any all more most other some tell explain please give there here hello hi hey""".split())

_lock = threading.Lock()
_index = None


def _stem(word):
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def tokens(text):
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    return [_stem(w) for w in words if w not in STOP and (len(w) > 1 or w.isdigit())]


def embed(text, dims=DIMS):
    """Hashed bag-of-words embedding (unigrams and bigrams), L2 normalised. Deterministic and instant."""
    toks = tokens(text)
    vec = [0.0] * dims
    grams = [(t, 1.0) for t in toks] + [(a + "_" + b, 0.5) for a, b in zip(toks, toks[1:])]
    for gram, weight in grams:
        h = zlib.crc32(gram.encode("utf-8"))
        sign = 1.0 if zlib.crc32(b"s" + gram.encode("utf-8")) & 1 else -1.0
        vec[h % dims] += sign * weight
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _doc(s, lvl, ti, t, kind, q, a, fi):
    q_toks = tokens(q)
    toks = q_toks + tokens(a) + tokens(t["title"])
    weighted = Counter(toks)
    for term in q_toks:          # words in the question count double
        weighted[term] += 1
    return {
        "id": f"{s['id']}.{lvl}.{ti}#{kind[0]}{fi}", "key": f"{s['id']}.{lvl}.{ti}", "sid": s["id"], "kind": kind,
        "subject": s["name"], "level": kb.LEVEL_NAME[lvl], "topic": t["title"], "mn": t["mn"],
        "q": q, "a": a, "tf": weighted, "len": len(toks) or 1, "vec": embed(f"{q} {a} {t['title']}"),
    }


def _build():
    docs = []
    for s, lvl, ti, t, fi, q, a in kb.iter_facts():
        docs.append(_doc(s, lvl, ti, t, "fact", q, a, fi))
    for s, lvl, ti, t in kb.iter_topics():
        docs.append(_doc(s, lvl, ti, t, "overview", f"Explain {t['title']}", t["ov"], 0))
        docs.append(_doc(s, lvl, ti, t, "example", f"Worked example: {t['title']}", t["ex"], 0))
    df = Counter()
    for d in docs:
        for term in d["tf"]:
            df[term] += 1
    avg = sum(d["len"] for d in docs) / max(1, len(docs))
    return {"docs": docs, "df": df, "avg": avg, "n": len(docs)}


def index():
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                _index = _build()
    return _index


def retrieve(query, subject=None, topic_key=None, k=3):
    """Top-k notes for a query: [{id, key, subject, level, topic, q, a, mn, score, bm25, cosine}]."""
    ix = index()
    q_terms = set(tokens(query))
    if not q_terms:
        return []
    q_vec = embed(query)
    scored = []
    for d in ix["docs"]:
        if subject and d["sid"] != subject:
            continue
        bm, matched = 0.0, 0
        for term in q_terms:
            tf = d["tf"].get(term, 0)
            if not tf:
                continue
            matched += 1
            idf = math.log(1 + (ix["n"] - ix["df"][term] + 0.5) / (ix["df"][term] + 0.5))
            bm += idf * (tf * 2.5) / (tf + 1.5 * (0.25 + 0.75 * d["len"] / ix["avg"]))
        if bm <= 0 or matched < 0.5 * len(q_terms):
            continue
        cos = sum(x * y for x, y in zip(q_vec, d["vec"]))
        score = bm + 3.0 * max(cos, 0.0)
        if topic_key and d["key"] == topic_key:
            score *= 1.5
        scored.append({k_: d[k_] for k_ in ("id", "key", "kind", "subject", "level", "topic", "q", "a", "mn")}
                       | {"score": round(score, 3), "bm25": round(bm, 3), "cosine": round(cos, 3)})
    scored.sort(key=lambda h: h["score"], reverse=True)
    return scored[:k]


def _s(text):
    return str(text).replace("*", "\u2217")


NO_ANSWER = ("I do not have a good answer for that yet. Try rephrasing it, or ask about AI, Machine Learning, "
             "DSA, Calculus or Engineering Maths.")
_KEEP_CAPS = {"its", "both", "nearly", "zero", "left", "it", "their"}


def _cap(text):
    return text[:1].upper() + text[1:]


def _plain_word(word):
    """True for an ordinary capitalised word such as Harmonic (not O(n), TP or GPT)."""
    return word.isalpha() and word[0].isupper() and (word[1:].islower() or word == "A")


def _lower_first(text):
    first = text.split()[0] if text.split() else ""
    return text[0].lower() + text[1:] if _plain_word(first) else text


def _end(text):
    return text if text[-1:] in ".!?" else text + "."


def _best_sentences(text, q_terms):
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    scores = [sum(1 for t in q_terms if t in set(tokens(x))) for x in sents]
    best = max(scores)
    if best == 0:
        return sents[0]
    return " ".join([x for x, sc in zip(sents, scores) if sc == best][:2])


def _direct(h, q_terms=()):
    """Turn the chosen note into plain sentences. No headings, no 'from the notes'."""
    if h["kind"] == "overview":
        return _best_sentences(h["a"], q_terms)
    if h["kind"] != "fact":
        return h["a"].strip()
    q, a = h["q"].strip(), h["a"].strip()
    m = re.match(r"^What (is|are) (.+)\?$", q)
    if m and len(a.split()) <= 14:
        verb, subject = m.group(1), m.group(2)
        called = re.match(r"^it called (?:when|if) (.+)$", subject)
        if called:  # "What is it called when X?"  ->  "<Answer> is what it is called when X."
            return _end(f"{_cap(a)} is what it is called when {called.group(1)}")
        first = a.split()[0]
        body = _lower_first(a)
        if subject.lower().startswith("the ") and _plain_word(first) and first.lower() not in _KEEP_CAPS \
                and first not in ("A", "An", "The"):
            body = "the " + body
        return _end(f"{_cap(subject)} {verb} {body}")
    m = re.match(r"^What does (.+) do\?$", q)
    if m:
        return _end(f"{_cap(m.group(1))} {_lower_first(a)}")
    return _end(a) if len(a.split()) > 3 else a


def _pick(query, hits):
    """The note that really answers the question: a matching fact, else the topic overview, else None."""
    q_terms = set(tokens(query))
    if not q_terms:
        return None

    def fit(h):
        f = set(tokens(h["q"]))
        if not f:
            return 0.0
        both = len(q_terms & f)
        return min(both / len(q_terms), both / len(f))

    exact = [h for h in hits if h["kind"] == "fact" and fit(h) >= 0.7]
    if exact:
        return max(exact, key=lambda h: h["score"])

    def overview_terms(h):
        return tokens(h["a"] + " " + h["q"])

    overviews = [h for h in hits if h["kind"] == "overview"
                 and len(q_terms & set(overview_terms(h))) / len(q_terms) >= 0.5]
    if overviews:
        def rank(h):
            first = tokens(re.split(r"(?<=[.!?])\s+", h["a"].strip())[0])
            density = sum(overview_terms(h).count(t) for t in q_terms) / len(overview_terms(h))
            # a topic that defines the term at the start of its first sentence wins
            return (len(q_terms & set(first[:6])), len(q_terms & set(first)), density)

        return max(overviews, key=rank)

    named = [h for h in hits if h["kind"] == "fact" and q_terms <= set(tokens(h["a"]))]
    if named:
        return sorted(named, key=lambda h: (not h["q"].startswith("What is it called"), -h["score"]))[0]
    return None


def answer(query, hits, mode="professor"):
    """The answer only. The Socratic style still asks you to recall it first."""
    if not hits or hits[0]["score"] < MIN_SCORE:
        return NO_ANSWER
    fact = next((h for h in hits if h["kind"] == "fact"), None)
    if mode == "socratic" and fact:
        words = fact["a"].split()
        others = [h for h in hits if h is not fact and h["kind"] == "fact"]
        lines = [f"Try to recall it before I tell you: {_s(fact['q'])}",
                 f"Hint: the answer is {len(words)} word{'s' if len(words) != 1 else ''} long and starts with \"{_s(fact['a'][:2])}\".",
                 f"When you have tried, check: **{_s(fact['a'])}**"]
        if others:
            lines.append(f"Next question for you: {_s(others[0]['q'])}")
        return "\n\n".join(lines)
    hit = _pick(query, hits)
    if hit is None:
        return NO_ANSWER
    return _s(_direct(hit, set(tokens(query))))


def run(query, subject=None, topic_key=None, k=3, mode="professor"):
    """Full simulated pipeline with timings: embed -> retrieve -> generate."""
    t0 = time.perf_counter()
    embed(query)
    t1 = time.perf_counter()
    hits = retrieve(query, subject=subject, topic_key=topic_key, k=k)
    t2 = time.perf_counter()
    text = answer(query, hits, mode)
    t3 = time.perf_counter()
    return {
        "answer": text, "hits": hits,
        "timings_ms": {"embed": round((t1 - t0) * 1000, 2), "retrieve": round((t2 - t1) * 1000, 2),
                       "generate": round((t3 - t2) * 1000, 2), "total": round((t3 - t0) * 1000, 2)},
    }


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:24]}"
