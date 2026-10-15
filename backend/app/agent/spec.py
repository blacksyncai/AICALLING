"""
The agent specification — the typed, validated object the generator produces
before any prompt text exists (stage B of the pipeline, see app/agent/pipeline.py).

It is produced in two parts so neither model response gets too long:
- strategy:     purpose, identity, objective, style, approved wording, questions,
                tools plan, outcomes, compliance, fact provenance
- conversation: the script — first message, opening lines, stages with spoken lines and
                wait points, the close (ask, yes, no, goodbye), the situations this kind of
                call really meets with example replies, objections, direct answers, voicemail

Sizes scale with the purpose: a short client follow-up gets a short spec, not the
discovery process of a prospecting call. Rules every call needs (one question at a
time, don't re-ask, honesty, do-not-call …) are added by the runtime, not repeated here.

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

# What the call is for. Picks the flow, the situations to plan for and how much to ask.
PURPOSES = {
    "prospecting": "Outbound prospecting or new-lead follow-up: reach someone who showed interest or may need the "
                   "service, find out quickly whether there's a fit, and offer the next step.",
    "reactivation": "Database reactivation: reconnect with an older lead or past customer who went quiet, learn where "
                    "they stand now, and offer a next step only if the timing is right.",
    "client_follow_up": "Existing-client follow-up: a short call to someone who already works with the business "
                        "(reminder, confirmation, check-in, renewal). Little or no qualification.",
    "inbound": "Inbound: answer people who call the business, find out what they need, answer from known facts, and "
               "route them to the right next step.",
}
# How many questions each purpose may plan (min, max). Inbound asks for what it needs to help.
QUESTION_RANGE = {"prospecting": (1, 4), "reactivation": (1, 3), "client_follow_up": (0, 2), "inbound": (1, 4)}

_REACTIVATION = re.compile(r"reactivation|recall|past_|old_estimate|unsold|incomplete_application")
_CLIENT = re.compile(r"check_in|confirmation|reminder|aftercare|seasonal|client_review|renewal")


def purpose_for(key: str, direction: str) -> str:
    """The purpose a preset use case implies ('' for a custom goal: the model chooses)."""
    if direction == "inbound":
        return "inbound"
    if not key or key == "custom":
        return ""
    if _CLIENT.search(key):
        return "client_follow_up"
    if _REACTIVATION.search(key):
        return "reactivation"
    return "prospecting"


# Situations a call can meet. Only the ones that fit the purpose are planned (required_branches()).
BRANCHES = {
    "ready": "They're ready for the next step",
    "unsure": "They're unsure, or the timing isn't right yet",
    "busy": "It's a bad time to talk",
    "not_interested": "They're not interested",
    "not_a_fit": "They're not a fit",
    "wrong_person": "Wrong person or wrong number",
    "price": "They ask about price or cost",
    "question": "They ask something you don't have the answer to",
    "wants_person": "They want to talk to a person",
    "send_info": "They ask you to send information",
    "issue": "They have a problem or complaint",
    "urgent": "It's urgent",
}


def required_branches(purpose: str, direction: str = "outbound") -> list[str]:
    keys = {
        "prospecting": ["ready", "unsure", "busy", "not_interested", "wrong_person", "price", "wants_person"],
        "reactivation": ["ready", "unsure", "busy", "not_interested", "wrong_person", "wants_person"],
        "client_follow_up": ["ready", "busy", "wrong_person", "issue", "wants_person"],
        "inbound": ["ready", "price", "question", "wants_person"],
    }.get(purpose, ["ready", "unsure", "not_interested", "wants_person"])
    if direction == "both" and purpose != "inbound":
        keys = keys + ["question"]
    return list(dict.fromkeys(keys))


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


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s{}]", " ", (text or "").lower())).strip()


def is_verbatim(text: str, source: str) -> bool:
    """True when `text` appears word for word in `source` (ignoring case, punctuation and spacing)."""
    t = _norm(text)
    return bool(t) and t in _norm(source)


# Rules the runtime adds to every call (app/agent/runtime.conversation_rules). The model sometimes restates them
# as "compliance" or "habits"; dropping those keeps each rule in one place.
_UNIVERSAL = re.compile(
    r"\b(?:disclos\w*|(?:an?|the) AI\b|do[- ]?not[- ]?call|one question|pauses? (?:after|to let)|stack\w* questions"
    r"|match(?:es|ing)? (?:their|the \w+'s) (?:pace|tone|energy)|never (?:invent|make up)|uses? (?:their|the \w+'s) first name)",
    re.I)
# Outcomes the platform detects itself; the agent never needs to pick them.
_PLATFORM_OUTCOMES = {"voicemail", "no_answer", "failed"}


def _specific(items: list[str]) -> list[str]:
    return [x for x in items if not _UNIVERSAL.search(x)]


def validate_strategy(p: dict, *, allowed_vars: set[str], allowed_tools: set[str], flags: dict,
                      forced_name: str = "", purpose: str = "", customer_text: str = "") -> dict:
    ident = p.get("identity") if isinstance(p.get("identity"), dict) else {}
    obj = p.get("objective") if isinstance(p.get("objective"), dict) else {}
    style = p.get("style") if isinstance(p.get("style"), dict) else {}
    outc = p.get("outcomes") if isinstance(p.get("outcomes"), dict) else {}

    chosen = purpose or _s(p.get("purpose"), "purpose", 30)
    if chosen not in PURPOSES:
        raise InvalidOutput(f"purpose must be one of: {', '.join(PURPOSES)}")

    out = {
        "purpose": chosen,
        "agent_name": forced_name or _s(p.get("agent_name"), "agent_name", 40),
        "title": _s(p.get("title"), "title", 60),
        "identity": {
            "role": _s(ident.get("role"), "identity.role", 300),
            "company_context": _s(ident.get("company_context"), "identity.company_context", 500),
            "calling_context": _s(ident.get("calling_context"), "identity.calling_context", 400),
            "representation_rules": _specific(_strs(ident.get("representation_rules"), "identity.representation_rules", 4, 250)),
        },
        "objective": {
            "primary": _s(obj.get("primary"), "objective.primary", 300),
            "fallback": _s(obj.get("fallback"), "objective.fallback", 300, required=False),
            "ready_when": _s(obj.get("ready_when"), "objective.ready_when", 300),
        },
        "style": {
            "summary": _s(style.get("summary"), "style.summary", 300),
            "habits": _specific(_strs(style.get("habits"), "style.habits", 8, 200))[:6],
        },
    }

    exact = []
    for e in _objs(p.get("exact_wording"), "exact_wording", 6):
        text = _s(e.get("text"), "exact_wording.text", 600)
        if customer_text and not is_verbatim(text, customer_text):
            continue  # not the user's own words (a paraphrase or the mission) — never presented as approved wording
        exact.append({"use": _s(e.get("use"), "exact_wording.use", 200), "text": text,
                      "is_opening": e.get("is_opening") is True})
    out["exact_wording"] = exact

    variables, seen = [], set()
    for v in _objs(p.get("variables"), "variables", 6):
        name = _s(v.get("name"), "variables.name", 40).strip("{} ")
        if name not in allowed_vars:
            raise InvalidOutput(f"variables lists '{name}', which isn't available. Available: {', '.join(sorted(allowed_vars))}")
        if name in seen:
            continue
        seen.add(name)
        variables.append({"name": name, "how_to_use": _s(v.get("how_to_use"), "variables.how_to_use", 200)})
    out["variables"] = variables

    lo, hi = QUESTION_RANGE[chosen]
    if flags.get("intake"):
        hi += 4  # an intake call (a death call) takes several details, one at a time
    if flags.get("depth") == "light":
        hi = min(hi, 2)
    questions = []
    for q in _objs(p.get("questions"), "questions", 8):
        questions.append({"ask": _s(q.get("ask"), "questions.ask", 200),
                          "why": _s(q.get("why"), "questions.why", 200),
                          "skip_if": _s(q.get("skip_if"), "questions.skip_if", 200, required=False)})
    if len(questions) < lo:
        raise InvalidOutput(f"questions needs at least {lo} item(s) for a {chosen} call")
    if len(questions) > hi:
        raise InvalidOutput(f"questions has {len(questions)} items; a {chosen} call should ask at most {hi}. "
                            "Keep only the ones that decide the next step.")
    out["questions"] = questions

    tools = []
    for t in _objs(p.get("tools"), "tools", 4):
        name = re.sub(r"\(.*\)$", "", _s(t.get("tool"), "tools.tool", 40))
        if name not in ALL_TOOLS:
            continue  # not a tool at all ("callback") — the plan for it lives elsewhere
        if name not in allowed_tools:
            raise InvalidOutput(f"tools lists '{name}', which this agent doesn't have. Available tools: {', '.join(sorted(allowed_tools))}")
        if name == TOOL_END_CALL:
            continue  # the runtime describes hanging up
        tools.append({"tool": name, "use_when": _s(t.get("use_when"), "tools.use_when", 300),
                      "on_failure": _s(t.get("on_failure"), "tools.on_failure", 250, required=False)})
    out["tools"] = tools

    dispositions, seen = [], set()
    for d in _objs(outc.get("dispositions"), "outcomes.dispositions", 10, 3):
        code = _s(d.get("outcome"), "outcomes.dispositions.outcome", 32)
        if code not in CALL_OUTCOMES:
            raise InvalidOutput(f"outcome '{code}' isn't valid. Use only: {', '.join(CALL_OUTCOMES)}")
        if code == "meeting_booked" and not flags.get("booking"):
            raise InvalidOutput("meeting_booked means a confirmed calendar booking, which this agent can't make. "
                                "Use interested, qualified or callback for a teammate to schedule instead.")
        if code in seen or code in _PLATFORM_OUTCOMES:
            continue
        seen.add(code)
        dispositions.append({"outcome": code, "when": _s(d.get("when"), "outcomes.dispositions.when", 200)})
    fields, seen = [], set()
    for f in _objs(outc.get("extraction_fields"), "outcomes.extraction_fields", 8, 1):
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
        "callback_rules": _s(outc.get("callback_rules"), "outcomes.callback_rules", 300, required=False),
    }
    out["compliance"] = _specific(_strs(p.get("compliance"), "compliance", 6, 250))[:4]

    facts = []
    for f in _objs(p.get("facts"), "facts", 25):
        facts.append({"fact": _s(f.get("fact"), "facts.fact", 400), "source": _s(f.get("source"), "facts.source", 300)})
    out["facts"] = facts

    for text in _walk_strings(out):
        check_variables(text, allowed_vars, "The strategy")
    return out


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


def _line(v, name: str, need_say: bool = True) -> dict:
    """One scripted line: words to say (an example unless it's approved wording), whether to wait for the answer,
    and optionally when it applies / when to skip it."""
    if not isinstance(v, dict):
        raise InvalidOutput(f"each item in {name} must be an object with \"say\"")
    say = _s(v.get("say"), f"{name}.say", 400, required=need_say)
    cond = {k: _s(v.get(k), f"{name}.{k}", 200, required=False) for k in ("if", "skip_if")}
    for k, c in cond.items():
        if _CODE_COND.search(c):
            raise InvalidOutput(f"{name}.{k} \"{c[:80]}\" reads like code; write the condition in plain words "
                                "(e.g. \"If they're the decision maker\")")
    return {"say": say, "wait": v.get("wait") is True or say.rstrip().endswith("?"), **cond}


# Conditions are read by the agent as instructions: "decision_maker == 'yes' && fit" reads as code, not a person.
_CODE_COND = re.compile(r"==|!=|&&|\|\||\b[a-z]+_[a-z_]+\s*(?:=|is (?:true|false|unknown))|\bnull\b|\bNone\b")


# A scripted "Thanks for sharing that." makes every turn sound the same; the runtime rules cover acknowledging.
_GENERIC_ACK = re.compile(r"^(?:ok(?:ay)?|great|perfect|got it|understood|sure|thanks?|thank you)?[ ,!.-]*"
                          r"(?:(?:thanks?|thank you)(?: so much)? for (?:letting me know|sharing(?: that)?|that|telling me)"
                          r"(?: with me)?"
                          r"|that(?:'s| is)? (?:helps?|helpful(?: to know)?|makes sense|good to know|great to hear)"
                          r"|that gives me a (?:good|clear|better) (?:sense|idea|picture)(?: of [\w' ]+)?"
                          r"|got it|understood|i (?:understand|see)|good to know|appreciate (?:that|you sharing))"
                          r"(?:[ ,]*(?:thank you|thanks)(?: (?:so much )?for (?:sharing(?: that)?|letting me know|telling me))?)?"
                          r"[ .!]*$", re.I)


def _lines(v, name: str, max_items: int, min_items: int = 1) -> list[dict]:
    if v is None:
        v = []
    if not isinstance(v, list):
        raise InvalidOutput(f"{name} must be a list of lines")
    out = [ln for ln in (_line(x, name) for x in v) if not _GENERIC_ACK.match(ln["say"].strip())]
    if len(out) < min_items:
        raise InvalidOutput(f"{name} needs at least {min_items} spoken line(s)")
    return out[:max_items]


# How many stages each purpose gets: a short follow-up isn't a discovery call.
STAGE_RANGE = {"prospecting": (2, 5), "reactivation": (2, 4), "client_follow_up": (1, 3), "inbound": (2, 4)}


def usable_outcomes(flags: dict) -> set[str]:
    """Outcomes a script may end on: everything but what the platform detects itself, and meeting_booked only
    when the agent can really book."""
    return set(CALL_OUTCOMES) - _PLATFORM_OUTCOMES - (set() if flags.get("booking") else {"meeting_booked"})


def validate_conversation(p: dict, *, allowed_vars: set[str], allowed_outcomes: set[str], direction: str,
                          flags: dict, purpose: str, exact_opening: str = "") -> dict:
    first = _s(p.get("first_message"), "first_message", 300)
    used = [m.group(1) for m in _VAR.finditer(first)]
    if not exact_opening and len(used) != len(set(used)):
        raise InvalidOutput("first_message uses the same {{field}} twice; use each detail at most once")
    # Approved wording is kept exactly as the user wrote it; generated openers get the question moved last.
    out = {"first_message": exact_opening or question_last(first)}
    out["opening"] = _lines(p.get("opening"), "opening", 4, 1 if direction != "inbound" else 0)

    lo, hi = STAGE_RANGE.get(purpose, (2, 4))
    hi += 2 if flags.get("intake") else 0  # an intake branches by the reason for the call
    stages = []
    for st in _objs(p.get("stages"), "stages", hi + 1):
        stages.append({"name": _s(st.get("name"), "stages.name", 60).replace("_", " ").strip().capitalize(),
                       "goal": _s(st.get("goal"), "stages.goal", 200),
                       "lines": _lines(st.get("lines"), f"stages.{st.get('name') or '?'}.lines",
                                       10 if flags.get("intake") else 6),
                       "move_on": _s(st.get("move_on"), "stages.move_on", 200, required=False)})
    if len(stages) < lo:
        raise InvalidOutput(f"stages needs at least {lo} stage(s) with spoken lines for a {purpose} call")
    if len(stages) > hi:
        raise InvalidOutput(f"stages has {len(stages)} stages; a {purpose} call should have at most {hi}")
    asked = sum(1 for st in stages for ln in st["lines"] if ln["say"].rstrip().endswith("?"))
    cap = QUESTION_RANGE.get(purpose, (1, 4))[1] + 3 + (6 if flags.get("intake") else 0)
    if asked > cap:
        raise InvalidOutput(f"the stages script {asked} questions; a {purpose} call should script at most {cap}. "
                            "Keep only the questions that decide the next step and mark the rest skip_if known.")
    out["stages"] = stages

    branches, seen = [], set()
    for b in _objs(p.get("branches"), "branches", 12, 2):
        key = _s(b.get("key"), "branches.key", 40)
        if key not in BRANCHES:
            raise InvalidOutput(f"branch key '{key}' isn't valid. Use: {', '.join(BRANCHES)}")
        if key in seen:
            continue
        seen.add(key)
        outcome = _s(b.get("outcome"), "branches.outcome", 32, required=False)
        if key == "wrong_person":
            outcome = "wrong_number"  # always this code; the runtime's rule says so too
        elif outcome and outcome not in allowed_outcomes:
            raise InvalidOutput(f"branch '{key}' ends with outcome '{outcome}', which isn't in this agent's dispositions")
        branches.append({"key": key, "say": _s(b.get("reply") or b.get("say"), f"branches.{key}.reply", 300),
                         "then": _s(b.get("then"), f"branches.{key}.then", 300, required=False), "outcome": outcome})
    missing = [k for k in required_branches(purpose, direction) if k not in seen]
    if missing:
        raise InvalidOutput(f"branches is missing required keys: {', '.join(missing)}")
    out["branches"] = branches

    objections = []
    for o in _objs(p.get("objections"), "objections", 8):
        objections.append({"objection": _s(o.get("objection"), "objections.objection", 150),
                           "say": _s(o.get("say") or o.get("response"), "objections.say", 300),
                           # Follow-up turns for the likely answers ("If they agree: … → wait").
                           "steps": _lines(o.get("steps"), "objections.steps", 4, min_items=0),
                           "if_again": _s(o.get("if_again"), "objections.if_again", 250, required=False)})
    out["objections"] = objections
    answers = []
    for a in _objs(p.get("direct_answers"), "direct_answers", 8):
        answers.append({"question": _s(a.get("question"), "direct_answers.question", 150),
                        "answer": _s(a.get("answer"), "direct_answers.answer", 300)})
    out["direct_answers"] = answers

    c = p.get("close") if isinstance(p.get("close"), dict) else {}
    out["close"] = {
        "when": _s(c.get("when"), "close.when", 250),
        "ask": _s(c.get("ask"), "close.ask", 250),
        "if_yes": _s(c.get("if_yes"), "close.if_yes", 300),
        "if_yes_say": _s(c.get("if_yes_say"), "close.if_yes_say", 250, required=False),
        "if_no": _s(c.get("if_no"), "close.if_no", 300),
        "if_no_say": _s(c.get("if_no_say"), "close.if_no_say", 250, required=False),
        "goodbye": _s(c.get("goodbye"), "close.goodbye", 200),
    }
    out["voicemail"] = _s(p.get("voicemail"), "voicemail", 400, required=False) if direction != "inbound" else ""
    if direction == "inbound":
        # The caller isn't a contact on file: their name comes from the conversation, not a placeholder.
        for text in _walk_strings({k: v for k, v in out.items() if k != "first_message"}):
            if _VAR.search(text):
                raise InvalidOutput(f"\"{text[:80]}\" uses a {{{{field}}}}, but inbound callers aren't on file. Write the "
                                    "line without it (\"Thanks for that. What's the reason for your call today?\") and "
                                    "set \"if\" to \"they gave their name — use it\".")
    allowed_codes = set(allowed_outcomes) | {"wrong_number", "do_not_call"}
    for text in _walk_strings(out):
        check_variables(text, allowed_vars, "The conversation")
        if _TOOL_SYNTAX.search(text):
            raise InvalidOutput(f"\"{text[:80]}\" uses tool syntax. Describe actions in plain words (\"transfer the "
                                "call\", \"end the call\"); the agent's tools are described separately.")
        bad = [c for c in _CODE.findall(text) if c in CALL_OUTCOMES and c not in allowed_codes]
        if bad:
            raise InvalidOutput(f"\"{text[:80]}\" uses outcome {bad[0]}, which isn't in this agent's dispositions")
    return out


_TOOL_SYNTAX = re.compile(r"\b(?:end_call|transfer_call|check_availability|book_appointment)\s*\(", re.I)
_CODE = re.compile(r"\b[a-z]+(?:_[a-z]+)+\b")
