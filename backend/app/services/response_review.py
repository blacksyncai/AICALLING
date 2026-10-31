"""Evidence-bound post-call decisions; never schedules or sends a follow-up."""

import re

from app.agent.runtime import _live_contact_turns, reconcile_outcome

RESPONSE_OUTCOMES = (
    "no_decision",
    "insufficient_conversation",
    "busy",
    "information_requested",
    "declined_conversation",
)
NEXT_ACTIONS = (
    "none_agreed",
    "callback_requested",
    "send_information",
    "meeting_booked",
    "human_review",
)
SCOPES = ("offer", "permission_to_speak", "meeting", "timing", "unknown")


def _normalized(text):
    return " ".join(str(text or "").casefold().replace("’", "'").split()).strip(" .!?")


def quote_from_contact(quote, transcript):
    if not isinstance(quote, str) or not quote.strip():
        return None
    needle = _normalized(quote)
    return (
        quote.strip()[:1200]
        if needle
        and any(needle in _normalized(t) for t in _live_contact_turns(transcript))
        else None
    )


def unresolved(transcript):
    turns = _live_contact_turns(transcript)
    words = re.findall(r"\w+", " ".join(turns))
    return "insufficient_conversation" if len(words) <= 3 else "no_decision"


def action_quote_from_contact(quote, action, transcript):
    grounded = quote_from_contact(quote, transcript)
    if not grounded:
        return None
    words = re.findall(r"\w+", _normalized(grounded))
    if set(words) <= {"thanks", "thank", "you"}:
        return None
    affirmations = {
        "yes",
        "yeah",
        "yep",
        "sure",
        "okay",
        "ok",
        "that",
        "works",
        "sounds",
        "good",
        "please",
        "do",
        "fine",
        "perfect",
    }
    if not set(words) <= affirmations:
        return grounded
    proposal = ""
    pattern = (
        r"\b(?:(?:call|catch|reach|phone) you|call (?:back|again)|another (?:time|day)|talk (?:later|tomorrow)|can we (?:speak|talk))\b"
        if action == "callback_requested"
        else r"\b(?:send|shoot|email|text)\b.{0,80}\b(?:you|email|text|information|details|link|valuation)\b"
    )
    for turn in transcript or []:
        if turn.get("role") in ("assistant", "agent"):
            proposal = _normalized(turn.get("text"))
        elif (
            turn.get("role") in ("user", "caller")
            and _normalized(grounded) in _normalized(turn.get("text"))
            and re.search(pattern, proposal)
        ):
            return grounded
    return None


def review_response(result, transcript):
    raw = result.get("response_analysis")
    if not isinstance(raw, dict):
        return result  # compatibility with older analyzers and stored reports
    out = dict(result)
    quote = quote_from_contact(raw.get("evidence_quote"), transcript)
    action_quote = quote_from_contact(raw.get("next_action_quote"), transcript)
    scope = (
        raw.get("response_scope") if raw.get("response_scope") in SCOPES else "unknown"
    )
    certainty = (
        raw.get("certainty")
        if raw.get("certainty") in ("clear", "ambiguous", "insufficient")
        else "ambiguous"
    )
    action = (
        raw.get("next_action")
        if raw.get("next_action") in NEXT_ACTIONS
        else "none_agreed"
    )
    if action in ("callback_requested", "send_information"):
        action_quote = action_quote_from_contact(
            raw.get("next_action_quote"), action, transcript
        )
    if action == "callback_requested" and action_quote:
        # Availability alone is not consent to another conversation. Other
        # languages retain the model's interpretation of a grounded quotation.
        timing_only = re.search(
            r"\b(busy|driving|no time|don't have time|can't talk|cannot talk)\b",
            _normalized(action_quote),
        )
        explicit = re.search(
            r"\b(?:(?:call|ring|phone|catch|reach|try) (?:me|us)|call (?:back|again|tomorrow|later)|another time|can we (?:talk|speak)|can you .{0,30}call)\b",
            _normalized(action_quote),
        )
        agreed = False
        proposal = ""
        for turn in transcript or []:
            if turn.get("role") in ("assistant", "agent"):
                proposal = _normalized(turn.get("text"))
            elif turn.get("role") in ("user", "caller") and _normalized(
                action_quote
            ) in _normalized(turn.get("text")):
                agreed = bool(
                    re.search(
                        r"\b(yes|yeah|sure|okay|ok|please do|that works)\b",
                        _normalized(action_quote),
                    )
                    and re.search(
                        r"\b(call you|call back|another time|talk tomorrow|can we talk)\b",
                        proposal,
                    )
                )
                if agreed:
                    break
        negated = re.search(
            r"\b(don't call|do not call|stop calling)\b", _normalized(action_quote)
        )
        if negated or (timing_only and not explicit and not agreed):
            action, action_quote = "none_agreed", None
    outcome = out.get("outcome")
    technical = (
        "no_answer",
        "voicemail",
        "screened",
        "failed",
        "wrong_number",
        "language_barrier",
    )
    protected = ("meeting_booked", "transferred", "do_not_call")
    if outcome not in (*technical, *protected):
        invalid_refusal = outcome == "not_interested" and (
            scope != "offer"
            or _normalized(quote)
            in ("thank you", "thanks", "hello", "hi", "sure", "okay")
        )
        invalid_interest = outcome in ("interested", "qualified") and scope != "offer"
        if invalid_refusal and quote and certainty == "clear" and scope == "timing":
            outcome = "busy"
        elif (
            invalid_refusal
            and quote
            and certainty == "clear"
            and scope == "permission_to_speak"
            and re.search(r"\b(no|decline|not interested)\b", _normalized(quote))
        ):
            outcome = "declined_conversation"
        elif (
            not quote
            or certainty != "clear"
            or invalid_refusal
            or invalid_interest
            or outcome == "declined_conversation"
            and scope != "permission_to_speak"
            or outcome == "completed"
        ):
            outcome = unresolved(transcript)
        if outcome == "callback" and (
            action != "callback_requested" or not action_quote
        ):
            outcome = "busy" if scope == "timing" and quote else unresolved(transcript)
    outcome = reconcile_outcome(
        outcome,
        transcript,
        callback_request=action_quote if action == "callback_requested" else None,
    )
    if action in ("callback_requested", "send_information") and not action_quote:
        action = "none_agreed"
    if (
        action == "send_information"
        and action_quote
        and outcome
        not in (*technical, *protected, "not_interested", "declined_conversation")
    ):
        outcome, quote, scope = "information_requested", action_quote, "offer"
    if outcome in technical or outcome in (
        "not_interested",
        "declined_conversation",
        "do_not_call",
    ):
        action, action_quote = "none_agreed", None
    if outcome == "meeting_booked":
        action = "meeting_booked"
    elif action == "meeting_booked":
        action, action_quote = "human_review", None
    if outcome == "callback" and action != "callback_requested":
        outcome = unresolved(transcript)
    out["outcome"] = outcome
    out["response_analysis"] = {
        "version": 1,
        "response": outcome,
        "evidence_quote": quote,
        "response_scope": scope,
        "certainty": certainty,
        "next_action": action,
        "next_action_quote": action_quote,
        "channel": raw.get("channel")
        if action in ("callback_requested", "send_information")
        and raw.get("channel") in ("phone", "email", "text")
        else None,
        "timeline": quote_from_contact(raw.get("timeline"), transcript)
        if action_quote and raw.get("timeline")
        else None,
        "meeting_response": raw.get("meeting_response")
        if raw.get("meeting_response")
        in ("accepted", "declined", "not_discussed", "unclear")
        else "not_discussed",
    }
    return out


def routing_outcome(call):
    outcome = getattr(call, "outcome", "")
    review = getattr(call, "response_analysis", None) or {}
    if outcome not in (
        "do_not_call",
        "not_interested",
        "declined_conversation",
        "voicemail",
        "screened",
        "no_answer",
        "failed",
        "meeting_booked",
        "transferred",
    ) and (
        review.get("version") == 1
        and review.get("next_action") == "callback_requested"
        and review.get("next_action_quote")
    ):
        return "callback"
    return outcome
