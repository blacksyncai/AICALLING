"""
Quality gate (stage D): checks a composed agent before it can be saved.

Each check returns {"key", "label", "status": "pass"|"warn"|"fail", "detail", "part"}.
"part" says which half of the spec a failure belongs to ("strategy" or
"conversation"), so the pipeline can ask the model to repair just that part.
"""

from __future__ import annotations

import re

from app.agent import spec as S
from app.agent.composer import SECTION_KEYS_V2, TITLES_V2

MIN_WORDS_FAIL = 450      # below this the prompt is a description, not operating instructions
MIN_WORDS_WARN = 900
MIN_SECTION_WORDS = 25

_URL = re.compile(r"\b(?:https?://|www\.)[^\s\"'<>)]+", re.I)
_DOMAIN = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|ai|co|cloud|app|dev|us|si)\b", re.I)
_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}|re_[A-Za-z0-9]{12,}|bsk_[A-Za-z0-9]{8,}|pk_(?:live|test)_[A-Za-z0-9]{8,}"
    r"|AKIA[0-9A-Z]{12,}|api[_-]?key\s*[=:]\s*\S+|Bearer\s+[A-Za-z0-9._-]{12,}|[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN)\b)")
_FUNC = re.compile(r"\b([a-z]+(?:_[a-z]+)+)\(")
_UNSUPPORTED = re.compile(
    r"\b(I'll|I will|I can|I'm going to|let me)\s+(?:just\s+)?(text|sms|send you (?:a|an) (?:text|email|link|sms)|email you|"
    r"update (?:your|the) (?:crm|record)|charge|process (?:a|the|your) payment)", re.I)


def _words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def _check(key, label, ok, detail_ok, detail_bad, part="strategy", warn=False):
    return {"key": key, "label": label, "status": "pass" if ok else ("warn" if warn else "fail"),
            "detail": detail_ok if ok else detail_bad, "part": part}


def term_leaks(text: str, terms: list[str], customer_text: str) -> list[str]:
    """Private playbook terms in `text` that the customer didn't supply themselves."""
    low_customer = customer_text.lower()
    found = []
    for t in terms:
        if t.lower() in low_customer:
            continue
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(t)}(?![A-Za-z0-9])", text, re.I):
            found.append(t)
    return found


_COMMON_EMAIL_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com", "aol.com"}


def foreign_urls(text: str, customer_text: str) -> list[str]:
    low = customer_text.lower()
    out = []
    for m in list(_URL.finditer(text)) + list(_DOMAIN.finditer(text)):
        u = m.group(0).rstrip(".,;:").lower()
        bare = re.sub(r"^https?://", "", u).removeprefix("www.").split("/")[0]
        if bare and bare not in low and bare not in _COMMON_EMAIL_DOMAINS and u not in out:
            out.append(u)
    return out


def _part_of(spec: dict, needles: list[str]) -> str:
    """Which half of the spec contains these strings (so the repair goes to the right model call)."""
    import json

    conv = json.dumps(spec["conversation"], ensure_ascii=False).lower()
    return "conversation" if any(n.lower() in conv for n in needles) else "strategy"


def run(spec: dict, composed: dict, ctx: dict) -> dict:
    st, cv = spec["strategy"], spec["conversation"]
    flags, sections = ctx["flags"], composed["sections"]
    prompt, first = composed["system_prompt"], composed["first_message"]
    everything = f"{prompt}\n{first}"
    checks: list[dict] = []

    # Completeness of every required section.
    thin = [TITLES_V2[k] for k in SECTION_KEYS_V2 if _words(sections.get(k, "")) < MIN_SECTION_WORDS]
    checks.append(_check("sections", "All 12 sections are complete", not thin, "Every section has real content.",
                         f"These sections are too thin: {', '.join(thin)}."))
    words = _words(prompt)
    checks.append({"key": "length", "label": "Detailed operating instructions",
                   "status": "fail" if words < MIN_WORDS_FAIL else ("warn" if words < MIN_WORDS_WARN else "pass"),
                   "detail": f"{words} words of instructions.", "part": "conversation"})

    # Identity and opening.
    name, company = st["agent_name"], ctx["business"]["name"]
    checks.append(_check("identity", "Identity names the agent and company",
                         name.lower() in sections["identity"].lower() and company.lower() in sections["identity"].lower(),
                         f"{name} represents {company}.", "The identity must name the agent and the company."))
    opening_text = " ".join([first] + [x["say"] for x in cv["opening"]]).lower()
    checks.append(_check("opening", "Opening has real lines and waits",
                         (name.lower() in opening_text or company.lower() in opening_text)
                         and any(x["wait"] for x in cv["opening"]) and len(cv["opening"]) >= 2,
                         "The opening introduces the agent and stops to listen.",
                         "The opening must use the agent's name or company, have at least two lines, and wait for replies.",
                         part="conversation"))
    if flags["ai_disclosure"]:
        checks.append(_check("disclosure", "AI disclosure", re.search(r"\bAI\b", sections["identity"]) is not None,
                             "The agent is honest that it's an AI.", "The identity must state the AI disclosure rule."))

    # Conversation branches.
    have = {b["key"] for b in cv["branches"]}
    missing = [S.BRANCHES[k] for k in S.required_branches(ctx["direction"], flags) if k not in have]
    checks.append(_check("branches", "Call flow covers real situations", not missing,
                         f"{len(have)} branches, including every required one.",
                         f"Missing branches: {', '.join(missing)}.", part="conversation"))
    checks.append(_check("turn_taking", "Turn-taking and stop points",
                         "stop and wait" in prompt.lower() and "turn boundary" in sections["turn_taking"].lower(),
                         "Questions are marked as stop points.", "Questions must be marked as stop points.",
                         part="conversation"))

    # Qualification, objections, outcomes.
    qs = st["qualification"]["questions"]
    need_q = 3 if flags.get("depth") == "thorough" else 2
    checks.append(_check("qualification", "Use-case-specific qualification with a stop rule",
                         len(qs) >= need_q and all(q["why"] for q in qs) and bool(st["qualification"]["stop_rule"]),
                         f"{len(qs)} questions, each with a reason, plus a stop rule.",
                         f"Need at least {need_q} questions with reasons and a stop rule."))
    checks.append(_check("objections", "Objection handling", len(cv["objections"]) >= 3,
                         f"{len(cv['objections'])} objections with responses.", "Need at least 3 realistic objections.",
                         part="conversation"))
    codes = {d["outcome"] for d in st["outcomes"]["dispositions"]}
    checks.append(_check("outcomes", "Post-call outcomes and extraction",
                         "do_not_call" in codes and len(codes) >= 4 and len(st["outcomes"]["extraction_fields"]) >= 2,
                         f"{len(codes)} outcomes and {len(st['outcomes']['extraction_fields'])} extracted fields.",
                         "Need at least 4 outcomes including do_not_call, and at least 2 extracted fields."))

    # Tools: only real ones, consistent with what's enabled.
    allowed = set(ctx["tools"])
    bad_funcs = sorted({m.group(1) for m in _FUNC.finditer(everything)} - allowed)
    promises = sorted({m.group(0) for m in _UNSUPPORTED.finditer(everything)})
    checks.append(_check("tools", "Only real tools and actions",
                         not bad_funcs and not promises,
                         f"Uses only: {', '.join(sorted(allowed))}.",
                         "Mentions actions the agent can't do: " + ", ".join(bad_funcs + promises) + ".",
                         part=_part_of(spec, bad_funcs + promises)))
    if not flags["booking"]:
        checks.append(_check("booking_off", "No booking without a calendar",
                             not re.search(r"\b(?:I've|I have|I'll|I will|let me)\s+(?:book|schedule)", everything, re.I),
                             "The agent never claims to book.", "The agent promises to book, but booking isn't available.",
                             part="conversation"))

    # Variables.
    unknown = sorted({m.group(1) for m in S._VAR.finditer(everything)} - set(ctx["variables"]))
    checks.append(_check("variables", "Only real contact fields", not unknown,
                         "Every placeholder maps to a real contact field.",
                         "Unknown placeholders: " + ", ".join(unknown) + ".", part="conversation"))

    # Isolation: nothing from internal playbooks or other customers, no secrets, no foreign URLs.
    leaks = term_leaks(everything, ctx["private_terms"], ctx["customer_text"])
    checks.append(_check("isolation", "No details copied from reference scripts", not leaks,
                         "No names, offers or identifiers from internal examples.",
                         "Contains reference-script details: " + ", ".join(leaks) + ".", part=_part_of(spec, leaks)))
    urls = foreign_urls(everything, ctx["customer_text"])
    checks.append(_check("urls", "No outside links or endpoints", not urls, "No links or endpoints the customer didn't provide.",
                         "Contains links the customer didn't provide: " + ", ".join(urls) + ".", part=_part_of(spec, urls)))
    secrets = sorted({m.group(0)[:24] for m in _SECRET.finditer(everything)})
    checks.append(_check("secrets", "No credentials", not secrets, "No keys, tokens or credentials.",
                         "Contains something that looks like a credential: " + ", ".join(secrets) + ".",
                         part=_part_of(spec, secrets)))

    failed = [c for c in checks if c["status"] == "fail"]
    return {"passed": not failed, "words": words, "checks": checks}
