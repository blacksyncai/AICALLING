"""Warm transfer: what the agent says to the teammate before putting the caller through, and what it tells
the caller when nobody takes the call."""
from app.agent.runtime import render_vars

DEFAULT_RING_SECONDS = 20
# After the teammate answers: time to hear the handoff and say "put them through" before we give up.
BRIEFING_SECONDS = 75

DEFAULT_HANDOFF = ("Hey, it's {{agent_name}} from {{business_name}}. I've got {{full_name}} on the line. "
                   "[One sentence on what they want and anything important they told you.] "
                   "Want me to put them through?")


def handoff_line(cfg: dict, variables: dict | None) -> str:
    """The handoff the agent opens with, {{variables}} filled. [Brackets] are left for the agent to fill in."""
    template = (cfg.get("transfer_handoff") or "").strip() or DEFAULT_HANDOFF
    persona = (cfg.get("persona_name") or "").strip() or "the assistant"
    company = (cfg.get("business_name") or "").strip() or "the team"
    values = {**(variables or {}), "agent_name": persona, "business_name": company}
    if not (values.get("full_name") or values.get("name") or values.get("first_name")):
        values["full_name"] = "a caller"
    return render_vars(template, values).strip()


def briefing_instructions(cfg: dict, variables: dict | None, history: str) -> str:
    """Instructions for the call to the teammate. The caller is on hold and can't hear any of it."""
    return f"""You are calling a teammate at {(cfg.get("business_name") or "").strip() or "the business"} to hand off a live call.
The caller is on hold listening to music and can't hear you. You are speaking to the teammate now, not the caller.

Open with this handoff, said naturally. Where it has [brackets], replace them with what they describe:
"{handoff_line(cfg, variables)}"

Then answer any quick question the teammate has, using only the conversation below. Keep every reply to one or two
short spoken sentences.
- When the teammate is ready to take the call ("yes", "sure", "put them through"), call connect_to_caller.
- If they can't take it right now, call decline_transfer with the reason.
- If you hear a voicemail greeting, an automated message, or a request to leave a message, call voicemail_detected
  right away. Don't leave a message.

## Conversation with the caller so far
{history.strip() or "(nothing yet)"}
"""


def history_text(chat_ctx) -> str:
    lines = []
    for msg in chat_ctx.messages() if chat_ctx is not None else []:
        if msg.role not in ("user", "assistant") or not msg.text_content:
            continue
        lines.append(f"{'Caller' if msg.role == 'user' else 'You'}: {msg.text_content}")
    return "\n".join(lines[-30:])


def not_connected(reason: str, booking: bool) -> str:
    """Tool result for the caller's conversation when the teammate didn't take the call."""
    why = {"no_answer": "Nobody picked up.", "voicemail": "It went to voicemail.",
           "declined": "The teammate can't take the call right now.",
           }.get(reason, "The transfer didn't connect.")
    offer = ("Offer to book a time with the team instead (check_availability, then book_appointment), or a callback "
             "if they'd rather." if booking else "Offer a callback from the team and confirm the best time and number.")
    return (f"Transfer not connected: {why} The caller is back on the line with you now. Tell them in one short, "
            f"friendly line that the team just stepped away (don't mention voicemail or the teammate's reason), "
            f"then {offer[0].lower()}{offer[1:]} Don't end the call or try the transfer again unless they ask.")
