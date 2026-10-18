from types import SimpleNamespace as NS
import pytest
from livekit.agents.llm import ChatContext
from app.agent.opening_turns import complete_identity_answer, OpeningTurnDetector


def chat(answer,question='Hey, is this Matt?',previous=()):
    ctx=ChatContext()
    for role,text in previous:ctx.add_message(role=role,content=text)
    ctx.add_message(role='assistant',content=question)
    ctx.add_message(role='user',content=answer)
    return ctx


@pytest.mark.parametrize('answer',['Yes.','Yeah','Yep!','No.','Nope','This is Matt.',"It's Matt.",
                                  'Matt speaking.',"Yes, it's Matt.","That's me.",'Speaking.','Wrong number.'])
def test_complete_identity_answers_use_normal_min_delay(answer):
    assert complete_identity_answer(chat(answer),'Matt Jones')


@pytest.mark.parametrize('answer',['Yes, but','Yes...','Yes,','Yes?','I think','This is','My address is 14 Main Street',
                                  'four one five ...','Yes, after ...','No, wait','Yes and I was wondering',
                                  'This is Matthew','Someone else speaking','No; actually,','Yes—'])
def test_unfinished_corrected_or_dictated_answers_keep_semantic_detection(answer):
    assert not complete_identity_answer(chat(answer),'Matt Jones')


@pytest.mark.parametrize('question',['Is this a good time?','Do you want to book Tuesday?','Is this your address?',
                                     'Hey Matt, how are you?','Is this Matt or someone else?','Is this Matt'])
def test_other_questions_are_not_short_circuited(question):
    assert not complete_identity_answer(chat('Yes',question),'Matt')


def test_only_opening_exchange_not_later_identity_recheck():
    previous=[('assistant','Hello'),('user','Hi'),('assistant','How can I help?'),('user','Tell me about it')]
    assert not complete_identity_answer(chat('Yes',previous=previous),'Matt')


def test_manual_call_uses_name_in_spoken_identity_question():
    for name in [None,'','there','unknown','firstname']:
        assert complete_identity_answer(chat('Yes'),name)
        assert complete_identity_answer(chat("It's Matt"),name)


@pytest.mark.parametrize('question',['Is this a good time?','Is this Your Address?',
                                     'Is this First Name?','Is this The Right Number?',
                                     'Is this {{name}}?','Is this Unknown?'])
def test_manual_call_generic_or_placeholder_question_never_uses_fast_path(question):
    assert not complete_identity_answer(chat('Yes',question),None)


@pytest.mark.asyncio
async def test_fast_path_participates_in_existing_detector_and_keeps_threshold():
    calls=[]
    class Delegate:
        model='multilingual';provider='livekit'
        async def supports_language(self,language):return True
        async def unlikely_threshold(self,language):return .7
        async def predict_end_of_turn(self,ctx,**kw):calls.append(kw);return .1
    marks=[]
    detector=OpeningTurnDetector(Delegate(),'Matt',lambda:marks.append('fast'))
    assert await detector.supports_language('en')
    assert await detector.unlikely_threshold('en')==.7
    assert await detector.predict_end_of_turn(chat('Yes'))==1
    assert not calls and marks==['fast']
    assert await detector.predict_end_of_turn(chat('Yes but'),timeout=1)==.1
    assert calls==[{'timeout':1}]
    assert detector.model=='multilingual' and detector.provider=='livekit'



@pytest.mark.asyncio
async def test_actual_sdk_eou_drops_max_delay_only_for_complete_identity(record_property):
    import asyncio
    import time
    from livekit.agents import AgentSession
    from livekit.agents.voice.audio_recognition import AudioRecognition
    from livekit.agents.voice.endpointing import create_endpointing
    class Delegate:
        model='test';provider='offline'
        async def supports_language(self,language):return True
        async def unlikely_threshold(self,language):return .7
        async def predict_end_of_turn(self,ctx,**kw):return .1
    async def measure(answer,adapt,question="Hey, is this Matt?"):
        detector=OpeningTurnDetector(Delegate(),'Matt') if adapt else Delegate()
        received=[]
        hooks=NS(on_end_of_turn=lambda info:received.append(info) or False, on_eot_prediction=lambda event:None)
        rec=AudioRecognition(AgentSession(vad=None),hooks=hooks,
            endpointing=create_endpointing({'mode':'dynamic','min_delay':.35,'max_delay':2.5,'alpha':.9}),
            stt=None,vad=None,using_default_vad=False,interruption_detection=None,turn_detection=detector)
        now=time.time();rec._last_speaking_time=now-.55
        rec._last_final_transcript_time=now-.1;rec._user_turn_start=now-1
        rec._audio_transcript=answer
        ctx=ChatContext();ctx.add_message(role='assistant',content=question)
        rec._run_eou_detection(ctx,trigger='vad')
        await asyncio.wait_for(rec._end_of_turn_task,timeout=4)
        assert len(received)==1
        return received[0].metrics.end_of_turn_delay
    baseline=await measure('Yes',False)
    fixed=await measure('Yes',True)
    unfinished=await measure('Yes but',True)
    closed=await measure('Yes',True,'Would you like a callback?')
    assert closed < 1.0
    record_property('baseline_end_of_turn_seconds',baseline)
    record_property('fixed_identity_end_of_turn_seconds',fixed)
    record_property('unfinished_end_of_turn_seconds',unfinished)
    assert baseline>=2.4 and fixed<1.0 and unfinished>=2.4

@pytest.mark.parametrize('question,answer',[
    ('Are you interested?', 'Yes.'), ('Would you like a callback?', 'No.'),
    ('Do you own the property?', 'Yep!'), ('Can I help?', 'Yeah'),
    ('Hello?', 'Hello'), ('Hello.', 'Hi'),
])
def test_closed_short_answers(question,answer):
    from app.agent.opening_turns import complete_short_answer
    assert complete_short_answer(chat(answer,question))

@pytest.mark.parametrize('question,answer',[
    ('Are you interested?', 'Yes, but'), ('Are you interested?', 'Yes...'),
    ('Are you interested?', 'Yes?'), ('Are you interested?', 'No, wait'),
    ('What is your address?', '14 Main'), ('Is your phone number correct?', 'Yes'),
    ('Would you prefer Tuesday or Wednesday?', 'Yes'), ('What would you like?', 'Yes'),
    ('Can you spell your name?', 'Yes'), ('Hello, how can I help?', 'Hello'),
    ('Are you interested?', 'four one five'), ('Are you interested?', 'Yes—'),
])
def test_pauses_and_open_questions_still_use_semantic_model(question,answer):
    from app.agent.opening_turns import complete_short_answer
    assert not complete_short_answer(chat(answer,question))

@pytest.mark.asyncio
async def test_later_closed_question_uses_existing_detector_fast_path():
    class Delegate:
        async def predict_end_of_turn(self,*args,**kwargs):
            raise AssertionError('closed answer should not hit semantic maximum')
    ctx=chat('Yes','Would you like a callback?',previous=[('assistant','Hello'),('user','Hello'),
        ('assistant','How can I help?'),('user','I need information')])
    assert await OpeningTurnDetector(Delegate(),None).predict_end_of_turn(ctx)==1.0
