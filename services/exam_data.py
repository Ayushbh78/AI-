"""Fixed facts about the exams: the list of exams and papers, and a built-in syllabus + pattern for the most used ones.

These are the SAFETY NET. When a Tavily key is set, services/exams.py reads the syllabus from the web first and uses
this data only when the web result is missing or unusable. Subject "marks" are approximate typical weightage.
"""

GATE_PAPERS = [
    ("DA", "Data Science and Artificial Intelligence"), ("CS", "Computer Science and Information Technology"),
    ("EC", "Electronics and Communication Engineering"), ("EE", "Electrical Engineering"),
    ("ME", "Mechanical Engineering"), ("CE", "Civil Engineering"), ("CH", "Chemical Engineering"),
    ("IN", "Instrumentation Engineering"), ("PI", "Production and Industrial Engineering"),
    ("BT", "Biotechnology"), ("BM", "Biomedical Engineering"), ("AE", "Aerospace Engineering"),
    ("AG", "Agricultural Engineering"), ("AR", "Architecture and Planning"),
    ("ES", "Environmental Science and Engineering"), ("GE", "Geomatics Engineering"),
    ("GG", "Geology and Geophysics"), ("MN", "Mining Engineering"), ("MT", "Metallurgical Engineering"),
    ("NM", "Naval Architecture and Marine Engineering"), ("PE", "Petroleum Engineering"),
    ("TF", "Textile Engineering and Fibre Science"), ("MA", "Mathematics"), ("PH", "Physics"),
    ("CY", "Chemistry"), ("ST", "Statistics"), ("EY", "Ecology and Evolution"), ("XE", "Engineering Sciences"),
    ("XH", "Humanities and Social Sciences"), ("XL", "Life Sciences"),
]

EXAMS = [
    {"id": "gate", "name": "GATE", "full": "Graduate Aptitude Test in Engineering", "icon": "🎯",
     "paper_label": "Paper / branch", "papers": [{"id": c, "name": n} for c, n in GATE_PAPERS]},
    {"id": "jee-main", "name": "JEE Main", "full": "Joint Entrance Examination (Main)", "icon": "⚙️",
     "paper_label": "Paper", "papers": [{"id": "BTECH", "name": "Paper 1: B.E. / B.Tech"}]},
    {"id": "jee-adv", "name": "JEE Advanced", "full": "Joint Entrance Examination (Advanced)", "icon": "🚀",
     "paper_label": "Paper", "papers": [{"id": "ADV", "name": "Paper 1 and Paper 2"}]},
    {"id": "neet", "name": "NEET UG", "full": "National Eligibility cum Entrance Test (UG)", "icon": "🩺",
     "paper_label": "Paper", "papers": [{"id": "UG", "name": "NEET (UG)"}]},
    {"id": "cat", "name": "CAT", "full": "Common Admission Test (MBA)", "icon": "📈",
     "paper_label": "Paper", "papers": [{"id": "CAT", "name": "CAT"}]},
    {"id": "custom", "name": "Other exam", "full": "Type any exam name", "icon": "✍️", "paper_label": "Paper / stream",
     "papers": []},
]


def exam_by_id(exam_id):
    for e in EXAMS:
        if e["id"] == exam_id:
            return e
    return None


# ---------------------------------------------------------------- patterns
# types: share of question types inside the group (mcq = single correct, msq = one or more correct, nat = numerical answer)

def gate_pattern():
    mix = {"mcq": 0.55, "msq": 0.15, "nat": 0.30}
    return {
        "duration_min": 180, "total_marks": 100,
        "sections": [
            {"name": "General Aptitude", "subject": "General Aptitude",
             "groups": [{"count": 5, "marks": 1, "types": {"mcq": 1}}, {"count": 5, "marks": 2, "types": {"mcq": 1}}]},
            {"name": "Technical Section", "subject": None,
             "groups": [{"count": 25, "marks": 1, "types": dict(mix)}, {"count": 30, "marks": 2, "types": dict(mix)}]},
        ],
        "negative": {"mcq": 1 / 3, "msq": 0, "nat": 0},
        "rules": ["65 questions, 100 marks, 3 hours.",
                  "MCQ: one correct option. Wrong answer: minus 1/3 of the marks (1 mark: -1/3, 2 marks: -2/3).",
                  "MSQ: one or more correct options. Full marks only if every correct option and no wrong option is chosen. No negative marking, no partial marks.",
                  "NAT: type a number with the on-screen keypad. No negative marking."],
    }


def jee_main_pattern():
    sec = lambda s: {"name": s, "subject": s, "groups": [{"count": 20, "marks": 4, "types": {"mcq": 1}},
                                                          {"count": 5, "marks": 4, "types": {"nat": 1}}]}
    return {"duration_min": 180, "total_marks": 300, "sections": [sec("Physics"), sec("Chemistry"), sec("Mathematics")],
            "negative": {"mcq": 0.25, "msq": 0, "nat": 0},
            "rules": ["75 questions, 300 marks, 3 hours: 25 questions each in Physics, Chemistry, Mathematics.",
                      "Each subject: 20 multiple choice questions (+4, wrong answer -1) and 5 numerical value questions (+4, no negative)."]}


def neet_pattern():
    sec = lambda s: {"name": s, "subject": s, "groups": [{"count": 45, "marks": 4, "types": {"mcq": 1}}]}
    return {"duration_min": 180, "total_marks": 720,
            "sections": [sec("Physics"), sec("Chemistry"), sec("Botany"), sec("Zoology")],
            "negative": {"mcq": 0.25, "msq": 0, "nat": 0},
            "rules": ["180 questions, 720 marks, 3 hours.", "Each correct answer +4, each wrong answer -1, unanswered 0."]}


def cat_pattern():
    return {"duration_min": 120, "total_marks": 198,
            "sections": [
                {"name": "Verbal Ability and Reading Comprehension", "subject": "Verbal Ability and Reading Comprehension",
                 "groups": [{"count": 24, "marks": 3, "types": {"mcq": 0.75, "nat": 0.25}}]},
                {"name": "Data Interpretation and Logical Reasoning", "subject": "Data Interpretation and Logical Reasoning",
                 "groups": [{"count": 20, "marks": 3, "types": {"mcq": 0.6, "nat": 0.4}}]},
                {"name": "Quantitative Ability", "subject": "Quantitative Ability",
                 "groups": [{"count": 22, "marks": 3, "types": {"mcq": 0.64, "nat": 0.36}}]}],
            "negative": {"mcq": 1 / 3, "msq": 0, "nat": 0},
            "rules": ["66 questions, 198 marks, 2 hours (the real CAT gives 40 minutes per section; here the clock is one 2-hour timer).",
                      "Multiple choice: +3, wrong answer -1. Typed-in answers (TITA): +3, no negative."]}


def generic_pattern():
    mix = {"mcq": 0.6, "msq": 0.1, "nat": 0.3}
    return {"duration_min": 180, "total_marks": 90,
            "sections": [{"name": "Main Section", "subject": None,
                          "groups": [{"count": 30, "marks": 1, "types": dict(mix)}, {"count": 30, "marks": 2, "types": dict(mix)}]}],
            "negative": {"mcq": 1 / 3, "msq": 0, "nat": 0},
            "rules": ["Standard pattern used because the official pattern could not be read online. Add TAVILY_API_KEY to read it from the web."]}


# ---------------------------------------------------------------- syllabi: {subject: (marks, [topics])}

GA = ("General Aptitude", 15, [
    "Verbal: grammar (tenses, articles, prepositions, conjunctions)", "Verbal: vocabulary, idioms and phrases in context",
    "Verbal: reading comprehension", "Verbal: narrative sequencing and sentence ordering",
    "Quantitative: data interpretation (tables and charts)", "Quantitative: ratios, percentages, powers and logarithms",
    "Quantitative: permutations, combinations and series", "Quantitative: mensuration and geometry",
    "Quantitative: elementary statistics and probability", "Analytical: logical deduction and induction",
    "Analytical: analogy and numerical relations"])

GATE_DA = [
    ("Probability and Statistics", 14, [
        "Counting: permutations and combinations", "Probability axioms, sample space and events",
        "Independent and mutually exclusive events", "Marginal, conditional and joint probability", "Bayes theorem",
        "Conditional expectation and variance", "Mean, median, mode and standard deviation", "Correlation and covariance",
        "Random variables and probability mass functions", "Discrete distributions: uniform, Bernoulli, binomial, Poisson",
        "Continuous random variables and probability density functions",
        "Continuous distributions: uniform, exponential, normal, standard normal",
        "t-distribution and chi-squared distribution", "Cumulative distribution function and conditional PDF",
        "Central limit theorem", "Confidence intervals", "Hypothesis tests: z-test, t-test, chi-squared test"]),
    ("Linear Algebra", 10, [
        "Vector spaces and subspaces", "Linear dependence and independence", "Matrix types: orthogonal, idempotent, partition",
        "Projection matrix", "Quadratic forms", "Systems of linear equations and Gaussian elimination",
        "Eigenvalues and eigenvectors", "Determinant, rank and nullity", "LU decomposition", "Singular value decomposition"]),
    ("Calculus and Optimization", 6, [
        "Functions of a single variable", "Limits, continuity and differentiability", "Taylor series",
        "Maxima and minima", "Optimization of a single variable"]),
    ("Programming, Data Structures and Algorithms", 14, [
        "Programming in Python", "Stacks and queues", "Linked lists", "Trees", "Hash tables",
        "Linear search and binary search", "Selection, bubble and insertion sort", "Divide and conquer: merge sort and quicksort",
        "Graph theory basics", "Graph traversals: BFS and DFS", "Shortest path algorithms"]),
    ("Database Management and Warehousing", 9, [
        "ER model", "Relational model", "Relational algebra and tuple calculus", "SQL", "Integrity constraints",
        "Normal forms", "File organization and indexing", "Data transformation: normalization, discretization, sampling, compression",
        "Data warehouse modelling: multidimensional schema, concept hierarchies, measures"]),
    ("Machine Learning", 22, [
        "Regression and classification problems", "Simple and multiple linear regression", "Ridge regression",
        "Logistic regression", "k-nearest neighbour", "Naive Bayes classifier", "Linear discriminant analysis",
        "Support vector machine", "Decision trees", "Bias-variance trade-off", "Cross-validation: leave-one-out and k-fold",
        "Multi-layer perceptron and feed-forward neural networks", "Clustering and k-means / k-medoid",
        "Hierarchical clustering: single and multiple linkage", "Dimensionality reduction and principal component analysis"]),
    ("Artificial Intelligence", 10, [
        "Uninformed search", "Informed search and heuristics (A*)", "Adversarial search: minimax and alpha-beta",
        "Propositional logic", "Predicate logic", "Reasoning under uncertainty: conditional independence",
        "Bayesian network representation", "Exact inference by variable elimination", "Approximate inference through sampling"]),
]

GATE_CS = [
    ("Engineering Mathematics", 13, [
        "Propositional and first-order logic", "Sets, relations and functions", "Groups, partial orders and lattices",
        "Graph theory", "Combinatorics", "Linear algebra: matrices, systems of equations, eigenvalues",
        "Calculus: limits, continuity, maxima and minima, integration", "Probability and statistics: random variables, distributions, Bayes"]),
    ("Digital Logic", 5, ["Boolean algebra", "Combinational circuits", "Minimization and K-maps",
                          "Number representations and arithmetic", "Sequential circuits: flip-flops, counters, registers"]),
    ("Computer Organization and Architecture", 8, [
        "Machine instructions and addressing modes", "ALU, data path and control unit", "Instruction pipelining and hazards",
        "Memory hierarchy: cache, main memory, secondary storage", "I/O interface: interrupts and DMA"]),
    ("Programming and Data Structures", 11, ["Programming in C", "Recursion", "Arrays, stacks and queues", "Linked lists",
                                             "Trees, binary search trees and heaps", "Graphs"]),
    ("Algorithms", 8, ["Asymptotic analysis", "Searching and sorting", "Hashing", "Greedy algorithms", "Dynamic programming",
                       "Divide and conquer", "Graph traversals, shortest paths and minimum spanning trees"]),
    ("Theory of Computation", 8, ["Regular expressions and finite automata", "Context-free grammars and pushdown automata",
                                  "Closure properties and pumping lemma", "Turing machines", "Decidability and undecidability"]),
    ("Compiler Design", 6, ["Lexical analysis", "Parsing: LL and LR", "Syntax-directed translation", "Runtime environments",
                            "Intermediate code generation", "Local optimization and data flow analysis"]),
    ("Operating System", 9, ["System calls, processes and threads", "Inter-process communication", "Concurrency and synchronization",
                             "Deadlock", "CPU and I/O scheduling", "Memory management and virtual memory", "File systems"]),
    ("Databases", 8, ["ER model", "Relational model", "Relational algebra and tuple calculus", "SQL", "Integrity constraints",
                      "Normal forms", "File organization and indexing (B and B+ trees)", "Transactions and concurrency control"]),
    ("Computer Networks", 9, ["Layering: OSI and TCP/IP", "Switching: packet, circuit, virtual circuit",
                              "Data link layer: framing, error detection, MAC", "Routing protocols", "Congestion control",
                              "TCP, UDP and sockets", "IP addressing and CIDR", "Application layer: DNS, SMTP, HTTP, FTP",
                              "Network security basics"]),
]

JEE_MAIN = [
    ("Physics", 100, ["Units and measurements", "Kinematics", "Laws of motion", "Work, energy and power", "Rotational motion",
                      "Gravitation", "Properties of solids and liquids", "Thermodynamics", "Kinetic theory of gases",
                      "Oscillations and waves", "Electrostatics", "Current electricity", "Magnetic effects of current and magnetism",
                      "Electromagnetic induction and alternating currents", "Electromagnetic waves", "Optics",
                      "Dual nature of matter and radiation", "Atoms and nuclei", "Electronic devices", "Experimental skills"]),
    ("Chemistry", 100, ["Some basic concepts of chemistry", "Atomic structure", "Chemical bonding and molecular structure",
                        "Chemical thermodynamics", "Solutions", "Equilibrium", "Redox reactions and electrochemistry",
                        "Chemical kinetics", "Classification of elements and periodicity", "p-block elements",
                        "d- and f-block elements", "Coordination compounds", "General organic chemistry", "Hydrocarbons",
                        "Organic compounds containing halogens", "Organic compounds containing oxygen",
                        "Organic compounds containing nitrogen", "Biomolecules", "Principles of practical chemistry"]),
    ("Mathematics", 100, ["Sets, relations and functions", "Complex numbers and quadratic equations", "Matrices and determinants",
                          "Permutations and combinations", "Binomial theorem", "Sequences and series",
                          "Limits, continuity and differentiability", "Integral calculus", "Differential equations",
                          "Coordinate geometry", "Three-dimensional geometry", "Vector algebra", "Statistics and probability",
                          "Trigonometry"]),
]

NEET = [
    ("Physics", 180, ["Physical world and measurement", "Kinematics", "Laws of motion", "Work, energy and power", "Rotational motion",
                      "Gravitation", "Properties of bulk matter", "Thermodynamics", "Kinetic theory", "Oscillations and waves",
                      "Electrostatics", "Current electricity", "Magnetic effects and magnetism", "EMI and alternating current",
                      "Electromagnetic waves", "Optics", "Dual nature of matter", "Atoms and nuclei", "Electronic devices"]),
    ("Chemistry", 180, ["Basic concepts of chemistry", "Structure of atom", "Classification of elements and periodicity",
                        "Chemical bonding", "Thermodynamics", "Equilibrium", "Redox reactions", "Solutions", "Electrochemistry",
                        "Chemical kinetics", "p-block, d- and f-block elements", "Coordination compounds",
                        "General organic chemistry", "Hydrocarbons", "Haloalkanes and haloarenes", "Alcohols, phenols and ethers",
                        "Aldehydes, ketones and carboxylic acids", "Amines", "Biomolecules"]),
    ("Botany", 180, ["Diversity of living world", "Structural organisation in plants", "Cell structure and function",
                     "Plant physiology: photosynthesis, respiration, growth", "Reproduction in plants",
                     "Genetics and molecular biology", "Biotechnology", "Ecology and environment"]),
    ("Zoology", 180, ["Animal kingdom", "Structural organisation in animals", "Human physiology: digestion, breathing, circulation, excretion",
                      "Neural and chemical coordination", "Locomotion and movement", "Human reproduction and reproductive health",
                      "Evolution", "Human health and disease", "Biotechnology applications", "Biodiversity and conservation"]),
]

CAT = [
    ("Verbal Ability and Reading Comprehension", 72, ["Reading comprehension", "Para jumbles", "Para summary",
                                                      "Odd sentence out", "Sentence completion and vocabulary in context"]),
    ("Data Interpretation and Logical Reasoning", 60, ["Tables and charts (described in text)", "Caselets", "Arrangements and puzzles",
                                                       "Games and tournaments", "Venn diagrams and sets", "Logical sequencing"]),
    ("Quantitative Ability", 66, ["Arithmetic: percentages, ratio, profit and loss, interest", "Time, speed, distance and work",
                                  "Mixtures and averages", "Algebra: equations, inequalities, functions", "Number system",
                                  "Geometry and mensuration", "Permutations, combinations and probability", "Logarithms, surds and indices"]),
]


def builtin(exam_id, paper):
    """(title, pattern, subjects) of the built-in data, or None. subjects = [(name, marks, [topics])]."""
    if exam_id == "gate":
        if paper == "DA":
            return gate_pattern(), GATE_DA + [GA]
        if paper == "CS":
            return gate_pattern(), GATE_CS + [GA]
        return None
    if exam_id == "jee-main":
        return jee_main_pattern(), JEE_MAIN
    if exam_id == "neet":
        return neet_pattern(), NEET
    if exam_id == "cat":
        return cat_pattern(), CAT
    return None


# Hints that make the generated questions look like the real paper, by subject (matched by words in the subject name).
SUBJECT_STYLE = {
    "machine learning": "Typical: compute a prediction, loss, gradient step, entropy or information gain, a k-means iteration, "
                        "PCA/eigenvalue result, bias-variance reasoning, SVM margin, which statements about an algorithm are true.",
    "probability": "Typical: conditional probability and Bayes with numbers, expectation and variance, named distributions, "
                   "confidence intervals and test statistics, counting problems.",
    "linear algebra": "Typical: rank, determinant, eigenvalues and eigenvectors of small matrices, projections, solving systems, "
                      "SVD facts, properties of matrix types.",
    "calculus": "Typical: limits, derivatives, Taylor expansion, maxima/minima, single-variable optimization.",
    "programming": "Typical: trace a short Python snippet (put code in a fenced block), output prediction, time complexity, "
                   "BST/heap/hash operations, sorting passes, BFS/DFS order, shortest path.",
    "database": "Typical: output of an SQL query on a small table (give the table as a markdown table), normal form of a relation, "
                "relational algebra, indexing, star schema and cube measures.",
    "artificial intelligence": "Typical: A* and minimax with alpha-beta on a small tree described in text, propositional/predicate logic "
                               "entailment, Bayesian network independence, variable elimination factor sizes.",
    "general aptitude": "Typical GA: sentence completion, synonyms/antonyms, idioms, short reading passage with one question, "
                        "arithmetic word problems, data interpretation from a small text table, logical reasoning. "
                        "NO figure-based, spatial or diagram questions.",
    "engineering mathematics": "Typical: logic, sets, graph theory counting, matrix and calculus problems, probability.",
    "algorithms": "Typical: recurrence and complexity, greedy vs dynamic programming outcomes, graph algorithm steps.",
    "operating system": "Typical: scheduling Gantt numbers, page replacement faults, semaphore/deadlock reasoning.",
    "computer networks": "Typical: subnetting and CIDR, TCP window/throughput numbers, routing table reasoning.",
}

EXAM_STYLE = {
    "gate": ("GATE questions are conceptual and numerical, never trivia. Options are plausible. MSQ stems read like "
             "'Which of the following statements is/are correct?'. NAT answers are computed numbers."),
    "jee-main": "JEE Main style: direct but calculation-heavy NCERT-based questions; numerical value answers are integers or 2-decimal numbers.",
    "neet": "NEET style: NCERT-based single-correct questions, statement-based and assertion-reason items, simple numericals.",
    "cat": "CAT style: reasoning-heavy; typed-in answers (TITA) are whole numbers; verbal questions use short passages.",
}
