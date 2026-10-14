from livekit.agents import llm

from app.agent.chat_order import contact_last


def test_interrupted_agent_line_moves_before_the_contact():
    c = llm.ChatContext()
    c.add_message(role="system", content="sys")
    c.add_message(role="user", content="Who is this?")
    c.add_message(role="assistant", content="Hey, this is Hooman,", interrupted=True)
    fixed = contact_last(c)
    assert [m.role for m in fixed.items] == ["system", "assistant", "user"]
    assert [m.role for m in c.items] == ["system", "user", "assistant"]  # original untouched


def test_normal_context_is_unchanged():
    c = llm.ChatContext()
    c.add_message(role="user", content="hi")
    c.add_message(role="assistant", content="Hello!")
    assert contact_last(c) is c
