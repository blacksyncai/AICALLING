"""
Some models (Mistral) refuse a request whose last message is the assistant's own ("Expected last role User or
Tool"). That happens when the contact talks over the agent: their words are stored before the agent's cut-off
line. Put the interrupted line back before what the contact said, so the contact has the last word.
"""

from __future__ import annotations


def _is_msg(item, role: str) -> bool:
    return getattr(item, "type", None) == "message" and getattr(item, "role", None) == role


def contact_last(chat_ctx):
    """chat_ctx, or a fixed copy when it ends on an interrupted assistant line after the contact's turn."""
    items = chat_ctx.items
    if not items or not _is_msg(items[-1], "assistant") or not getattr(items[-1], "interrupted", False):
        return chat_ctx
    tail = len(items)
    while tail > 0 and _is_msg(items[tail - 1], "assistant") and getattr(items[tail - 1], "interrupted", False):
        tail -= 1
    user_at = next((i for i in range(tail - 1, -1, -1) if _is_msg(items[i], "user")), None)
    if user_at is None:
        return chat_ctx
    fixed = chat_ctx.copy()
    moved = fixed.items[tail:]
    del fixed.items[tail:]
    fixed.items[user_at:user_at] = moved
    return fixed
