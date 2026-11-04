"""
Why a contact said no (or not now): "already sold", "working with an agent", "not the owner"...

Saved on each analyzed call as response_analysis["reason"] (+ "reason_quote", the contact's own words), shown in
place of a generic "Not interested", counted per campaign, and written to CRM notes. Clear phrases are matched by
rules below; the post-call model fills in the rest, and its pick is kept only when its quote is the contact's.
"""

from __future__ import annotations

import re

REASONS: dict[str, str] = {
    "already_sold": "Already sold",
    "already_bought": "Already bought",
    "working_with_agent": "Working with an agent",
    "not_owner": "Not the owner",
    "renting_out": "Renting it out",
    "not_selling": "Not selling anymore",
    "not_looking": "Not looking anymore",
    "has_provider": "Already has a provider",
    "cost": "Cost / commission",
    "price_value": "Price or value",
    "timing": "Bad timing",
    "no_need": "No need",
    "privacy": "Asked how we got their number",
    "other": "Other",
}

_RULES: list[tuple[str, re.Pattern]] = [(k, re.compile(p)) for k, p in (
    ("already_sold", r"\b(?:(?:house|home|property|place|it|condo|unit|land|lot)(?: has| was| is|'s)? (?:already )?(?:been )?sold"
                     r"|already sold|(?:we|i|they) (?:already )?sold|sold it|it sold|under contract|in escrow|pending sale"
                     r"|closed (?:on the sale|already)|(?:we|i) closed last)\b"),
    ("already_bought", r"\b(?:(?:already |just )?(?:bought|purchased|closed on) (?:a |another |the |our |my )?"
                       r"(?:house|home|place|property|condo)|found (?:a |our |my )(?:house|home|place)|(?:we|i) bought already)\b"),
    ("working_with_agent", r"\b(?:(?:have|got|working with|using|signed with|listed (?:it )?with|going with|already have|hired)"
                           r" (?:a |an |my |our )?(?:own )?(?:realtor|agent|broker|real estate agent|listing agent)"
                           r"|my (?:realtor|agent|broker)|our (?:realtor|agent|broker)|(?:realtor|agent) already)\b"),
    ("not_owner", r"\b(?:not the (?:owner|homeowner)|(?:i|we) don't own|i'm (?:just )?(?:the |a )?(?:tenant|renter)"
                  r"|i rent here|(?:it's|it is|that's) not my (?:house|home|property)|(?:the )?owner (?:passed|died|moved))\b"),
    ("renting_out", r"\b(?:rent(?:ing)? it(?: out)?|renting (?:the (?:house|place|home)|out)|leased it|(?:have|got) tenants"
                    r"|turn(?:ed)? it into a rental|keeping it as a rental)\b"),
    ("not_selling", r"\b(?:not selling|no longer selling|decided (?:not to sell|to stay|to keep)|keeping (?:it|the (?:house|home))"
                    r"|staying put|took it off the market|(?:we're|i'm) staying|don't want to sell|not going to sell)\b"),
    ("not_looking", r"\b(?:not looking(?: anymore| any more)?|stopped looking|done looking|no longer looking)\b"),
    ("privacy", r"\b(?:how did you get (?:my|this) number|where did you get (?:my|this) (?:number|info))\b"),
    ("cost", r"\b(?:too expensive|can't afford|commission(?:s)? (?:is|are) too|fees? (?:is|are) too)\b"),
)]
_NEGATED = re.compile(r"\b(?:didn't|did not|never|hasn't|has not|not|wasn't|won't) (?:get )?sold|didn't sell|never sold|couldn't sell\b")


def label(reason: str | None) -> str | None:
    return REASONS.get(reason or "")


def from_rules(turns: list[str]) -> tuple[str, str] | None:
    """(reason, the contact's words) for the first clear reason the contact gave, or None."""
    for text in turns:
        t = " ".join((text or "").lower().replace("’", "'").split())
        for key, pattern in _RULES:
            if pattern.search(t) and not (key == "already_sold" and _NEGATED.search(t)):
                return key, text.strip()[:600]
    return None


def decide(raw_reason, raw_quote, turns: list[str]) -> tuple[str | None, str | None]:
    """The call's reason: a rule match first, else the model's pick when its quote is the contact's own words."""
    hit = from_rules(turns)
    if hit:
        return hit
    if raw_reason in REASONS and isinstance(raw_quote, str) and raw_quote.strip():
        needle = " ".join(raw_quote.casefold().split()).strip(" .!?")
        if needle and any(needle in " ".join(t.casefold().split()) for t in turns):
            return raw_reason, raw_quote.strip()[:600]
    return None, None
