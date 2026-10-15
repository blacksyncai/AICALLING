"""
Prompt composer (stage C): turns a validated agent specification into the
editable voice-agent system prompt, one section per heading.

The model writes the agent-specific script inside the spec; this module decides
structure, so every agent has the same complete shape:

  Identity and Objective · What You Know · Approved Wording (when supplied) ·
  Opening · Conversation Flow · Next Step and Close · Situations and Objections ·
  Rules and Boundaries

Quoted lines are examples the agent adapts; "Say exactly" lines are the user's
approved wording. "→ wait" marks where the agent stops and listens. Rules every
call needs (turn-taking, not re-asking, honesty, do-not-call, tool mechanics) are
added once at call time by app/agent/runtime.build_instructions().
"""

from __future__ import annotations

from app.agent import spec as S

# Agents built by the production generator since v4: a complete script in eight sections.
SECTIONS_V4: list[tuple[str, str]] = [
    ("identity", "Identity and Objective"),
    ("context", "What You Know"),
    ("approved", "Approved Wording"),
    ("opening", "Opening"),
    ("flow", "Conversation Flow"),
    ("close", "Next Step and Close"),
    ("situations", "Situations and Objections"),
    ("rules", "Rules and Boundaries"),
]
SECTION_KEYS_V4 = tuple(k for k, _ in SECTIONS_V4)
TITLES_V4 = dict(SECTIONS_V4)

# v3 agents (compact, briefly generated before v4) keep their own layout.
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


def assemble(sections: dict, order=SECTIONS_V4) -> str:
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


def _lower_first(text: str) -> str:
    text = (text or "").strip().rstrip(".")
    return text[:1].lower() + text[1:]


def _similar(a: str, b: str) -> bool:
    """Two rules that say mostly the same thing (word overlap)."""
    wa, wb = set(a.split()), set(b.split())
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.6


def _clause(text: str) -> str:
    """A condition to follow "when": drops a leading "when", "once" or "after" the model already wrote."""
    import re

    text = re.sub(r"^(?:(?:skip[_ ]if|only if|if|when|once|after|as soon as)\s+)+", "", (text or "").strip(), flags=re.I)
    # "deceased_name is already provided" → "deceased name is already provided"
    return _lower_first(re.sub(r"\b([a-z]+)_([a-z_]+)\b", lambda m: m.group(0).replace("_", " "), text))


def _say(line: dict, exact: set[str]) -> str:
    """One scripted line: '- Say: "…" → wait.' with its condition; approved wording is marked exact."""
    verb = "Say exactly" if S._norm(line["say"]) in exact else ("Ask" if line["say"].rstrip().endswith("?") else "Say")
    out = f'{verb}: "{line["say"]}"'
    if line.get("wait"):
        out += " → wait"
    # The condition comes first, so the agent checks it before speaking.
    if line.get("skip_if"):
        out = f"Only if you don't know yet (skip if {_clause(line['skip_if'])}): {out}"
    elif line.get("if"):
        out = f"If {_clause(line['if'])}: {out}"
    return "- " + out


def spoken_lines(cv: dict) -> list[str]:
    """Every line the script has the agent say (used to find questions scripted twice)."""
    out = [cv["first_message"], *(x["say"] for x in cv["opening"])]
    for st in cv["stages"]:
        out += [x["say"] for x in st["lines"]]
    c = cv["close"]
    return out + [c["ask"], c["if_yes_say"], c["if_no_say"], *(b["say"] for b in cv["branches"])]


def compose(spec: dict, ctx: dict) -> dict:
    """spec = {"strategy": …, "conversation": …}; ctx = the context from pipeline.assemble_context()."""
    st, cv = spec["strategy"], spec["conversation"]
    flags, direction = ctx["flags"], ctx["direction"]
    name, company = st["agent_name"], ctx["business"]["name"]
    ident, obj = st["identity"], st["objective"]
    exact = {S._norm(e["text"]) for e in st["exact_wording"]}
    s: dict[str, str] = {k: "" for k in SECTION_KEYS_V4}

    # 1. Identity and objective
    style = _sentence(st["style"]["summary"])
    if st["style"]["habits"]:
        style += " " + " ".join(_sentence(h) for h in st["style"]["habits"])
    goal = [f"Goal: {_sentence(obj['primary'])}"]
    if obj["fallback"]:
        goal.append(f"If that isn't possible: {_sentence(obj['fallback'])}")
    s["identity"] = "\n\n".join(x for x in [
        f"You are {name}, {ident['role'].rstrip('.')}. You represent {company}.",
        f"Who you're talking to and why: {_sentence(ident['calling_context'])}",
        " ".join(goal),
        f"How you sound: {style}",
    ] if x)

    # 2. What you know
    var_lines = [f"- {v['name']}: {_sentence(v['how_to_use'])}" for v in st["variables"]]
    s["context"] = "\n\n".join(x for x in [
        f"About {company}: {_sentence(ident['company_context'])} For anything else, use the business reference "
        "below; if it isn't there, don't guess.",
        "This contact's details are under CONTACT DETAILS at the end. If one is missing, say the line without it."
        + ("\n" + "\n".join(var_lines) if var_lines else ""),
    ] if x)

    # 3. Approved wording — exactly as the user wrote it.
    approved = [e for e in st["exact_wording"] if not e["is_opening"]]
    if approved:
        s["approved"] = "Say these word for word when they apply. Don't paraphrase prices, offers or terms:\n" + \
            "\n".join(f'- {_sentence(e["use"])} "{e["text"]}"' for e in approved)

    # 4. Opening
    opening_first = ("Your first line is spoken for you when the call connects"
                     + (" (approved wording, word for word)" if any(e["is_opening"] for e in st["exact_wording"]) else "")
                     + f': "{cv["first_message"]}" → wait.')
    opening = [opening_first]
    if direction == "both":
        opening.append(f"If they called you instead, greet them as {company} and ask how you can help.")
    if cv["opening"]:
        opening.append("Then (say everything up to a → wait in the same turn):\n"
                       + "\n".join(_say(x, exact) for x in cv["opening"]))
    opening.append("Quoted lines are examples: keep the meaning, fit the words to what they just said. "
                   "\"Say exactly\" lines are approved wording. \"→ wait\" means stop and let them answer. "
                   "If they interrupt with a question, answer it, then continue from where it fits — never restart.")
    s["opening"] = "\n\n".join(opening)

    # 5. Flow — stage by stage, with the words to use.
    blocks = []
    for i, x in enumerate(cv["stages"], 1):
        block = f"### {i}. {x['name']}\n{_sentence(x['goal'])}\n" + "\n".join(_say(ln, exact) for ln in x["lines"])
        if x["move_on"]:
            block += f"\nMove on when {_clause(x['move_on'])}."
        blocks.append(block)
    s["flow"] = ("Use the stages in order, but skip anything they've already answered or that no longer applies. "
                 "Each stage's lines are options, not a list to recite: say the one that fits what they just said.\n\n") \
        + "\n\n".join(blocks)

    # 6. Close
    c = cv["close"]
    yes = _sentence(c["if_yes"]) + (f' Say: "{c["if_yes_say"]}"' if c["if_yes_say"] else "")
    no = _sentence(c["if_no"]) + (f' Say: "{c["if_no_say"]}"' if c["if_no_say"] else "")
    ask_verb = "Say exactly" if S._norm(c["ask"]) in exact else "Ask"
    s["close"] = "\n".join([
        f"When {_clause(c['when'])}, offer the next step once. If they already asked for it, skip the question and "
        "go straight to \"If yes\".",
        f'- {ask_verb}: "{c["ask"]}" → wait',
        f"- If yes: {yes}",
        f"- If no or not now: {no}",
        f'- Goodbye: "{c["goodbye"]}" Then end the call.',
    ])
    if flags["callback"] and not flags["booking"] and direction != "inbound":
        # Without a calendar, the next step is a callback the team confirms: same steps every time.
        s["close"] += "\n\n" + "\n".join([
            "Callback flow (when they agree to talk with the team, or ask to be called back):",
            '- Ask: "What day would work best for you?" → wait',
            '- Ask: "And what time is usually easiest?" → wait',
            "- Confirm their time zone if it isn't clear from what they said or their details.",
            '- Repeat it once naturally, e.g. "Okay, so Thursday afternoon around two?" → wait',
            f'- Then: "Got it. I\'ll pass that along to the team at {company} so they can confirm with you." '
            "Never say it's booked or confirmed.",
        ])

    # 7. Situations and objections
    by_key = {b["key"]: b for b in cv["branches"]}
    sit = []
    for key in S.BRANCHES:
        b = by_key.get(key)
        if not b:
            continue
        line = f'- {S.BRANCHES[key]}: "{b["say"]}"'
        if b["then"]:
            line += f" Then {_lower_first(b['then'])}."
        if b["outcome"]:
            line += f" (outcome: {b['outcome']})"
        sit.append(line)
    parts = ["\n".join(sit)]
    if cv["objections"]:
        blocks = []
        for o in cv["objections"]:
            block = [f'### "{o["objection"]}"', _say({"say": o["say"], "wait": True, "if": "", "skip_if": ""}, exact)]
            block += [_say(ln, exact) for ln in o.get("steps") or []]
            if o["if_again"]:
                block.append(f"- If they push back again: {_lower_first(o['if_again'])}.")
            blocks.append("\n".join(block))
        parts.append("Objections — one thoughtful answer each; respond to what they actually say, then move on or "
                     "let them go politely:\n\n" + "\n\n".join(blocks))
    if cv["direct_answers"]:
        parts.append("Common questions:\n" + "\n".join(
            f'- "{a["question"]}" → "{a["answer"]}"' for a in cv["direct_answers"]))
    s["situations"] = "\n\n".join(parts)

    # 8. Rules and boundaries
    plan = {t["tool"]: t for t in st["tools"]}
    acts = []
    if flags["transfer"]:
        p = plan.get(S.TOOL_TRANSFER)
        when = (p["use_when"] if p else "") or flags.get("transfer_when") or "they ask for a person"
        acts.append(f"Transfer to a person when {_clause(when)}. Say you're connecting them first. If it fails: "
                    + (_sentence(p["on_failure"]) if p and p["on_failure"] else "say so and offer a callback from the team."))
    else:
        acts.append("You can't transfer calls. If they want a person, say someone from the team will call them back"
                    + (" and ask when suits them." if flags["callback"] else "."))
    if flags["booking"]:
        p = plan.get(S.TOOL_BOOK) or plan.get(S.TOOL_CHECK)
        acts.append("Book with the calendar tools" + (f" when {_clause(p['use_when'])}" if p else " once they want to meet")
                    + ". Offer only times the calendar returns. It's booked only when the booking tool confirms it.")
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
    for b in cv["branches"]:
        if b["outcome"] and b["outcome"] not in {d["outcome"] for d in disp}:
            disp.append({"outcome": b["outcome"], "when": OUTCOME_LABELS.get(b["outcome"], b["outcome"]).capitalize()})
    rules: list[str] = []
    for r in acts + st["identity"]["representation_rules"] + st["compliance"]:
        n = S._norm(r)
        if any(n in S._norm(x) or S._norm(x) in n or _similar(n, S._norm(x)) for x in rules):
            # Same rule twice: keep the fuller wording.
            rules = [r if (S._norm(x) in n and len(r) > len(x)) else x for x in rules]
            continue
        rules.append(r)
    fields = st["outcomes"].get("extraction_fields") or []
    summary = ("Call summary — record only what they actually said; mark anything not discussed as unknown:\n"
               + "\n".join(f"- {f['name'].replace('_', ' ').capitalize()}: {_sentence(f['description'])}" for f in fields)) \
        if fields else ""
    s["rules"] = "\n\n".join(x for x in [
        "\n".join(f"- {r}" for r in rules),
        "Outcome to pick when you end the call:\n" + "\n".join(f"- {d['outcome']}: {_sentence(d['when'])}" for d in disp),
        summary,
    ] if x)

    return {"sections": s, "first_message": cv["first_message"], "system_prompt": assemble(s),
            "voicemail": cv["voicemail"]}
