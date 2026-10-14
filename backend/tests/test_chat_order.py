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


def test_models_that_need_the_contact_last_get_a_cue_after_a_finished_agent_line():
    c = llm.ChatContext()
    c.add_message(role="user", content="hi")
    c.add_message(role="assistant", content="Hello!")
    fixed = contact_last(c, needs_user_last=True)
    assert [m.role for m in fixed.items] == ["user", "assistant", "user"] and len(c.items) == 2
