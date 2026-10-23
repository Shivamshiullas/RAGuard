"""Lightweight agentic router.

Decides the path for each student message; it never decides whether college
facts are true. Obvious cases are handled by rules (greetings, thanks, simple
single college questions). Ambiguous intent and multi-part questions go to the
LLM planner, whose output is validated with Pydantic. If planning fails, a
safe fallback is used. The plan only selects from fixed agents; model output
can never call arbitrary tools or execute code.
"""

from __future__ import annotations

import logging
import re

from pydantic import BaseModel, Field, ValidationError

from .config import get_settings
from .llm import LLMUnavailable, get_llm
from .schemas import PlanTask, RouterPlan

log = logging.getLogger(__name__)

GREETING_REPLY = (
    "Hello! I'm the college assistant. Ask me about fees, admissions, registration dates, the academic "
    "calendar, syllabus, exams or campus information, and I'll answer from the official college documents."
)
THANKS_REPLY = "You're welcome! Let me know if there's anything else you'd like to know about the college."
BYE_REPLY = "Goodbye, and good luck with your studies!"
CAPABILITIES_REPLY = (
    "I answer questions using the college's official documents: fees, admissions, registration and "
    "academic calendar dates, syllabus and course structure, exams, campus rules and facilities. "
    "You can also attach a screenshot (PNG or JPG) of a notice and ask about it. Every college answer "
    "includes the document and page it came from."
)
CLARIFY_REPLY = "Could you tell me a bit more about what you'd like to know? For example: fees, dates, courses or campus rules."
IMAGE_ONLY_QUESTION = "Explain what this screenshot says, using the official college documents."
DECLINE_REPLY = (
    "Sorry, I can only help with questions about the college, such as fees, admissions, academic dates, "
    "courses, exams and campus information."
)

_GREETING = re.compile(
    r"^(hi+|hii+|hello+|hey+|heya|hola|namaste|yo|sup|what'?s up|wassup|good\s+(morning|afternoon|evening|day)|"
    r"greetings|hi there|hello there|hey there)( (there|bot|assistant|buddy|bro|friend))?$"
)
_THANKS = re.compile(r"^(thanks?( you)?( so much| a lot| very much)?|thank u|thx|ty|tysm|cheers|ok thanks|great thanks|"
                     r"awesome|cool|great|nice|ok(ay)?|got it|perfect)$")
_BYE = re.compile(r"^(bye+|goodbye|see (you|ya)|good night|take care|cya)$")
_CAPABILITIES = re.compile(r"^(who are you|what are you|what can you do|how can you help( me)?|help|what do you know)$")

COLLEGE_TERMS = re.compile(
    r"\b(fee|fees|tuition|scholarship|admission|admissions|apply|application|registration|register|enrol|enroll|"
    r"semester|sem|syllabus|course|courses|subject|credit|credits|exam|exams|examination|timetable|time table|"
    r"schedule|calendar|deadline|holiday|holidays|vacation|attendance|hostel|library|campus|canteen|transport|bus|"
    r"department|faculty|professor|hod|dean|principal|grade|grading|cgpa|sgpa|gpa|marks|result|results|backlog|"
    r"re-?exam|supplementary|internship|placement|lab|labs|unit|units|prerequisite|b\.?tech|m\.?tech|mba|degree|"
    r"programme|program|class|classes|lecture|admit card|hall ticket|uniform|dress code|rules|regulation|"
    r"regulations|policy|policies|refund|payment|installment|instalment|document|documents|certificate|"
    r"transfer|migration|ragging|club|clubs|fest|sports|gym|wifi|located|location|address|contact|office)\b",
    re.I,
)
_MULTI_SPLIT = re.compile(r"\?\s+|\?$|;\s+|\n+|\s+(?:and also|also|plus|as well as)\s+", re.I)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^a-z' ]+", " ", text.lower()).split())


def extract_filters(text: str) -> dict[str, str | None]:
    semester = re.search(r"\b(?:sem(?:ester)?)\s*[-#]?\s*(\d{1,2})\b|\b(\d{1,2})(?:st|nd|rd|th)\s+sem(?:ester)?\b", text, re.I)
    year = re.search(r"\b(20\d\d)\s*[-/]\s*(\d{2,4})\b", text)
    return {
        "semester": f"Semester {semester.group(1) or semester.group(2)}" if semester else None,
        "academic_year": f"{year.group(1)}-{year.group(2)[-2:]}" if year else None,
    }


def _task(task_id: str, question: str, agent: str = "text_agent", deps: list[str] | None = None) -> PlanTask:
    return PlanTask(task_id=task_id, question=question[:1000], dependencies=deps or [], suggested_agent=agent,
                    **extract_filters(question))


def split_questions(message: str) -> list[str]:
    parts = [p.strip(" ,.") for p in _MULTI_SPLIT.split(message) if p and p.strip(" ,.")]
    return [p if p.endswith("?") else p + "?" for p in parts if len(p.split()) >= 2]


def rule_route(message: str, has_image: bool) -> RouterPlan | None:
    """Deterministic routing for obvious cases; None means 'ask the planner'."""
    text = message.strip()
    norm = _norm(text)
    if not has_image:
        if not norm:
            return RouterPlan(intent="unclear", requires_rag=False, clarification_question=CLARIFY_REPLY)
        if _GREETING.match(norm):
            return RouterPlan(intent="general", requires_rag=False, direct_response=GREETING_REPLY)
        if _THANKS.match(norm):
            return RouterPlan(intent="general", requires_rag=False, direct_response=THANKS_REPLY)
        if _BYE.match(norm):
            return RouterPlan(intent="general", requires_rag=False, direct_response=BYE_REPLY)
        if _CAPABILITIES.match(norm):
            return RouterPlan(intent="general", requires_rag=False, direct_response=CAPABILITIES_REPLY)

    if has_image:
        # The screenshot drives the first task; any extra typed questions become text tasks.
        questions = split_questions(text) if text else []
        if len(questions) <= 1:
            return RouterPlan(intent="college_specific", requires_rag=True, execution_mode="direct",
                              tasks=[_task("t1", text or IMAGE_ONLY_QUESTION, "image_agent")])
        return None

    questions = split_questions(text)
    if len(questions) <= 1 and COLLEGE_TERMS.search(text):
        return RouterPlan(intent="college_specific", requires_rag=True, execution_mode="direct", tasks=[_task("t1", text)])
    return None


# ---------------------------------------------------------------------------
# LLM planner
# ---------------------------------------------------------------------------

PLANNER_SYSTEM = """You are the request router for a college assistant chatbot. Classify the student's message and plan tasks. You do not answer college questions yourself.

intent:
- "general": greetings, thanks, small talk, or general questions that need no college-specific facts (e.g. study tips). Put a short friendly reply in "direct_response". Never state college facts (fees, dates, rules) in it.
- "college_specific": one question about this college (fees, admissions, dates, calendar, syllabus, courses, exams, hostel, rules, campus, facilities, contacts). One task.
- "multi_task": several distinct college questions in one message. One task per question (max {max_tasks}), each a standalone question.
- "unclear": too vague to act on. Put one short question in "clarification_question".
- "out_of_scope": unrelated to the college and not suitable small talk (e.g. coding help, news, other institutions).
Informal, slang or misspelled wording is fine: interpret it charitably, do not mark it unclear just for being casual.

For tasks: "dependencies" lists task_ids whose answers are needed first (e.g. "fee for my semester, and when is it due" -> due date may depend on fee task only if it truly needs that answer). Most tasks are independent. Use "semester" like "Semester 5" and "academic_year" like "2025-26" only when stated.
{image_note}
Reply with JSON only:
{{"intent": "...", "requires_rag": true|false, "execution_mode": "direct"|"parallel"|"sequential"|"mixed",
 "tasks": [{{"task_id": "t1", "question": "...", "category": null, "semester": null, "academic_year": null, "dependencies": [], "suggested_agent": "text_agent"}}],
 "clarification_question": null, "direct_response": null}}"""


class _PlannerOutput(BaseModel):
    intent: str
    requires_rag: bool = False
    execution_mode: str = "direct"
    tasks: list[dict] = Field(default_factory=list)
    clarification_question: str | None = None
    direct_response: str | None = None


def llm_plan(message: str, has_image: bool) -> RouterPlan:
    settings = get_settings()
    image_note = (
        "The student attached a screenshot. Give the task about the screenshot suggested_agent \"image_agent\"."
        if has_image else ""
    )
    system = PLANNER_SYSTEM.format(max_tasks=settings.max_subtasks, image_note=image_note)
    raw = get_llm().generate_json(f"Student message:\n{message}", _PlannerOutput, system)
    data = raw.model_dump()
    data["tasks"] = data["tasks"][: settings.max_subtasks]
    if data["intent"] in ("college_specific", "multi_task"):
        data["requires_rag"] = True
    else:
        data["requires_rag"] = False
        data["tasks"] = []
    if data["intent"] == "college_specific" and len(data["tasks"]) > 1:
        data["intent"] = "multi_task"
    plan = RouterPlan.model_validate(data)
    for task in plan.tasks:
        if not has_image and task.suggested_agent == "image_agent":
            task.suggested_agent = "text_agent"
        filters = extract_filters(task.question)
        task.semester = task.semester or filters["semester"]
        task.academic_year = task.academic_year or filters["academic_year"]
    if has_image and plan.tasks and not any(t.suggested_agent == "image_agent" for t in plan.tasks):
        plan.tasks[0].suggested_agent = "image_agent"
    deps = any(t.dependencies for t in plan.tasks)
    if len(plan.tasks) > 1:
        plan.execution_mode = "mixed" if deps and any(not t.dependencies for t in plan.tasks[1:]) else (
            "sequential" if deps else "parallel")
    elif plan.tasks:
        plan.execution_mode = "direct"
    return plan


def fallback_plan(message: str, has_image: bool) -> RouterPlan:
    """Planner failed: one conservative RAG task per detected question (bounded)."""
    if not message.strip() and not has_image:
        return RouterPlan(intent="unclear", requires_rag=False, clarification_question=CLARIFY_REPLY)
    questions = split_questions(message)[: get_settings().max_subtasks] or [message.strip() or IMAGE_ONLY_QUESTION]
    tasks = [_task(f"t{i + 1}", q, "image_agent" if has_image and i == 0 else "text_agent")
             for i, q in enumerate(questions)]
    return RouterPlan(
        intent="multi_task" if len(tasks) > 1 else "college_specific", requires_rag=True, tasks=tasks,
        execution_mode="parallel" if len(tasks) > 1 else "direct",
    )


def route(message: str, has_image: bool = False) -> RouterPlan:
    plan = rule_route(message, has_image)
    if plan is not None:
        return plan
    try:
        plan = llm_plan(message, has_image)
    except (LLMUnavailable, ValidationError, ValueError) as exc:
        log.warning("Planner unavailable or invalid, using fallback: %s", str(exc)[:200])
        return fallback_plan(message, has_image)
    if plan.intent == "general" and not plan.direct_response:
        plan.direct_response = CAPABILITIES_REPLY
    if plan.intent == "unclear" and not plan.clarification_question:
        plan.clarification_question = CLARIFY_REPLY
    if has_image and not plan.requires_rag:
        # A screenshot is always about college material; read it instead of chatting.
        return fallback_plan(message, has_image)
    return plan
