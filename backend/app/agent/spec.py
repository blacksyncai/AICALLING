"""
The agent specification — the typed, validated object the generator produces
before any prompt text exists (stage B of the pipeline, see app/agent/pipeline.py).

It is produced in two parts so neither model response gets too long:
- strategy:     identity, objectives, persona, variables, qualification, stages,
                tools plan, outcomes, compliance, fact provenance
- conversation: first message, opening script, call-flow branches, objections,
                direct answers, turn-taking additions, voicemail, close

validate_strategy() / validate_conversation() raise InvalidOutput with a
plain message the model can act on when it repairs its answer.
"""

from __future__ import annotations

import re

from app.models.call_log import CALL_OUTCOMES


class InvalidOutput(ValueError):
    pass


_FIELD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,39}$")
_VAR = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")

# Tools the voice runtime really provides (app/agent/runtime.py, app/services/llm.py).
TOOL_END_CALL = "end_call"
TOOL_CHECK = "check_availability"
TOOL_BOOK = "book_appointment"
TOOL_TRANSFER = "transfer_call"
ALL_TOOLS = (TOOL_END_CALL, TOOL_CHECK, TOOL_BOOK, TOOL_TRANSFER)

BASE_VARIABLES = ("name", "full_name", "company", "phone", "email", "role")

# Call-flow branches. Required ones depend on direction and enabled capabilities (required_branches()).
BRANCHES = {
    "interested": "They're interested",
    "partial_interest": "They're somewhat interested or unsure",
    "busy": "They're busy or it's a bad time",
    "not_interested": "They're not interested",
    "not_a_fit": "They're not a fit",
    "wrong_person": "Wrong person or wrong number",
    "question": "They ask a question",
    "objection": "They raise an objection",
    "callback": "They ask for a callback",
    "transfer": "They want to speak to a person now",
    "booking": "They agree to book",
    "send_info": "They ask you to send information",
    "voicemail": "You reach voicemail",
    "screener": "A call screener or gatekeeper answers",
    "do_not_call": "They ask not to be called again",
    "hostile": "They're abusive or inappropriate",
    "disconnect": "The line drops or goes silent",
}


def required_branches(direction: str, flags: dict) -> list[str]:
    keys = ["interested", "partial_interest", "busy", "not_interested", "question", "objection"]
    if direction in ("outbound", "both"):
        keys += ["wrong_person", "voicemail"]
    if flags.get("callback"):
        keys.append("callback")
    if flags.get("transfer"):
        keys.append("transfer")
    if flags.get("booking"):
        keys.append("booking")
    return keys


def _s(v, name: str, max_len: int, required: bool = True) -> str:
    if v is None and not required:
        return ""
    if not isinstance(v, str):
        raise InvalidOutput(f"{name} must be a string")
    v = v.strip()
    if required and not v:
        raise InvalidOutput(f"{name} is empty")
    if len(v) > max_len:
        raise InvalidOutput(f"{name} is too long (max {max_len} characters)")
    return v


def _strs(v, name: str, max_items: int, max_len: int, min_items: int = 0) -> list[str]:
    if v is None:
        v = []
    if not isinstance(v, list):
        raise InvalidOutput(f"{name} must be a list of strings")
    out = [_s(x, name, max_len) for x in v if not (isinstance(x, str) and not x.strip())]
    if len(out) < min_items:
        raise InvalidOutput(f"{name} needs at least {min_items} item(s)")
    return out[:max_items]


def _objs(v, name: str, max_items: int, min_items: int = 0) -> list[dict]:
    if v is None:
        v = []
    if not isinstance(v, list) or not all(isinstance(x, dict) for x in v):
        raise InvalidOutput(f"{name} must be a list of objects")
    if len(v) < min_items:
        raise InvalidOutput(f"{name} needs at least {min_items} item(s)")
    return v[:max_items]


def check_variables(text: str, allowed: set[str], where: str) -> None:
    for m in _VAR.finditer(text or ""):
        if m.group(1) not in allowed:
            raise InvalidOutput(
                f"{where} uses {{{{{m.group(1)}}}}}, which isn't an available variable. "
                f"Use only: {', '.join('{{' + a + '}}' for a in sorted(allowed))}, or plain words.")


def _walk_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_strings(v)


def validate_strategy(p: dict, *, allowed_vars: set[str], allowed_tools: set[str], flags: dict,
                      forced_name: str = "") -> dict:
    ident = p.get("identity") if isinstance(p.get("identity"), dict) else {}
    obj = p.get("objectives") if isinstance(p.get("objectives"), dict) else {}
    persona = p.get("persona") if isinstance(p.get("persona"), dict) else {}
    qual = p.get("qualification") if isinstance(p.get("qualification"), dict) else {}
    outc = p.get("outcomes") if isinstance(p.get("outcomes"), dict) else {}

    out = {
        "agent_name": forced_name or _s(p.get("agent_name"), "agent_name", 40),
        "title": _s(p.get("title"), "title", 60),
        "identity": {
            "role": _s(ident.get("role"), "identity.role", 600),
            "company_context": _s(ident.get("company_context"), "identity.company_context", 1200),
            "calling_context": _s(ident.get("calling_context"), "identity.calling_context", 800),
            "self_intro": _s(ident.get("self_intro"), "identity.self_intro", 300),
            "representation_rules": _strs(ident.get("representation_rules"), "identity.representation_rules", 8, 300, 1),
        },
        "audience": _s(p.get("audience"), "audience", 600),
        "objectives": {
            "primary": _s(obj.get("primary"), "objectives.primary", 400),
            "secondary": _strs(obj.get("secondary"), "objectives.secondary", 6, 300),
            "qualified_when": _s(obj.get("qualified_when"), "objectives.qualified_when", 600),
            "success_criteria": _strs(obj.get("success_criteria"), "objectives.success_criteria", 6, 300, 1),
            "move_to_close_when": _s(obj.get("move_to_close_when"), "objectives.move_to_close_when", 600),
        },
        "persona": {
            "summary": _s(persona.get("summary"), "persona.summary", 600),
            "traits": _strs(persona.get("traits"), "persona.traits", 10, 80, 2),
            "do": _strs(persona.get("do"), "persona.do", 12, 300, 2),
            "avoid": _strs(persona.get("avoid"), "persona.avoid", 12, 300, 2),
        },
    }

    variables, seen = [], set()
    for v in _objs(p.get("variables"), "variables", 20):
        name = _s(v.get("name"), "variables.name", 40).strip("{} ")
        if name not in allowed_vars:
            raise InvalidOutput(f"variables lists '{name}', which isn't available. Available: {', '.join(sorted(allowed_vars))}")
        if name in seen:
            continue
        seen.add(name)
        variables.append({"name": name, "how_to_use": _s(v.get("how_to_use"), "variables.how_to_use", 300),
                          "if_missing": _s(v.get("if_missing"), "variables.if_missing", 300)})
    out["variables"] = variables

    questions = []
    for q in _objs(qual.get("questions"), "qualification.questions", 10, 2):
        questions.append({"ask": _s(q.get("ask"), "qualification.questions.ask", 300),
                          "why": _s(q.get("why"), "qualification.questions.why", 300),
                          "skip_if": _s(q.get("skip_if"), "qualification.questions.skip_if", 300, required=False)})
    out["qualification"] = {
        "approach": _s(qual.get("approach"), "qualification.approach", 800),
        "questions": questions,
        "stop_rule": _s(qual.get("stop_rule"), "qualification.stop_rule", 600),
        "never_ask": _strs(qual.get("never_ask"), "qualification.never_ask", 10, 200),
    }

    stages = []
    for st in _objs(p.get("stages"), "stages", 10, 3):
        stages.append({"name": _s(st.get("name"), "stages.name", 60), "goal": _s(st.get("goal"), "stages.goal", 300),
                       "move_on_when": _s(st.get("move_on_when"), "stages.move_on_when", 300)})
    out["stages"] = stages

    tools = []
    for t in _objs(p.get("tools"), "tools", 6):
        name = _s(t.get("tool"), "tools.tool", 40)
        if name not in allowed_tools:
            raise InvalidOutput(f"tools lists '{name}', which this agent doesn't have. Available tools: {', '.join(sorted(allowed_tools))}")
        tools.append({"tool": name, "use_when": _s(t.get("use_when"), "tools.use_when", 400),
                      "before": _s(t.get("before"), "tools.before", 300, required=False),
                      "on_success": _s(t.get("on_success"), "tools.on_success", 300, required=False),
                      "on_failure": _s(t.get("on_failure"), "tools.on_failure", 300, required=False)})
    out["tools"] = tools

    dispositions, seen = [], set()
    for d in _objs(outc.get("dispositions"), "outcomes.dispositions", 13, 4):
        code = _s(d.get("outcome"), "outcomes.dispositions.outcome", 32)
        if code not in CALL_OUTCOMES:
            raise InvalidOutput(f"outcome '{code}' isn't valid. Use only: {', '.join(CALL_OUTCOMES)}")
        if code in seen:
            continue
        seen.add(code)
        dispositions.append({"outcome": code, "when": _s(d.get("when"), "outcomes.dispositions.when", 300)})
    if "do_not_call" not in seen:
        raise InvalidOutput("outcomes.dispositions must include do_not_call")
    fields, seen = [], set()
    for f in _objs(outc.get("extraction_fields"), "outcomes.extraction_fields", 10, 2):
        name = f.get("name")
        if not isinstance(name, str) or not _FIELD_NAME.match(name):
            raise InvalidOutput(f"extraction field name {name!r} must be snake_case")
        if name in seen:
            continue
        seen.add(name)
        fields.append({"name": name, "description": _s(f.get("description"), "extraction_fields.description", 200),
                       "values": _strs(f.get("values"), "extraction_fields.values", 12, 40)})
    out["outcomes"] = {
        "dispositions": dispositions,
        "extraction_fields": fields,
        "summary_format": _s(outc.get("summary_format"), "outcomes.summary_format", 400),
        "callback_rules": _s(outc.get("callback_rules"), "outcomes.callback_rules", 400, required=False),
    }
    out["compliance"] = _strs(p.get("compliance"), "compliance", 12, 300, 2)

    facts = []
    for f in _objs(p.get("facts"), "facts", 25):
        facts.append({"fact": _s(f.get("fact"), "facts.fact", 400), "source": _s(f.get("source"), "facts.source", 300)})
    out["facts"] = facts

    for text in _walk_strings(out):
        check_variables(text, allowed_vars, "The strategy")
    return out


def _steps(v, name: str) -> list[dict]:
    steps = []
    for st in _objs(v, name, 8, 1):
        say = _s(st.get("say"), f"{name}.say", 400, required=False)
        do = _s(st.get("do"), f"{name}.do", 400, required=False)
        if not (say or do):
            raise InvalidOutput(f"each step in {name} needs 'say' or 'do'")
        steps.append({"say": say, "do": do, "wait": st.get("wait") is True})
    return steps


_GREETING = re.compile(r"^(hi|hey|hello|hiya|good (?:morning|afternoon|evening))(\s+there)?\s*[,!.]\s*", re.I)


def question_last(text: str) -> str:
    """The first message is spoken in one go before the contact can reply, so a question must come last.
    "Hi, is this {{name}}? This is Ethan with Mirelo." -> "Hi, this is Ethan with Mirelo. Is this {{name}}?"
    """
    text = (text or "").strip()
    parts = [p.strip() for p in re.findall(r"[^.!?]+[.!?]+|[^.!?]+$", text) if p.strip()]
    if len(parts) < 2 or not any(p.endswith("?") for p in parts[:-1]):
        return text
    questions = [p for p in parts if p.endswith("?")]
    statements = [p for p in parts if not p.endswith("?")]
    greeting = ""
    m = _GREETING.match(questions[0])
    if m and statements:
        greeting = m.group(1)[0].upper() + m.group(1)[1:] + ", "
        rest = questions[0][m.end():]
        questions[0] = rest[:1].upper() + rest[1:]
        statements[0] = statements[0][:1].lower() + statements[0][1:]
    return (greeting + " ".join(statements + questions)).strip()


def validate_conversation(p: dict, *, allowed_vars: set[str], allowed_outcomes: set[str], direction: str,
                          flags: dict) -> dict:
    out = {"first_message": question_last(_s(p.get("first_message"), "first_message", 300))}
    out["opening"] = _steps(p.get("opening"), "opening")
    if not any(s["wait"] for s in out["opening"]):
        raise InvalidOutput("the opening needs at least one line that waits for the contact's reply (wait: true)")

    branches, seen = [], set()
    for b in _objs(p.get("branches"), "branches", 20, 4):
        key = _s(b.get("key"), "branches.key", 40)
        if key not in BRANCHES:
            raise InvalidOutput(f"branch key '{key}' isn't valid. Use: {', '.join(BRANCHES)}")
        if key in seen:
            continue
        seen.add(key)
        outcome = _s(b.get("outcome"), "branches.outcome", 32, required=False)
        if outcome and outcome not in allowed_outcomes:
            raise InvalidOutput(f"branch '{key}' ends with outcome '{outcome}', which isn't in this agent's dispositions")
        branches.append({"key": key, "when": _s(b.get("when"), "branches.when", 300),
                         "steps": _steps(b.get("steps"), f"branches.{key}"), "outcome": outcome})
    missing = [k for k in required_branches(direction, flags) if k not in seen]
    if missing:
        raise InvalidOutput(f"branches is missing required keys: {', '.join(missing)}")
    if not flags.get("booking") and "booking" in seen:
        raise InvalidOutput("booking is not available for this agent: remove the booking branch "
                            "and have a teammate follow up to schedule instead")
    if not flags.get("transfer") and "transfer" in seen:
        raise InvalidOutput("live transfer is not available for this agent: remove the transfer branch "
                            "and offer a callback from a teammate instead")
    out["branches"] = branches

    objections = []
    for o in _objs(p.get("objections"), "objections", 12, 3):
        objections.append({"objection": _s(o.get("objection"), "objections.objection", 200),
                           "response": _s(o.get("response"), "objections.response", 500),
                           "if_they_persist": _s(o.get("if_they_persist"), "objections.if_they_persist", 300, required=False)})
    out["objections"] = objections
    answers = []
    for a in _objs(p.get("direct_answers"), "direct_answers", 12):
        answers.append({"question": _s(a.get("question"), "direct_answers.question", 200),
                        "answer": _s(a.get("answer"), "direct_answers.answer", 500)})
    out["direct_answers"] = answers
    out["turn_taking"] = _strs(p.get("turn_taking"), "turn_taking", 10, 300)
    out["voicemail"] = _s(p.get("voicemail"), "voicemail", 600, required=direction != "inbound")
    close = p.get("closing") if isinstance(p.get("closing"), dict) else {}
    out["closing"] = {"close_line": _s(close.get("close_line"), "closing.close_line", 300),
                      "if_yes": _s(close.get("if_yes"), "closing.if_yes", 400),
                      "wrap_up": _s(close.get("wrap_up"), "closing.wrap_up", 300)}
    for text in _walk_strings(out):
        check_variables(text, allowed_vars, "The conversation")
    return out
