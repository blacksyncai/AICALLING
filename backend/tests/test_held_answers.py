"""A short answer said over the end of the agent's line used to get no reply (Compass, Nov 18)."""
from app.agent.runtime import held_short_answer


def test_a_one_word_answer_at_the_end_of_the_agents_line_is_answered():
    assert held_short_answer("Yes.", heard_at=10.0, agent_stopped=10.4, min_words=2)
    assert held_short_answer("No.", heard_at=10.0, agent_stopped=11.9, min_words=2)
    assert held_short_answer("Go ahead.", heard_at=10.0, agent_stopped=10.2, min_words=2)


def test_a_backchannel_from_the_middle_of_the_line_is_left_alone():
    assert not held_short_answer("Yeah.", heard_at=10.0, agent_stopped=16.0, min_words=2)


def test_nothing_or_a_real_interruption_is_not_forced():
    assert not held_short_answer("", heard_at=10.0, agent_stopped=10.2, min_words=2)
    assert not held_short_answer("No I'm not interested at all thanks", heard_at=10.0, agent_stopped=10.2, min_words=2)
