from app.agent.turn_latency import TurnLatency

def test_no_greeting_or_overlap_is_counted_as_a_response():
    t=TurnLatency()
    assert t.agent_state('listening','speaking',1) is None
    t.agent_state('speaking','listening',2)
    t.user_state('listening','speaking',3)
    assert t.agent_state('thinking','speaking',4) is None
    assert t.summary()['response_gap_samples']==0

def test_user_continuations_reset_gap_and_distinguish_interruptions():
    t=TurnLatency()
    t.user_state('listening','speaking',1);t.user_state('speaking','listening',2)
    t.user_state('listening','speaking',2.1);t.user_state('speaking','listening',3)
    assert t.agent_state('thinking','speaking',3.6)=={'seconds':.6,'kind':'response'}
    assert t.agent_state('speaking','speaking',3.7) is None
    t.user_state('listening','speaking',4);t.agent_state('speaking','listening',4.1)
    t.user_state('speaking','listening',5)
    assert t.agent_state('thinking','speaking',6)=={'seconds':1.,'kind':'interruption_recovery'}
    s=t.summary();assert s['avg_turn_gap']==.6 and s['interruptions']==1 and s['avg_interruption_recovery']==1.

def test_slow_tail_is_visible_instead_of_just_an_average():
    t=TurnLatency()
    for i,gap in enumerate([.4,.5,.6,4.]):
        t.agent_state('speaking','listening',i*10)
        t.user_state('listening','speaking',i*10+1);t.user_state('speaking','listening',i*10+2)
        t.agent_state('thinking','speaking',i*10+2+gap)
    s=t.summary();assert s['response_gap_samples']==4 and s['p95_turn_gap']==4. and s['p50_turn_gap']==.5
