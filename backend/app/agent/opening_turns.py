"""Complete short answers should not hit semantic max-delay.

This participates in the existing turn detector, not a second commit controller.
VAD, minimum endpoint delay, transcript updates and interruption handling remain
owned by the SDK. Early identity answers, unambiguous closed-question replies
and greeting acknowledgments are eligible; other answers keep semantic inference.
"""
import re


def _words(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?", text.lower().replace("’", "'"))


def complete_identity_answer(chat_ctx, expected_name):
    messages = [m for m in chat_ctx.items if getattr(m, "role", None) in ("user", "assistant")
                and getattr(m, "text_content", "")]
    if not messages or messages[-1].role != "user":
        return False
    # The first greeting and identity exchange only, never later qualification.
    if sum(m.role == "assistant" for m in messages) > 2 or sum(m.role == "user" for m in messages) > 3:
        return False
    question = next((m.text_content for m in reversed(messages[:-1]) if m.role == "assistant"), "")
    if '?' not in question:
        return False
    name = _words(str(expected_name or ""))
    placeholders = {"there", "unknown", "contact", "firstname", "first", "name"}
    if not name or name[0] in placeholders:
        # Manual “Call me” has no lead variables. Use only a capitalized proper
        # name in the spoken identity question, never generic “is this a good
        # time / your address / the right number” or an unresolved placeholder.
        match = re.search(r"\b(?i:is this|am i (?:speaking|talking) (?:to|with))\s+"
                          r"([A-Z][a-z]+(?:['-][A-Z]?[a-z]+)?(?:\s+[A-Z][a-z]+){0,2})\s*\?\s*$", question)
        if not match:
            return False
        name = _words(match.group(1))
        if name[0] in placeholders | {"a", "an", "the", "your", "our", "my", "this", "that", "good", "right", "correct"}:
            return False
    variants = {name[0], ' '.join(name)}
    normalized_question = ' '.join(_words(question))
    if not any(re.search(r"\b(?:is this|am i (?:speaking|talking) (?:to|with)) " + re.escape(n) + r"$",
                         normalized_question) for n in variants):
        return False
    answer = messages[-1].text_content.strip()
    # An ellipsis, comma, dash or question mark signals a potentially unfinished
    # or questioning answer. Never strip such a signal and call it complete.
    if re.search(r"(?:\.\.|…|[,?;:\-–—])\s*$", answer) or any(c.isdigit() for c in answer):
        return False
    response = ' '.join(_words(answer))
    complete = {'yes', 'yeah', 'yep', 'yup', 'no', 'nope', 'speaking', "that's me", 'that is me',
                'yes speaking', 'wrong number'}
    for prefix in ('this is ', "it's ", 'it is ', 'yes this is ', 'yeah this is ', "yes it's "):
        complete.update(prefix + n for n in variants)
    complete.update(n + ' speaking' for n in variants)
    return response in complete


def complete_short_answer(chat_ctx):
    """Conservative English closed answers; never commit open or dictated text."""
    messages = [m for m in chat_ctx.items if getattr(m, "role", None) in ("user", "assistant")
                and getattr(m, "text_content", "")]
    if len(messages) < 2 or messages[-1].role != "user" or messages[-2].role != "assistant":
        return False
    answer = messages[-1].text_content.strip()
    if re.search(r"(?:\.\.|…|[,?;:\-–—])\s*$", answer) or any(c.isdigit() for c in answer):
        return False
    response = ' '.join(_words(answer))
    question = messages[-2].text_content.strip()
    # Greeting acknowledgments only answer a greeting, not an open question.
    if response in {'hi', 'hello', 'hey'}:
        return ' '.join(_words(question)) in {'hi', 'hello', 'hey', 'hello there', 'hi there'}
    if response not in {'yes', 'yeah', 'yep', 'yup', 'no', 'nope'} or not question.endswith('?'):
        return False
    # Last sentence must itself be a closed question. Open questions and offers
    # listing alternatives keep the semantic model, including dictated details.
    clause = re.split(r'[.!?]', question[:-1])[-1].strip().lower()
    if re.search(r"\b(?:or|address|number|phone|email|spell|digit|code)\b", clause):
        return False
    return bool(re.match(r"^(?:do you|did you|does (?:it|that)|are you|is (?:it|that|this)|"
                         r"have you|has (?:it|that)|can (?:i|you|we)|could (?:i|you|we)|"
                         r"would you|will you|should (?:i|we))\b", clause))


class OpeningTurnDetector:
    """Installed LiveKit 1.6.4 _TurnDetector protocol, delegating every other case."""
    def __init__(self, delegate, expected_name, on_fast=None):
        self.delegate = delegate
        self.expected_name = expected_name
        self.on_fast = on_fast

    @property
    def model(self): return self.delegate.model

    @property
    def provider(self): return self.delegate.provider

    async def supports_language(self, language):
        return await self.delegate.supports_language(language)

    async def unlikely_threshold(self, language):
        return await self.delegate.unlikely_threshold(language)

    async def predict_end_of_turn(self, chat_ctx, *, timeout=3):
        if complete_identity_answer(chat_ctx, self.expected_name) or complete_short_answer(chat_ctx):
            if self.on_fast:
                self.on_fast()
            return 1.0
        return await self.delegate.predict_end_of_turn(chat_ctx, timeout=timeout)
