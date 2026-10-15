"""
Prompt composer (stage C): turns a validated agent specification into the
editable voice-agent system prompt, one section per heading.

The model writes the agent-specific content inside the spec; this module decides
structure. Rules every call needs (turn-taking, not re-asking, honesty, do-not-call,
tool mechanics, AI disclosure) are added once at call time by
app/agent/runtime.build_instructions(), so they aren't repeated here.

Sections (v3), each only when it has content:
  1. Identity and objective     4. Conversation flow
  2. What you know              5. Questions and objections
  3. Opening                    6. Actions and boundaries
plus "Approved wording" when the user supplied lines that must be said exactly.
"""

from __future__ import annotations

from app.agent import spec as S

# Agents built by the production generator since v3.
SECTIONS_V3: list[tuple[str, str]] = [
    ("identity", "Identity and Objective"),
    ("context", "What You Know"),
    ("approved", "Approved Wording (say exactly)"),
    ("opening", "Opening"),
    ("flow", "Conversation Flow"),
    ("questions", "Questions and Objections"),
    ("actions", "Actions and Boundaries"),
]
SECTION_KEYS_V3 = tuple(k for k, _ in SECTIONS_V3)
TITLES_V3 = dict(SECTIONS_V3)

# Earlier generated agents ("v2", twelve sections) keep their sections; still editable section by section.
SECTIONS_V2: list[tuple[str, str]] = [
    ("identity", "Agent Identity & Role"),
    ("objectives", "Objectives and Success Criteria"),
    ("conduct", "Voice & Conversational Conduct"),
    ("variables", "Variables and Personalization"),
    ("opening", "Opening Script"),
    ("flow", "Dynamic Call Flow"),
    ("qualification", "Qualification Questions and Stop Rules"),
    ("objections", "Objection Handling & Direct Answers"),
    ("tools", "Tools, Transfers, and Calendar"),
    ("outcomes", "Post-Call Structured Output"),
    ("compliance", "Compliance, Privacy, and Security"),
    ("turn_taking", "Turn-Taking Edge Cases"),
]
SECTION_KEYS_V2 = tuple(k for k, _ in SECTIONS_V2)
TITLES_V2 = dict(SECTIONS_V2)

OUTCOME_LABELS = {
    "meeting_booked": "a meeting or appointment was booked",
    "qualified": "qualified and ready for the team",
    "not_qualified": "not a fit",
    "interested": "interested, next step agreed without a booking",
    "not_interested": "not interested",
    "callback": "asked to be called back",
    "transferred": "handed to a person",
    "voicemail": "reached voicemail",
    "no_answer": "no answer",
    "completed": "conversation finished with no clearer outcome",
    "failed": "technical problem",
    "wrong_number": "wrong person or number",
    "do_not_call": "asked not to be called again",
}


def assemble(sections: dict, order=SECTIONS_V3) -> str:
    return "\n\n".join(f"## {title}\n\n{(sections.get(k) or '').strip()}"
                       for k, title in order if (sections.get(k) or "").strip())


def _bullets(items) -> str:
    return "\n".join(f"- {x}" for x in items if x)


def _sentence(text: str) -> str:
    text = (text or "").strip()
    return text if not text or text[-1] in ".!?\"" else text + "."


def _questions_in(text: str) -> set[str]:
    import re

    return {S._norm(q) for q in re.findall(r"[^.!?]*\?", text or "") if len(S._norm(q).split()) >= 4}


def spoken_lines(cv: dict) -> list[str]:
    """Lines the conversation part already scripts (where a question would be asked)."""
    return [cv["first_message"], *cv["after_opening"], cv["next_step"]["ask"], *(b["say"] for b in cv["branches"])]


def open_questions(st: dict, cv: dict) -> list[dict]:
    """The planned questions minus any the conversation already asks — each question lives in one place."""
    asked = set().union(*(_questions_in(x) for x in spoken_lines(cv)))
    return [q for q in st["questions"] if not (_questions_in(q["ask"]) & asked)]


def compose(spec: dict, ctx: dict) -> dict:
    """spec = {"strategy": …, "conversation": …}; ctx = the context from pipeline.assemble_context()."""
    st, cv = spec["strategy"], spec["conversation"]
    flags, direction = ctx["flags"], ctx["direction"]
    name, company = st["agent_name"], ctx["business"]["name"]
    ident, obj = st["identity"], st["objective"]
    s: dict[str, str] = {k: "" for k in SECTION_KEYS_V3}

    # 1. Identity and objective
    style = _sentence(st["style"]["summary"])
    if st["style"]["habits"]:
        style += " " + " ".join(_sentence(h) for h in st["style"]["habits"])
    goal = [f"Goal: {_sentence(obj['primary'])}"]
    if obj["fallback"]:
        goal.append(f"If that isn't possible: {_sentence(obj['fallback'])}")
    s["identity"] = "\n\n".join(x for x in [
        f"You are {name}, {ident['role'].rstrip('.')}. You represent {company}.",
        f"Why this call happens: {_sentence(ident['calling_context'])}",
        " ".join(goal),
        f"Style: {style}",
        _bullets(ident["representation_rules"]),
    ] if x)

    # 2. What you know
    var_lines = [f"- {v['name']}: {_sentence(v['how_to_use'])}" for v in st["variables"]]
    s["context"] = "\n\n".join(x for x in [
        f"About {company}: {_sentence(ident['company_context'])}",
        "Details about this contact are listed under CONTACT DETAILS at the end. Use them naturally; if one is "
        "missing, say the sentence without it." + ("\n" + "\n".join(var_lines) if var_lines else ""),
    ] if x)

    # 3. Approved wording — exactly as the user wrote it.
    exact = [e for e in st["exact_wording"] if not e["is_opening"]]
    if exact:
        s["approved"] = "Say these exactly as written when they apply (don't paraphrase prices, offers or terms):\n" + \
            "\n".join(f'- {_sentence(e["use"])} "{e["text"]}"' for e in exact)

    # 4. Opening
    opening = ["Your first line is spoken for you when the call connects. Then stop and let them answer."]
    if direction == "both":
        opening.append("If they called you instead, greet them as " + company + " and ask how you can help.")
    opening.append("After they answer:\n" + _bullets(cv["after_opening"]))
    s["opening"] = "\n\n".join(opening)

    # 5. Flow
    stages = "\n".join(f"{i}. {x['name']}: {_sentence(x['goal'])}" for i, x in enumerate(cv["stages"], 1))
    by_key = {b["key"]: b for b in cv["branches"]}
    situations = []
    for key in S.BRANCHES:
        b = by_key.get(key)
        if not b:
            continue
        line = f"- {S.BRANCHES[key]}: {_sentence(b['guidance'])}"
        if b["say"]:
            line += f' For example: "{b["say"]}"'
        if b["outcome"]:
            line += f" (outcome: {b['outcome']})"
        situations.append(line)
    nxt = cv["next_step"]
    s["flow"] = "\n\n".join(x for x in [
        "A guide, not a script. Skip any step the conversation already covered.\n" + stages,
        f"Move to the next step as soon as {obj['ready_when'][:1].lower() + obj['ready_when'][1:].rstrip('.')}. "
        f'Offer it once, plainly: "{nxt["ask"]}" If yes: {_sentence(nxt["if_yes"])}',
        "Situations:\n" + "\n".join(situations),
    ] if x)

    # 6. Questions and objections
    q_lines = []
    for q in open_questions(st, cv):
        line = f'- "{q["ask"]}" ({q["why"].rstrip(".")}'
        line += f"; skip if {q['skip_if'][:1].lower() + q['skip_if'][1:].rstrip('.')})" if q["skip_if"] else ")"
        q_lines.append(line)
    parts = []
    if q_lines:
        parts.append("Only ask what you still need, one at a time, woven into the conversation. If they already "
                     "told you, use what they said instead of asking:\n" + "\n".join(q_lines))
    if cv["objections"]:
        parts.append("Objections (answer once, briefly, then move on or let them go):\n" + "\n".join(
            f'- "{o["objection"]}" → "{o["response"]}"' for o in cv["objections"]))
    if cv["direct_answers"]:
        parts.append("Common questions:\n" + "\n".join(
            f'- "{a["question"]}" → "{a["answer"]}"' for a in cv["direct_answers"]))
    s["questions"] = "\n\n".join(parts)

    # 7. Actions and boundaries
    plan = {t["tool"]: t for t in st["tools"]}
    acts = []
    if flags["transfer"]:
        p = plan.get(S.TOOL_TRANSFER)
        when = (p["use_when"] if p else "") or flags.get("transfer_when") or "they ask for a person"
        acts.append(f"Transfer to a person when {when[:1].lower() + when[1:].rstrip('.')}. Tell them you're "
                    "connecting them first. If it fails: " + (_sentence(p["on_failure"]) if p and p["on_failure"] else
                                                                "say so and offer a callback from the team."))
    else:
        acts.append("You can't transfer calls. If they want a person, say someone from the team will call them back"
                    + (" and ask when suits them." if flags["callback"] else "."))
    if flags["booking"]:
        p = plan.get(S.TOOL_BOOK) or plan.get(S.TOOL_CHECK)
        acts.append("Book with the calendar tools" + (f" when {p['use_when'][:1].lower() + p['use_when'][1:].rstrip('.')}"
                                                       if p else " once they want to meet") +
                    ". It's booked only when the booking tool confirms it.")
    else:
        acts.append("You can't book appointments on this call. If they want to meet, say the team will reach out "
                    "to set a time.")
    if flags["callback"] and st["outcomes"]["callback_rules"]:
        acts.append(f"Callbacks: {_sentence(st['outcomes']['callback_rules'])}")
    elif not flags["callback"]:
        acts.append("Don't arrange callbacks. If now is a bad time, thank them and end the call.")
    disp = list(st["outcomes"]["dispositions"])
    have = {d["outcome"] for d in disp}
    if direction != "inbound" and "wrong_number" not in have:
        disp.append({"outcome": "wrong_number", "when": "You reached the wrong person or number."})
    if "do_not_call" not in have:
        disp.append({"outcome": "do_not_call", "when": "They asked not to be contacted again."})
    outcomes = "\n".join(f"- {d['outcome']}: {_sentence(d['when'])}" for d in disp)
    s["actions"] = "\n\n".join(x for x in [
        _bullets(acts + st["compliance"]),
        "Outcome to pick when you end the call:\n" + outcomes,
    ] if x)

    return {"sections": s, "first_message": cv["first_message"], "system_prompt": assemble(s),
            "voicemail": cv["voicemail"]}
