import asyncio

import pytest

from app.agent.expressions import DELIVERY_STYLES, allows_laughter, instructions, speech_text, synthesize_expressions
from app.agent.runtime import build_instructions
from app.agent.speech_guard import clean, guarded
from app.agent.voice_tuning import voice_tuning


def cfg(**values):
    return {'voice_id':'voice-id','voice_tuning':{'expressions_enabled':True,'expression_mode':'automatic', **values}}


@pytest.mark.parametrize('style', DELIVERY_STYLES)
def test_automatic_style_is_private_contextual_guidance(style):
    settings=cfg(delivery_style=style,delivery_direction='Be softer if they say they are busy.')
    prompt=build_instructions(settings,{},channel='web')
    assert '# AUTOMATIC DELIVERY' in prompt
    assert 'Be softer if they say they are busy.' in prompt
    assert 'Most speech should remain untagged' in prompt
    assert 'Preserve the script’s facts and purpose' in prompt
    assert 'Never generate [laughter]' in prompt
    assert 'wait for the recipient' in prompt
    assert '# AUTOMATIC DELIVERY' not in build_instructions(settings,{},channel='chat')
    settings['voice_id']='elevenlabs:example'
    assert instructions(settings)==''


def test_automatic_does_not_apply_blanket_emotion_or_change_legacy_tone():
    raw=cfg(tone='upbeat',default_emotion='excited')['voice_tuning']
    assert voice_tuning(raw)['emotion'] is None
    assert voice_tuning({**raw,'expression_mode':'script'})['emotion']=='excited'
    assert voice_tuning({'tone':'warm'})['emotion']=='Content'
    assert not allows_laughter(cfg())
    assert allows_laughter(cfg(automatic_laughter=True))
    assert allows_laughter({'voice_tuning':{'expressions_enabled':True}})
    assert '# AUTOMATIC DELIVERY' not in instructions({'voice_id':'voice-id','voice_tuning':{'expressions_enabled':True}})


def test_laughter_is_blocked_in_guard_first_message_and_synthesis_unless_allowed():
    text='<emotion value="curious"/>Hey James? [laughter] How are you?'
    assert '[laughter]' not in clean(text, expressions=True,allow_laughter=False)
    assert '[laughter]' in clean(text, expressions=True,allow_laughter=True)
    async def chunks():
        for char in text: yield char
    async def synthesize(text):
        async for chunk in text: yield chunk
    async def run(allow):
        safe=guarded(chunks(),expressions=True,allow_laughter=allow)
        transformed=speech_text(safe,True,allow_laughter=allow)
        return ''.join([chunk async for chunk in synthesize_expressions(transformed,synthesize,allow_laughter=allow)])
    assert '[laughter]' not in asyncio.run(run(False))
    assert '[laughter]' in asyncio.run(run(True))


def test_delivery_api_roundtrip_validation_and_toggle_off(client, agent_id):
    data={'expressions_enabled':True,'expression_mode':'automatic','delivery_style':'warm',
          'delivery_direction':'Be curious about the property and reassuring if they are unsure.', 'automatic_laughter':False}
    response=client.patch(f'/api/agents/{agent_id}',json={'voice_tuning':data})
    assert response.status_code==200, response.text
    saved=client.get(f'/api/agents/{agent_id}').json()['voice_tuning']
    assert all(saved[key]==value for key,value in data.items())
    for invalid in [{'expression_mode':'unknown'}, {'delivery_style':'unknown'}, {'delivery_direction':'x'*501}]:
        assert client.patch(f'/api/agents/{agent_id}',json={'voice_tuning':invalid}).status_code==422
    disabled={**saved,'expressions_enabled':False}
    response=client.patch(f'/api/agents/{agent_id}',json={'voice_tuning':disabled})
    assert response.status_code==200
    assert instructions(response.json())==''
    assert response.json()['voice_tuning']['delivery_direction']==data['delivery_direction']


@pytest.mark.parametrize('text', [
    'Hey, this is James, right?', 'Hi, is this James?', 'Am I speaking with James?',
    'Hi James, correct?', 'Have I reached James?', "You’re James, right?",
])
def test_saved_identity_openings_automatically_request_curiosity(text):
    from app.agent.expressions import opening_delivery
    assert opening_delivery(text,cfg()) == '<emotion value="curious"/>' + text


def test_curiosity_does_not_spread_to_the_whole_saved_opening():
    from app.agent.expressions import opening_delivery, clean_markup
    text='Hey, this is James, right? I’m calling on behalf of Josh.'
    result=opening_delivery(text,cfg())
    assert result=='<emotion value="curious"/>Hey, this is James, right?<emotion value="neutral"/> I’m calling on behalf of Josh.'
    assert clean_markup(result)==text


def test_identity_opening_leaves_manual_disabled_other_voices_and_nonquestions_alone():
    from app.agent.expressions import opening_delivery
    question='Hey, this is James, right?'
    for config in [cfg(expressions_enabled=False),cfg(expression_mode='script'),
                   {'voice_id':'elevenlabs:example','voice_tuning':cfg()['voice_tuning']}]:
        assert opening_delivery(question,config)==question
    for text in ['Hi, I’m calling on behalf of Josh.', '<emotion value="calm"/>'+question,
                 'What time works for you?']:
        assert opening_delivery(text,cfg())==text
