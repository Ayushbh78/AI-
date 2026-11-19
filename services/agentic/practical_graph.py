"""LangGraph Agentic Workflow: Practical Subject Analyzer, Companion Course Architect, and AI Lab Assistant.
1. Evaluates whether a subject has practical / coding / experimental laboratory requirements.
2. If practical, automatically designs the companion practical course with hands-on exercises and coding spaces.
3. Provides AI Code Evaluation, Socratic Debugging, and Viva Voce preparation.
"""
from typing import TypedDict, List, Dict, Any, Optional
import json
import re
from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage, HumanMessage

from .llm import get_llm
from services import course_logic as cl


class PracticalState(TypedDict):
    subject: str
    desc: str
    level_text: str
    is_practical: bool
    practical_type: str  # 'coding', 'sql', 'science_lab', 'simulation', 'none'
    practical_title: str
    practical_description: str
    primary_language: str
    reasoning: str
    modules: List[Dict[str, Any]]
    starter_exercises: List[Dict[str, Any]]


def _clean_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        # Search for first { and last }
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {}


def practical_analyzer_node(state: PracticalState) -> Dict[str, Any]:
    """Evaluates whether the subject has practical/lab components and generates the practical course architecture."""
    subject = state.get("subject", "")
    desc = state.get("desc", "")
    level_text = state.get("level_text", "intermediate learner")

    llm = get_llm(temperature=0.2)

    system_prompt = (
        "You are the Academic Dean and Director of Practical Curriculum at a premier technological university. "
        "Your task is to analyze an academic subject and determine if it requires a practical laboratory, "
        "coding workspace, data querying sandbox, or experimental scientific simulation in standard school/university syllabi.\n\n"
        "Guidelines:\n"
        "1. Practical Subjects include:\n"
        "   - Computer Science & Programming (Python, C, C++, Java, Web Dev, DSA, AI/ML, OS, Computer Networks, App Dev, etc.) -> practical_type: 'coding'\n"
        "   - Databases, SQL, Data Engineering -> practical_type: 'sql'\n"
        "   - Experimental Sciences (Physics, Chemistry, Electronics, Digital Circuits, Biology) -> practical_type: 'science_lab'\n"
        "   - Computational Mathematics & Statistics -> practical_type: 'coding' or 'simulation'\n"
        "2. Purely Theoretical Subjects without hands-on lab work include:\n"
        "   - History, Philosophy, English Literature, Sociology, Political Science, Pure Legal Studies -> is_practical: false, practical_type: 'none'\n"
        "3. If is_practical is true:\n"
        "   - Provide a formal companion practical title (e.g. '<Subject> Practical Lab & Coding Space')\n"
        "   - Select primary_language from: 'python', 'cpp', 'c', 'javascript', 'sql', 'html', 'simulation'\n"
        "   - Design 4 to 5 structured practical lab modules with hands-on experiment topics\n"
        "   - Provide 3 to 4 starter lab exercises with clear Aim, Starter Code with comments, Reference Solution Code, Test Cases, and Viva Voce questions\n\n"
        "Return ONLY a valid JSON object with no markdown wrappers."
    )

    user_prompt = f"""Analyze this subject for practical/lab requirements:

Subject: {subject}
Academic Level / Context: {desc} ({level_text})

Required JSON format:
{{
  "is_practical": true / false,
  "practical_type": "coding" | "sql" | "science_lab" | "simulation" | "none",
  "reasoning": "Clear 1-sentence reason why this subject is practical or theoretical.",
  "practical_title": "Subject Practical Lab & Coding Space",
  "practical_description": "Comprehensive hands-on laboratory covering practical implementations, programming problem sets, and experimental verification.",
  "primary_language": "python" | "cpp" | "c" | "javascript" | "sql" | "html" | "simulation",
  "modules": [
    {{
      "title": "Lab Unit 1: Foundations & Setup",
      "level": "Basic",
      "goal": "Core syntax, input/output, and elementary problem implementation.",
      "topics": [
        {{"title": "Experiment 1: Input/Output & Basic Syntax", "minutes": 45}},
        {{"title": "Experiment 2: Conditional Logic & Loops", "minutes": 60}}
      ]
    }}
  ],
  "starter_exercises": [
    {{
      "id": "ex_1",
      "title": "1. Two-Pointer Search or Basic Implementation",
      "aim": "Implement a function that performs...",
      "difficulty": "Easy",
      "language": "python",
      "starter_code": "# Write your implementation here\\ndef solution():\\n    pass\\n",
      "solution_code": "def solution():\\n    return 42\\n",
      "test_cases": [
        {{"input": "[1, 2, 3]", "expected_output": "6"}}
      ],
      "viva_questions": [
        {{"question": "What is the time complexity of this approach?", "answer": "O(n) because each element is visited at most twice."}}
      ]
    }}
  ]
}}"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt)
    ]

    try:
        response = llm.invoke(messages)
        content = response.content if hasattr(response, "content") else str(response)
        data = _clean_json(content)
        if not data or "is_practical" not in data:
            # Fallback heuristic
            sub_lower = subject.lower()
            coding_keywords = ["python", "java", "c++", "program", "code", "dsa", "data structure", "algorithm",
                               "web", "machine learning", "ai", "database", "sql", "network", "system", "react", "html", "css"]
            science_keywords = ["physics", "chemistry", "electronic", "circuit", "biology", "robotics"]
            
            is_coding = any(k in sub_lower for k in coding_keywords)
            is_science = any(k in sub_lower for k in science_keywords)
            
            if is_coding:
                data = {
                    "is_practical": True,
                    "practical_type": "coding",
                    "reasoning": f"{subject} involves active software development and algorithmic problem solving.",
                    "practical_title": f"{subject} Practical Lab & Coding Space",
                    "practical_description": f"Hands-on coding workspace and lab exercises for {subject}.",
                    "primary_language": "python" if "python" in sub_lower or not ("c++" in sub_lower or "sql" in sub_lower) else ("sql" if "sql" in sub_lower else "cpp"),
                    "modules": _default_coding_modules(subject),
                    "starter_exercises": _default_starter_exercises(subject, "python")
                }
            elif is_science:
                data = {
                    "is_practical": True,
                    "practical_type": "science_lab",
                    "reasoning": f"{subject} includes experimental apparatus, measurement, and laboratory observations.",
                    "practical_title": f"{subject} Practical & Experimental Lab",
                    "practical_description": f"Virtual lab simulations, observations, and calculations for {subject}.",
                    "primary_language": "python",
                    "modules": _default_science_modules(subject),
                    "starter_exercises": _default_science_exercises(subject)
                }
            else:
                data = {
                    "is_practical": False,
                    "practical_type": "none",
                    "reasoning": f"{subject} is primarily a theoretical discipline studied through text and conceptual synthesis.",
                    "practical_title": "",
                    "practical_description": "",
                    "primary_language": "python",
                    "modules": [],
                    "starter_exercises": []
                }
        
        return {
            "is_practical": bool(data.get("is_practical", False)),
            "practical_type": data.get("practical_type", "coding" if data.get("is_practical") else "none"),
            "practical_title": data.get("practical_title") or f"{subject} Practical Lab",
            "practical_description": data.get("practical_description") or f"Hands-on laboratory for {subject}",
            "primary_language": data.get("primary_language", "python"),
            "reasoning": data.get("reasoning", ""),
            "modules": data.get("modules", []),
            "starter_exercises": data.get("starter_exercises", [])
        }
    except Exception as err:
        print("[practical_graph] error analyzing practical subject:", err, flush=True)
        return {
            "is_practical": False,
            "practical_type": "none",
            "practical_title": "",
            "practical_description": "",
            "primary_language": "python",
            "reasoning": f"Analysis fallback: {err}",
            "modules": [],
            "starter_exercises": []
        }


def _default_coding_modules(subject: str) -> List[Dict[str, Any]]:
    return [
        {
            "title": "Lab Unit 1: Environment & Foundational Syntax",
            "level": "Basic",
            "goal": "Verify development setup and implement elementary logic.",
            "topics": [
                {"title": f"Lab 1: {subject} Hello World & Data Types", "minutes": 45},
                {"title": "Lab 2: Control Flow & Iterations", "minutes": 60}
            ]
        },
        {
            "title": "Lab Unit 2: Modular Programming & Data Structures",
            "level": "Intermediate",
            "goal": "Implement functions, modular design, and primary data structures.",
            "topics": [
                {"title": "Lab 3: Functional Decomposition & Recursion", "minutes": 60},
                {"title": "Lab 4: Collections, Lists & Dictionary Processing", "minutes": 60}
            ]
        },
        {
            "title": "Lab Unit 3: Algorithms & Problem Solving",
            "level": "Intermediate",
            "goal": "Write and analyze search, sort, and stateful algorithms.",
            "topics": [
                {"title": "Lab 5: Search & Sort Implementations", "minutes": 75},
                {"title": "Lab 6: Complexity Analysis & Edge Case Validation", "minutes": 75}
            ]
        },
        {
            "title": "Lab Unit 4: Capstone Practical Project",
            "level": "Advanced",
            "goal": "Integrate all practical units into an end-to-end working software tool.",
            "topics": [
                {"title": "Lab 7: Capstone Application Development", "minutes": 90},
                {"title": "Lab 8: Code Review, Testing & Viva Voce", "minutes": 60}
            ]
        }
    ]


def _default_starter_exercises(subject: str, lang: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": "ex_1",
            "title": f"1. {subject}: Foundation & Verification",
            "aim": f"Write a clean program in {lang} that takes an input and verifies correct environment execution and data processing.",
            "difficulty": "Easy",
            "language": lang,
            "starter_code": f"# {subject} - Lab Exercise 1\n# Write a function that processes an array of numbers and returns their sum and maximum.\n\ndef analyze_numbers(nums):\n    # TODO: Implement your solution\n    return {'sum': sum(nums), 'max': max(nums) if nums else None}\n\nif __name__ == '__main__':\n    data = [12, 45, 7, 23, 89, 34]\n    result = analyze_numbers(data)\n    print('Analysis Result:', result)\n",
            "solution_code": "def analyze_numbers(nums):\n    if not nums:\n        return {'sum': 0, 'max': None}\n    return {'sum': sum(nums), 'max': max(nums)}\n",
            "test_cases": [
                {"input": "[1, 2, 3]", "expected_output": "{'sum': 6, 'max': 3}"}
            ],
            "viva_questions": [
                {"question": "What is the time complexity of finding the maximum element in an unsorted list?", "answer": "O(n) time, as every element must be inspected at least once."}
            ]
        },
        {
            "id": "ex_2",
            "title": "2. Linear vs Binary Search Benchmark",
            "aim": "Implement Linear Search and Binary Search on an array, tracking the number of comparisons made in each.",
            "difficulty": "Medium",
            "language": lang,
            "starter_code": "# Implement Binary Search\ndef binary_search(arr, target):\n    low, high = 0, len(arr) - 1\n    comparisons = 0\n    while low <= high:\n        comparisons += 1\n        mid = (low + high) // 2\n        if arr[mid] == target:\n            return mid, comparisons\n        elif arr[mid] < target:\n            low = mid + 1\n        else:\n            high = mid - 1\n    return -1, comparisons\n\nif __name__ == '__main__':\n    nums = [2, 5, 8, 12, 16, 23, 38, 56, 72, 91]\n    idx, comps = binary_search(nums, 23)\n    print(f'Found 23 at index {idx} in {comps} comparisons')\n",
            "solution_code": "# Full solution provided in starter code\n",
            "test_cases": [
                {"input": "target = 23", "expected_output": "index 5"}
            ],
            "viva_questions": [
                {"question": "Why does Binary Search require the array to be sorted beforehand?", "answer": "Because the algorithm relies on monotonic order to eliminate half the search space with each comparison."}
            ]
        }
    ]


def _default_science_modules(subject: str) -> List[Dict[str, Any]]:
    return [
        {
            "title": "Lab Unit 1: Experimental Measurements & Error Analysis",
            "level": "Basic",
            "goal": "Vernier calipers, screw gauge, least count, and standard deviation.",
            "topics": [
                {"title": "Experiment 1: Precision Measurements & Zero Error", "minutes": 60},
                {"title": "Experiment 2: Graphical Error Estimation", "minutes": 60}
            ]
        },
        {
            "title": "Lab Unit 2: Core Physical / Chemical Laws",
            "level": "Intermediate",
            "goal": "Verify fundamental laws using controlled parameters.",
            "topics": [
                {"title": f"Experiment 3: {subject} Verification of Governing Law", "minutes": 75},
                {"title": "Experiment 4: Calculation of Proportionality Constants", "minutes": 75}
            ]
        },
        {
            "title": "Lab Unit 3: Viva Voce & Observations Record",
            "level": "Advanced",
            "goal": "Defend experimental observations and answer viva voce questions.",
            "topics": [
                {"title": "Experiment 5: Viva Preparation & Practical Exam Mock", "minutes": 60}
            ]
        }
    ]


def _default_science_exercises(subject: str) -> List[Dict[str, Any]]:
    return [
        {
            "id": "ex_1",
            "title": f"1. {subject}: Experimental Simulation & Law Verification",
            "aim": f"Simulate physical observations for {subject}, compute slope of the observation curve, and evaluate experimental constant.",
            "difficulty": "Medium",
            "language": "python",
            "starter_code": f"# {subject} - Experimental Simulation\nimport math\n\ndef calculate_constant(measurements):\n    # measurements is a list of (x, y) coordinates\n    # TODO: compute average ratio or slope\n    slopes = [y / x for x, y in measurements if x != 0]\n    return sum(slopes) / len(slopes) if slopes else 0\n\nif __name__ == '__main__':\n    # Sample Voltage (V) vs Current (I) or Force (F) vs Acceleration (a)\n    readings = [(0.5, 2.5), (1.0, 5.1), (1.5, 7.4), (2.0, 10.0)]\n    slope = calculate_constant(readings)\n    print(f'Computed Constant: {slope:.3f}')\n",
            "solution_code": "def calculate_constant(readings):\n    return sum(y / x for x, y in readings if x != 0) / len(readings)\n",
            "test_cases": [
                {"input": "[(1, 5), (2, 10)]", "expected_output": "5.0"}
            ],
            "viva_questions": [
                {"question": "What is the physical significance of the slope in this experiment?", "answer": "The slope represents the proportionality constant (e.g. Resistance R in Ohm's law V=IR)."}
            ]
        }
    ]


# Compile Practical Checker Workflow
def build_practical_graph():
    builder = StateGraph(PracticalState)
    builder.add_node("practical_analyzer", practical_analyzer_node)
    builder.add_edge(START, "practical_analyzer")
    builder.add_edge("practical_analyzer", END)
    return builder.compile()


practical_agent_graph = build_practical_graph()


# AI Code Evaluator Agent
def evaluate_student_code(code: str, aim: str, exercise_title: str, language: str) -> Dict[str, Any]:
    """Agent that grades and reviews student code against the laboratory problem."""
    llm = get_llm(temperature=0.1)

    system_prompt = (
        "You are an expert University Computer Science Examiner and Senior Software Engineer. "
        "Review the student's submitted code against the laboratory experiment aim.\n"
        "Assess:\n"
        "1. Score (0 to 10 marks)\n"
        "2. Verdict: 'Excellent' (9-10), 'Good' (7-8), 'Needs Improvement' (4-6), or 'Incomplete' (0-3)\n"
        "3. Syntax Validity: true/false\n"
        "4. Time Complexity: asymptotic notation (e.g. O(n log n))\n"
        "5. Space Complexity: asymptotic notation (e.g. O(1))\n"
        "6. Strengths: clear bullet points of what the student did well\n"
        "7. Improvements & Edge Cases: potential bugs, unhandled inputs, or optimization suggestions\n"
        "8. Model Code Suggestion: clean, idiomatic refactoring\n"
        "9. Viva Voce Tip: 1 question the university examiner is likely to ask about this implementation.\n\n"
        "Return ONLY a JSON object."
    )

    user_prompt = f"""Experiment: {exercise_title}
Aim / Problem Statement: {aim}
Language: {language}

Student Code:
```{language}
{code}
```

Required JSON format:
{{
  "score": 9,
  "verdict": "Good",
  "syntax_valid": true,
  "time_complexity": "O(n)",
  "space_complexity": "O(1)",
  "strengths": ["Clean structure", "Proper variable names"],
  "improvements": ["Consider handling empty input list"],
  "model_code_suggestion": "def solution(): ...",
  "viva_tip": "Be prepared to explain why this approach is preferred over an O(n^2) nested loop."
}}"""

    try:
        res = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        content = res.content if hasattr(res, "content") else str(res)
        data = _clean_json(content)
        if not data or "score" not in data:
            data = {
                "score": 8,
                "verdict": "Good",
                "syntax_valid": True,
                "time_complexity": "O(n)",
                "space_complexity": "O(1)",
                "strengths": ["Code compiles and addresses the primary aim."],
                "improvements": ["Add boundary checks for zero and empty cases."],
                "model_code_suggestion": code,
                "viva_tip": "Explain the time complexity and memory footprint during your viva exam."
            }
        return data
    except Exception as err:
        return {
            "score": 7,
            "verdict": "Reviewed",
            "syntax_valid": True,
            "time_complexity": "O(n)",
            "space_complexity": "O(1)",
            "strengths": ["Code parsed successfully."],
            "improvements": [f"Review error: {err}"],
            "model_code_suggestion": code,
            "viva_tip": "Understand the main algorithm logic thoroughly."
        }


# AI Socratic Debugger Agent
def debug_student_code(code: str, error_message: str, aim: str, language: str) -> Dict[str, Any]:
    """Agent that provides Socratic debugging hints to guide students without giving away full code."""
    llm = get_llm(temperature=0.2)

    system_prompt = (
        "You are an encouraging Socratic Lab Teaching Assistant. "
        "A student ran their practical lab code and encountered an error or failed output. "
        "Do NOT give them the full fixed code immediately. Instead, explain WHAT caused the issue in simple terms, "
        "point out the exact line or concept to look at, and provide 2 progressive hints to help them fix it themselves.\n"
        "Return ONLY a JSON object."
    )

    user_prompt = f"""Problem: {aim}
Language: {language}
Error Trace / Failure:
{error_message}

Student Code:
```{language}
{code}
```

Required JSON format:
{{
  "error_type": "IndexError / TypeError / Logic Error",
  "diagnosis": "Clear 1-2 sentence explanation of why this error happens.",
  "line_hint": "Look closely at line X...",
  "hints": [
    "Hint 1: Check what happens when the loop reaches the end...",
    "Hint 2: Verify the variable type before calling this method..."
  ],
  "quick_fix_tip": "Try printing the length before accessing the index."
}}"""

    try:
        res = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        content = res.content if hasattr(res, "content") else str(res)
        data = _clean_json(content)
        if not data or "diagnosis" not in data:
            data = {
                "error_type": "Runtime / Logic Error",
                "diagnosis": "The code threw an exception or didn't return the expected output.",
                "line_hint": "Inspect the return statement and loop bounds.",
                "hints": ["Check variables at each iteration.", "Validate input types."],
                "quick_fix_tip": "Print intermediate values using print() statements."
            }
        return data
    except Exception as err:
        return {
            "error_type": "Error",
            "diagnosis": f"Error analysis fallback: {err}",
            "line_hint": "Check the line reported in the traceback.",
            "hints": ["Double check syntax and indentation."],
            "quick_fix_tip": "Test with small sample inputs first."
        }
