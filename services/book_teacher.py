"""RAG-based Book Teacher: teaches students according to the content of any book.

Supports:
- Curated textbooks (ready out of the box)
- User-uploaded books (PDF, TXT, MD) chunked and indexed via RAG
- Chapter-by-chapter and topic-by-topic interactive teaching
- Socratic tutoring, concept explanations, and doubt answering with page citations
- Book-grounded test generation
"""
import json
import os
import re
import uuid
from datetime import datetime
from pathlib import Path

from . import groq, prompts, rag, storage
from .config import DATA_DIR, has_api_key

BOOKS_DIR = DATA_DIR / "books"
BOOKS_DIR.mkdir(parents=True, exist_ok=True)

CURATED_BOOKS = [
    {
        "id": "book_science_10",
        "title": "NCERT Science - Class 10 (Physics, Chemistry & Biology)",
        "author": "NCERT",
        "category": "School Science",
        "description": "Comprehensive textbook covering Chemical Reactions, Life Processes, Electricity, and Light.",
        "is_curated": True,
        "chapters": [
            {"number": 1, "title": "Chemical Reactions and Equations", "pages": "1-18"},
            {"number": 2, "title": "Acids, Bases and Salts", "pages": "19-35"},
            {"number": 3, "title": "Life Processes: Nutrition, Respiration & Transport", "pages": "36-72"},
            {"number": 4, "title": "Light: Reflection and Refraction", "pages": "73-102"},
            {"number": 5, "title": "Electricity and Circuits", "pages": "103-128"}
        ],
        "chunks": [
            # Chapter 1: Chemical Reactions
            {"page": 2, "text": "Chemical Reactions and Equations: Whenever a chemical change occurs, we say a chemical reaction has taken place. Observations that help determine whether a chemical reaction has taken place include change in state, change in colour, evolution of a gas, and change in temperature. Magnesium ribbon burns with a dazzling white flame and changes into a white powder of magnesium oxide: 2Mg + O2 -> 2MgO."},
            {"page": 5, "text": "A balanced chemical equation has an equal number of atoms of each element on both sides of the arrow. This follows the Law of Conservation of Mass, which states that mass can neither be created nor destroyed in a chemical reaction. Example: Fe + H2O -> Fe3O4 + H2 balanced becomes 3Fe + 4H2O -> Fe3O4 + 4H2."},
            {"page": 9, "text": "Types of Chemical Reactions: 1. Combination Reaction: When two or more substances combine to form a single product. Example: CaO (quicklime) + H2O -> Ca(OH)2 (slaked lime) with huge release of heat. Reactions in which heat is released are called exothermic reactions. 2. Decomposition Reaction: A single reactant breaks down into simpler products. Thermal decomposition of calcium carbonate: CaCO3 + heat -> CaO + CO2."},
            {"page": 13, "text": "Displacement Reaction: A more reactive element displaces a less reactive element from its compound. Example: Fe + CuSO4 (blue) -> FeSO4 (green) + Cu. Double Displacement Reaction: Reactions in which there is an exchange of ions between the reactants. Example: Na2SO4 + BaCl2 -> BaSO4 (white precipitate) + 2NaCl."},
            {"page": 16, "text": "Oxidation and Reduction (Redox): If a substance gains oxygen or loses hydrogen during a reaction, it is oxidised. If it loses oxygen or gains hydrogen, it is reduced. In CuO + H2 -> Cu + H2O, copper oxide is reduced to copper, while hydrogen is oxidised to water. Corrosion is the deterioration of metals by moisture and acids (e.g. rusting of iron: hydrated iron oxide). Rancidity is oxidation of fats and oils resulting in bad smell and taste, prevented by antioxidants or flushing with nitrogen."},

            # Chapter 2: Acids, Bases, Salts
            {"page": 21, "text": "Acids turn blue litmus red and produce H+ (aq) or H3O+ ions in aqueous solution. Bases turn red litmus blue, feel soapy, and produce OH- ions in aqueous solution. Acid + Base -> Salt + Water (Neutralisation reaction). Example: HCl + NaOH -> NaCl + H2O. The pH scale measures hydrogen ion concentration from 0 (strongly acidic) to 14 (strongly alkaline), with 7 being neutral. Human blood has a pH range of 7.35 to 7.45."},
            {"page": 28, "text": "Important Salts: Bleaching powder (CaOCl2) produced by chlorine on dry slaked lime Ca(OH)2. Baking soda is sodium hydrogen carbonate (NaHCO3), used in baking powder with mild tartaric acid. Washing soda is Na2CO3.10H2O (sodium carbonate decahydrate). Plaster of Paris is calcium sulphate hemihydrate (CaSO4.1/2H2O), obtained by heating gypsum (CaSO4.2H2O) at 373 K."},

            # Chapter 3: Life Processes
            {"page": 40, "text": "Life Processes: Autotrophic nutrition is carried out by green plants through photosynthesis: 6CO2 + 12H2O + Sunlight + Chlorophyll -> C6H12O6 (glucose) + 6O2 + 6H2O. Events in photosynthesis: 1. Absorption of light energy by chlorophyll. 2. Conversion of light energy to chemical energy and splitting of water molecules into hydrogen and oxygen. 3. Reduction of carbon dioxide to carbohydrates."},
            {"page": 48, "text": "Human Digestion: Salivary amylase breaks starch into simple sugars in the mouth. Stomach secretes hydrochloric acid (HCl), pepsin enzyme for protein digestion, and mucus to protect the inner lining. Small intestine is the site of complete digestion of carbohydrates, proteins, and fats. Bile juice from the liver makes medium alkaline and emulsifies fats. Pancreatic juice contains trypsin (proteins) and lipase (emulsified fats). Villi in the small intestine increase surface area for absorption."},
            {"page": 55, "text": "Respiration in humans: Glucose (6-carbon) breaks in cytoplasm into pyruvate (3-carbon). In presence of oxygen (mitochondria), pyruvate gives CO2, H2O, and 36-38 ATP. In absence of oxygen in yeast (fermentation), it gives ethanol, CO2, and 2 ATP. In lack of oxygen in human muscle cells, it produces lactic acid (causes muscle cramps) and energy."},
            {"page": 63, "text": "Transportation in Humans: The heart is a muscular organ with four chambers (right atrium, right ventricle, left atrium, left ventricle) preventing mixing of oxygenated and deoxygenated blood. Double circulation: blood passes through the heart twice during each cardiac cycle (pulmonary and systemic circulation). Arteries carry oxygenated blood under high pressure away from heart (thick elastic walls). Veins carry deoxygenated blood towards heart with valves to prevent backflow."},

            # Chapter 4: Light
            {"page": 78, "text": "Laws of Reflection: 1. The angle of incidence equals the angle of reflection (i = r). 2. The incident ray, normal to the mirror at the point of incidence, and the reflected ray all lie in the same plane. Spherical mirrors: Concave mirrors converge rays (used in headlights, solar furnaces, shaving mirrors). Convex mirrors diverge rays, always give diminished, virtual, erect images, and have a wide field of view (used as rear-view mirrors in vehicles). Mirror formula: 1/f = 1/v + 1/u. Magnification m = -v/u = h'/h."},
            {"page": 91, "text": "Refraction of Light: Bending of light when passing from one transparent medium to another. Snell's Law: sin(i) / sin(r) = constant (refractive index n21). Refraction through lenses: Convex lens converges light; Concave lens diverges light. Lens formula: 1/f = 1/v - 1/u. Magnification m = v/u = h'/h. Power of a lens P = 1 / f(in metres), measured in Dioptres (D). Converging lens has positive power; diverging lens has negative power."},

            # Chapter 5: Electricity
            {"page": 108, "text": "Electric Current (I) is the rate of flow of electric charges: I = Q / t. SI unit is Ampere (A). Electric Potential Difference (V) between two points is work done per unit charge: V = W / Q. SI unit is Volt (V). Ohm's Law: The potential difference across the ends of a metallic conductor is directly proportional to current flowing through it, provided temperature remains constant: V = I * R, where R is resistance in Ohms (Ω)."},
            {"page": 118, "text": "Factors affecting resistance: Resistance R is directly proportional to length (l) and inversely proportional to area of cross-section (A): R = ρ * (l / A), where ρ is electrical resistivity of the material. Resistors in Series: Equivalent resistance R = R1 + R2 + R3. Resistors in Parallel: 1/R = 1/R1 + 1/R2 + 1/R3. Joule's Law of Heating: Heat produced H = I^2 * R * t. Electric Power P = V * I = I^2 * R = V^2 / R. Commercial unit of electrical energy is kilowatt-hour (kWh), 1 kWh = 3.6 x 10^6 Joules."}
        ]
    },
    {
        "id": "book_python_cs",
        "title": "Python Programming & Core Computer Science",
        "author": "Dr. Anita Sharma & Prof. K. Raman",
        "category": "Computer Science",
        "description": "Essential concepts of Python, Data Structures, OOP, and Algorithmic Thinking.",
        "is_curated": True,
        "chapters": [
            {"number": 1, "title": "Python Foundations & Memory Model", "pages": "1-25"},
            {"number": 2, "title": "Data Structures: Lists, Tuples, Dictionaries & Sets", "pages": "26-58"},
            {"number": 3, "title": "Functions, Scope & Recursion", "pages": "59-88"},
            {"number": 4, "title": "Object-Oriented Programming (OOP) in Python", "pages": "89-124"},
            {"number": 5, "title": "Algorithms: Searching, Sorting & Big-O Notation", "pages": "125-160"}
        ],
        "chunks": [
            {"page": 8, "text": "Python Fundamentals: Python is an interpreted, high-level, dynamically typed language created by Guido van Rossum. Variables are references to objects in memory; everything in Python is an object. Mutable objects (lists, dictionaries, sets) can be altered after creation. Immutable objects (integers, floats, strings, tuples, frozensets) cannot have their contents changed in place; operations return a new object with a new id()."},
            {"page": 32, "text": "Python Collections: Lists are ordered, mutable sequences supporting slicing list[start:stop:step] and methods append(), extend(), pop(), sort(). Dictionaries are key-value mappings implemented as hash tables offering O(1) average lookup, insertion, and deletion. Keys must be hashable and immutable. Sets are unordered collections of unique elements providing set algebra: union (|), intersection (&), and difference (-)."},
            {"page": 64, "text": "Functions and Closures: Functions in Python are first-class citizens: they can be passed as arguments, returned from other functions, and stored in variables. *args collects positional arguments into a tuple, **kwargs collects keyword arguments into a dictionary. A generator function uses yield instead of return to produce a lazy sequence of values on demand, saving memory when processing massive datasets."},
            {"page": 95, "text": "Object-Oriented Programming: The four pillars of OOP are Abstraction, Encapsulation, Inheritance, and Polymorphism. Classes define blueprints; __init__ is the constructor method initializing instance attributes. Dunder (double underscore) methods like __str__, __repr__, __len__, and __eq__ provide operator overloading. Multiple inheritance uses Method Resolution Order (MRO) calculated by C3 linearization."},
            {"page": 134, "text": "Algorithmic Complexity: Big-O notation characterizes the upper bound on execution time or space as input size n grows. Common complexities: O(1) Constant, O(log n) Logarithmic (Binary Search), O(n) Linear, O(n log n) Linearithmic (MergeSort, QuickSort average), O(n^2) Quadratic (BubbleSort, SelectionSort). Binary search requires a sorted array and halves the search space each step by comparing target with midpoint."}
        ]
    },
    {
        "id": "book_wings_of_fire",
        "title": "Wings of Fire: An Autobiography",
        "author": "Dr. A.P.J. Abdul Kalam",
        "category": "Biography & Inspiration",
        "description": "Inspiring life journey of the Missile Man of India, from Rameswaram to ISRO and DRDO leadership.",
        "is_curated": True,
        "chapters": [
            {"number": 1, "title": "Orientation: Childhood in Rameswaram", "pages": "1-32"},
            {"number": 2, "title": "Creation: Education and Early Flight Research", "pages": "33-78"},
            {"number": 3, "title": "Propitiation: Building the SLV-3 at ISRO", "pages": "79-130"},
            {"number": 4, "title": "Contemplation: The Guided Missile Programme (IGMDP)", "pages": "131-180"}
        ],
        "chunks": [
            {"page": 12, "text": "Childhood in Rameswaram: Kalam was born into a middle-class Tamil Muslim family in the island town of Rameswaram. His father Jainulabdeen was a boat owner and imam who lived with austere simplicity, teaching Abdul that adversity always presents opportunities for introspection. His mother Ashiamma fed countless guests daily. Kalam distributed newspapers as a young boy to support his family during tough times."},
            {"page": 45, "text": "Early Engineering Journey: Kalam studied aeronautical engineering at the Madras Institute of Technology (MIT). His design of a low-altitude attack aircraft came under strict review by Professor Srinivasan, who gave him a 3-day ultimatum to finish the design or lose his scholarship. Kalam worked sleeplessly over the weekend and completed the design, earning high praise from his mentor for determination under pressure."},
            {"page": 92, "text": "The SLV-3 Rocket Project: At ISRO under the vision of Dr. Vikram Sarabhai and Satish Dhawan, Kalam was appointed Project Director for India's first satellite launch vehicle, SLV-3. In August 1979, the first experimental flight failed and plunged into the Bay of Bengal. Satish Dhawan took full responsibility in front of the press. On July 18, 1980, SLV-3 successfully launched the Rohini satellite into orbit, and Dhawan made Kalam face the press to celebrate the success, demonstrating true leadership."},
            {"page": 150, "text": "The Integrated Guided Missile Programme: Kalam led DRDO's IGMDP to develop five indigenous missile systems: Prithvi (surface-to-surface), Trishul (short-range surface-to-air), Akash (medium-range surface-to-air), Nag (anti-tank), and Agni (technology demonstrator for intermediate-range ballistic missile). Kalam emphasizes teamwork, indigenous technology, overcoming setbacks, and instilling scientific temper in the youth."}
        ]
    }
]


# ---------- uploaded books ----------
# Saved through storage.py, so with DATABASE_URL set they live in Supabase and survive Render restarts
# (they used to be written to a local file that Render erases). The small list (title, chapters ...) and the big text
# of each book are kept apart, so opening the Books page stays fast however many books were uploaded.

ALLOWED_BOOK_TYPES = (".pdf", ".txt", ".md")


def _legacy_file(username):
    return BOOKS_DIR / f"{username}_books.json"


def _book_key(username, book_id):
    return f"{username}__{book_id}"


def _meta_of(book):
    return {
        "id": book["id"],
        "title": book["title"],
        "author": book.get("author", "Uploaded Book"),
        "category": book.get("category", "My Uploads"),
        "description": book.get("description", ""),
        "chapters": book.get("chapters", []),
        "chunk_count": len(book.get("chunks", [])),
        "is_curated": False,
        "created": book.get("created", ""),
    }


def _load_meta(username):
    """The user's uploaded-book list (without the book text). Old local files are moved over once."""
    meta = storage.get_doc("bookmeta", username)
    if meta is not None:
        return meta
    meta = []
    legacy = _legacy_file(username)
    if legacy.exists():
        try:
            old_books = json.loads(legacy.read_text(encoding="utf-8"))
            for book in old_books:
                storage.put_doc("bookdata", _book_key(username, book["id"]), book)
                meta.append(_meta_of(book))
            storage.put_doc("bookmeta", username, meta)
            legacy.rename(legacy.with_suffix(".json.migrated"))
        except Exception:  # noqa: BLE001  a broken old file must never break the Books page
            return []
    return meta


def list_books(username):
    """Return all available books (curated presets + user's uploaded books). Light: no book text is loaded."""
    out = []
    for b in _load_meta(username):  # user uploaded books first
        item = dict(b)
        item["description"] = item.get("description") or f"{item.get('chunk_count', 0)} text sections extracted."
        out.append(item)
    for c in CURATED_BOOKS:
        out.append({
            "id": c["id"],
            "title": c["title"],
            "author": c["author"],
            "category": c["category"],
            "description": c["description"],
            "chapters": c["chapters"],
            "chunk_count": len(c["chunks"]),
            "is_curated": True,
            "created": "System"
        })
    return out


def get_book(username, book_id):
    """Retrieve one complete book record with its text chunks."""
    for c in CURATED_BOOKS:
        if c["id"] == book_id:
            return c
    _load_meta(username)  # makes sure old local books were moved over
    return storage.get_doc("bookdata", _book_key(username, book_id))


def add_uploaded_book(username, stream, filename, title="", author="", category="My Uploads"):
    """Extract pages, chunk with RAG, store as an indexed book. Returns the book's small record (no text)."""
    ext = Path(filename or "").suffix.lower()
    if ext not in ALLOWED_BOOK_TYPES:
        raise ValueError("Please choose a PDF, TXT or MD file.")
    pages = rag.extract(stream, ext)
    chunks = rag.chunk_pages(pages)[:rag.MAX_CHUNKS_PER_COURSE]
    if not chunks:
        raise ValueError("Could not read any text from this file. Scanned PDFs (photos of pages) cannot be read: use a PDF with selectable text.")

    book_title = title.strip() or Path(filename).stem.replace("_", " ").replace("-", " ").title()
    book_id = f"ubook_{uuid.uuid4().hex[:10]}"

    # Auto-detect chapters or divide into topical parts
    chapters = []
    sample_text = "\n".join(c["text"] for c in chunks[:15])
    ch_matches = re.findall(r"(?:chapter|unit|module|part)\s+([0-9ivxlcdm]+)[:\.\-\s]+([^\n\r\.]{4,60})", sample_text, re.IGNORECASE)
    if ch_matches:
        for idx, (num, ch_title) in enumerate(ch_matches[:12], start=1):
            chapters.append({"number": idx, "title": ch_title.strip().title(), "pages": "Various"})
    else:
        # Create logical chapter blocks based on page distribution
        total_chunks = len(chunks)
        step = max(1, total_chunks // 5)
        for i in range(0, total_chunks, step):
            ch_num = (i // step) + 1
            first_chunk = chunks[i]
            sample_words = " ".join(first_chunk["text"].split()[:5])
            chapters.append({
                "number": ch_num,
                "title": f"Section {ch_num}: {sample_words}...",
                "pages": f"Page {first_chunk.get('page', 1)}"
            })

    book_record = {
        "id": book_id,
        "title": book_title,
        "author": author.strip() or "Unknown Author",
        "category": category,
        "description": f"Uploaded book containing {len(pages)} pages and {len(chunks)} indexed passages.",
        "is_curated": False,
        "created": datetime.now().isoformat(timespec="seconds"),
        "chapters": chapters[:10],
        "chunks": chunks
    }

    _load_meta(username)
    storage.put_doc("bookdata", _book_key(username, book_id), book_record)       # the text
    with storage.update_doc("bookmeta", username, list) as meta:                  # the small list entry
        meta.insert(0, _meta_of(book_record))
    return _meta_of(book_record)


def teach_from_book(username, book_id, topic_or_query, mode="teach", language="en"):
    """
    RAG-based teaching powered by LangGraph Agentic Workflow:
    1. Retriever Agent: selects passages from the book.
    2. Evaluator Agent: grades passage relevance.
    3. Professor Book Tutor Agent: synthesizes structured lecture with page citations.
    """
    book = get_book(username, book_id)
    if not book:
        raise ValueError(f"Book with id {book_id} not found.")

    from services.agentic import book_teacher_agent_graph

    initial_state = {
        "book_title": book["title"],
        "book_author": book.get("author", "the author"),
        "book_chunks": book.get("chunks", []),
        "topic": topic_or_query,
        "mode": mode,
        "language": language,
        "retrieved_docs": [],
        "citations": [],
        "evaluation": "",
        "teaching_lecture": ""
    }

    graph_res = book_teacher_agent_graph.invoke(initial_state)

    return {
        "book_title": book["title"],
        "topic": topic_or_query,
        "mode": mode,
        "teaching": graph_res.get("teaching_lecture", "").strip(),
        "citations": graph_res.get("citations", []),
        "suggested_questions": [
            f"Explain {topic_or_query} with an example from the book",
            f"What are the main formulas or definitions in this section?",
            f"Test my understanding of {topic_or_query}"
        ]
    }


def generate_book_test_data(username, book_id, chapter_or_scope="all", count=5, test_type="mixed", language="en"):
    """
    Generate an interactive test grounded directly in the book content.
    Supports subjective questions (evaluated by LLM) and MCQs.
    """
    book = get_book(username, book_id)
    if not book:
        raise ValueError("Book not found.")

    chunks = book.get("chunks", [])
    if not chunks:
        raise ValueError("No text passages found in this book.")

    # Select relevant chunks for the scope
    if chapter_or_scope and chapter_or_scope != "all":
        searchable_doc = [{"id": book["id"], "name": book["title"], "chunks": chunks}]
        relevant = rag.search(searchable_doc, chapter_or_scope, k=8)
        selected_chunks = [r["text"] for r in relevant] if relevant else [c["text"] for c in chunks[:8]]
    else:
        step = max(1, len(chunks) // 8)
        selected_chunks = [chunks[i]["text"] for i in range(0, min(len(chunks), step * 8), step)]

    context = "\n---\n".join(selected_chunks[:8])

    system = f"""You are an expert examiner setting a test directly based on the book: "{book['title']}".
Generate exactly {count} high quality questions to test student comprehension.
The questions must be grounded in the book content provided below.

Test Type: {test_type}
- If test_type is 'subjective': all questions must be written answer questions (students write complete sentences).
- If test_type is 'mcq': all questions must be 4-option multiple choice questions.
- If test_type is 'mixed': include both multiple choice questions and subjective questions.

For 'subjective' questions:
- "type": "subjective"
- "question": clearly worded question (e.g. explain, derive, compare, analyze).
- "max_marks": 5
- "expected_points": list of 3-4 key concepts/points required for full marks.
- "model_answer": a concise, exemplary answer (2-4 sentences).

For 'mcq' questions:
- "type": "mcq"
- "question": unambiguous conceptual question.
- "options": exactly 4 options.
- "answer_index": integer 0 to 3.
- "max_marks": 1
- "explanation": brief explanation of why the answer is correct.

Return ONLY a valid JSON object matching this schema:
{{
  "title": "Test on {book['title']}",
  "scope": "{chapter_or_scope}",
  "total_marks": 20,
  "questions": [
    {{
      "id": "q1",
      "type": "subjective",
      "question": "...",
      "max_marks": 5,
      "expected_points": ["point 1", "point 2", "point 3"],
      "model_answer": "..."
    }},
    {{
      "id": "q2",
      "type": "mcq",
      "question": "...",
      "options": ["A", "B", "C", "D"],
      "answer_index": 0,
      "max_marks": 1,
      "explanation": "..."
    }}
  ]
}}
{prompts.lang_rule(language)}"""

    prompt = f"""Book Title: {book['title']}
Scope: {chapter_or_scope}
Excerpts from the book to base the test on:
{context}"""

    if has_api_key():
        raw = groq.generate(prompt, system=system, json_mode=True, temperature=0.5, max_tokens=4000)
    else:
        # Fallback test when offline
        raw = {
            "title": f"Review Test: {book['title']}",
            "scope": chapter_or_scope,
            "total_marks": 10,
            "questions": [
                {
                    "id": "q1",
                    "type": "subjective",
                    "question": f"Explain the core thesis and key takeaway described in {book['title']}.",
                    "max_marks": 5,
                    "expected_points": ["Accurate definition of core concept", "Example or evidence from the book", "Real-world significance"],
                    "model_answer": f"The book discusses key principles systematically. Students should explain the main mechanism, laws, or narrative presented in the text."
                },
                {
                    "id": "q2",
                    "type": "mcq",
                    "question": "Which of the following best reflects the book's methodology?",
                    "options": ["Systematic empirical observation and conceptual derivation", "Random guesswork", "Unrelated folklore", "Ignoring experimental data"],
                    "answer_index": 0,
                    "max_marks": 1,
                    "explanation": "The text emphasizes rigorous conceptual foundations and systematic learning."
                }
            ]
        }

    # Normalize question format
    questions = raw.get("questions") if isinstance(raw, dict) else []
    clean_questions = []
    total_marks = 0
    for idx, q in enumerate(questions, start=1):
        q_type = q.get("type", "subjective")
        marks = int(q.get("max_marks", 5 if q_type == "subjective" else 1))
        total_marks += marks
        item = {
            "id": f"q{idx}",
            "type": q_type,
            "question": q.get("question", f"Question {idx}"),
            "max_marks": marks
        }
        if q_type == "mcq":
            item["options"] = q.get("options", ["A", "B", "C", "D"])[:4]
            item["answer_index"] = int(q.get("answer_index", 0))
            item["explanation"] = q.get("explanation", "")
        else:
            item["expected_points"] = q.get("expected_points", ["Conceptual correctness", "Clear reasoning"])
            item["model_answer"] = q.get("model_answer", "")
        clean_questions.append(item)

    test_id = f"btest_{uuid.uuid4().hex[:8]}"
    test_obj = {
        "test_id": test_id,
        "book_id": book_id,
        "book_title": book["title"],
        "title": raw.get("title", f"Test: {book['title']}"),
        "scope": chapter_or_scope,
        "total_marks": total_marks,
        "questions": clean_questions,
        "created": datetime.now().isoformat(timespec="seconds")
    }

    # Cache test for grading
    storage.put_doc("tests", test_id, test_obj)

    # Return public version to client (without answers/model answers during attempt)
    client_questions = []
    for q in clean_questions:
        cq = {
            "id": q["id"],
            "type": q["type"],
            "question": q["question"],
            "max_marks": q["max_marks"]
        }
        if q["type"] == "mcq":
            cq["options"] = q["options"]
        client_questions.append(cq)

    return {
        "test_id": test_id,
        "book_id": book_id,
        "title": test_obj["title"],
        "total_marks": total_marks,
        "questions": client_questions
    }
