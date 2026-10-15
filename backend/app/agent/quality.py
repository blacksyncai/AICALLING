"""
Quality gate (stage D): checks a composed agent before it can be saved.

Each check returns {"key", "label", "status": "pass"|"warn"|"fail", "detail", "part"}.
"part" says which half of the spec a failure belongs to ("strategy" or
"conversation"), so the pipeline can ask the model to repair just that part.
"""

from __future__ import annotations

import re

from app.agent import spec as S

# Length is a warning only: a full script needs room, but a prompt past this is usually repeating itself.
MAX_WORDS_WARN = 3400

_URL = re.compile(r"\b(?:https?://|www\.)[^\s\"'<>)]+", re.I)
_DOMAIN = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|ai|co|cloud|app|dev|us|si)\b", re.I)
_SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}|re_[A-Za-z0-9]{12,}|bsk_[A-Za-z0-9]{8,}|pk_(?:live|test)_[A-Za-z0-9]{8,}"
    r"|AKIA[0-9A-Z]{12,}|api[_-]?key\s*[=:]\s*\S+|Bearer\s+[A-Za-z0-9._-]{12,}|[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN)\b)")
_FUNC = re.compile(r"\b([a-z]+(?:_[a-z]+)+)\(")
_UNSUPPORTED = re.compile(
    r"\b(I'll|I will|I can|I'm going to|let me)\s+(?:just\s+)?(text|sms|send you (?:a|an) (?:text|email|link|sms)|email you|"
    r"update (?:your|the) (?:crm|record)|charge|process (?:a|the|your) payment)"
    r"|\b(?:I can|I'll|I will|let me|we can)\s+(?:also\s+)?(?:send|email|text)\b|\bsend (?:it |that |some )?(?:your way|over to you)\b"
    r"|\binformation I can send\b", re.I)
_BOOK_CLAIM = re.compile(r"\b(?:I've|I have|I'll|I will|let me|I can)\s+(?:go ahead and\s+)?(?:book|schedule|get you (?:booked|scheduled))"
                         r"|\byou're (?:all )?(?:booked|scheduled)\b", re.I)
_TRANSFER_CLAIM = re.compile(r"\b(?:I'll|I will|let me|I can|I'm going to)\s+(?:go ahead and\s+)?(?:transfer|connect|patch|put) you"
                             r"(?: through| over| to| with)?|\b(?:connecting|transferring|patching) you\b"
                             r"|\bput(?:ting)? you through\b", re.I)


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


def repeated_questions(lines: list[str]) -> list[str]:
    """Questions scripted in more than one place — the agent would end up asking them twice."""
    seen, dupes = set(), []
    for line in lines:
        for q in re.findall(r"[^.!?]*\?", line or ""):
            key = S._norm(q)
            if len(key.split()) < 4:
                continue  # "Sound good?" can fairly come up twice
            if key in seen and q.strip() not in dupes:
                dupes.append(q.strip())
            seen.add(key)
    return dupes


def run(spec: dict, composed: dict, ctx: dict) -> dict:
    st, cv = spec["strategy"], spec["conversation"]
    flags, sections = ctx["flags"], composed["sections"]
    prompt, first = composed["system_prompt"], composed["first_message"]
    everything = f"{prompt}\n{first}\n{composed.get('voicemail') or ''}"
    checks: list[dict] = []

    words = _words(prompt)
    checks.append({"key": "length", "label": "Concise instructions",
                   "status": "warn" if words > MAX_WORDS_WARN else "pass",
                   "detail": f"{words} words of agent-specific script and instructions.", "part": "conversation"})

    # Identity and opening.
    name, company = st["agent_name"], ctx["business"]["name"]
    checks.append(_check("identity", "Identity names the agent and company",
                         name.lower() in sections["identity"].lower() and company.lower() in sections["identity"].lower(),
                         f"{name} represents {company}.", "The identity must name the agent and the company."))
    exact_opening = any(e["is_opening"] for e in st["exact_wording"])
    said = " ".join([first] + [x["say"] for x in cv["opening"]]).lower()
    opening_ok = exact_opening or ctx["direction"] == "inbound" or name.lower() in said or company.lower() in said
    checks.append(_check("opening", "Opening says who's calling", opening_ok,
                         "The opening introduces the agent or the business.",
                         "The first message or the opening lines must say who's calling (agent or company name).",
                         part="conversation"))
    told = [x for x in [first] + [ln["say"] for ln in cv["opening"]] if re.search(r"\bAI\b|virtual assistant", x)]
    checks.append(_check("opening_once", "Opening says each thing once", len(told) <= 1,
                         "The AI disclosure is said once.",
                         "The opening says it's an AI more than once — keep it in one line: " + " | ".join(told) + ".",
                         part="conversation"))
    thin = [x["name"] for x in cv["stages"] if not any(ln["say"] for ln in x["lines"])]
    checks.append(_check("script", "Every stage has words to say", not thin and bool(cv["close"]["ask"]),
                         f"{len(cv['stages'])} stages with spoken lines, plus a close.",
                         "These stages have no spoken lines: " + ", ".join(thin) + ".", part="conversation"))

    # Purpose-specific situations.
    have = {b["key"] for b in cv["branches"]}
    missing = [S.BRANCHES[k] for k in S.required_branches(st["purpose"], ctx["direction"]) if k not in have]
    checks.append(_check("branches", "Covers the situations this call meets", not missing,
                         f"{len(have)} situations for a {st['purpose'].replace('_', ' ')} call.",
                         f"Missing situations: {', '.join(missing)}.", part="conversation"))

    # The same scripted question twice makes the agent re-ask.
    from app.agent.composer import spoken_lines

    dupes = repeated_questions(spoken_lines({**cv, "first_message": first}))
    checks.append(_check("repeats", "No question scripted twice", not dupes, "Each question is planned once.",
                         "These questions are scripted more than once — keep each in one place: " + " | ".join(dupes) + ".",
                         part="conversation"))

    # Approved wording is kept exactly.
    lost = [e["text"] for e in st["exact_wording"] if not S.is_verbatim(e["text"], everything)]
    checks.append(_check("approved", "Approved wording kept exactly", not lost, "User-approved lines are verbatim.",
                         "These approved lines were changed or dropped: " + " | ".join(x[:60] for x in lost) + "."))

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
        claims = sorted({m.group(0) for m in _BOOK_CLAIM.finditer(everything)})
        checks.append(_check("booking_off", "No booking without a calendar", not claims,
                             "The agent never claims to book.",
                             "Booking isn't available, but the agent says: " + ", ".join(claims) + ".",
                             part=_part_of(spec, claims)))
    if not flags["transfer"]:
        claims = sorted({m.group(0) for m in _TRANSFER_CLAIM.finditer(everything)})
        checks.append(_check("transfer_off", "No transfer without a transfer number", not claims,
                             "The agent never offers a live transfer.",
                             "Live transfer isn't available, but the agent says: " + ", ".join(claims) + ".",
                             part=_part_of(spec, claims)))

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
