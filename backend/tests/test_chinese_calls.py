"""Mandarin agent (Mei, Compass Multifamily): built-in lines in the call's language, Chinese mailboxes, and a review
that knows the agent speaks Chinese."""

import asyncio


def test_built_in_lines_follow_the_agent_language():
    from app.agent.runtime import check_in_line
    from app.services.callbacks import greeting

    assert check_in_line("zh") == "喂，您好，听得到吗？"
    assert check_in_line("en") == check_in_line(None) == check_in_line("multi") == "Hello? Can you hear me okay?"
    assert greeting({"recognized": True, "first_name": "Aleck"}, "zh") == "您好，谢谢您回电！请问是Aleck吗？"
    assert greeting({}, "zh") == "您好，谢谢您回电！请问怎么称呼您？"
    assert greeting({"recognized": True, "first_name": "Sam"}).startswith("Hi, thanks for calling back")


def test_chinese_mailboxes_and_carrier_messages_are_machines():
    from app.agent.runtime import voicemail_answered, voicemail_greeting_match

    for text in ("請留", "请在嘀声后留言", "您拨打的用户暂时无法接通，请稍后再拨", "您撥打的電話已關機", "語音信箱"):
        assert voicemail_greeting_match(text), text
        assert voicemail_answered([{"role": "assistant", "text": "您好，请问是 Mary 吗？"},
                                   {"role": "user", "text": text}]), text
    for text in ("我聽你,誰", "你有什么事啊", "不卖，谢谢", "哪处公寓？"):
        assert voicemail_greeting_match(text) is None, text


def test_review_is_told_the_agent_speaks_chinese(monkeypatch):
    from app.services import llm

    seen = {}

    async def fake(prompt):
        seen["prompt"] = prompt
        return {"summary": "s", "outcome": "no_decision", "sentiment": "neutral", "extracted": {}}
    monkeypatch.setattr(llm, "_analysis_json", fake)
    monkeypatch.setattr(llm.settings, "openai_api_key", "x")
    t = [{"role": "assistant", "text": "您好，请问是 Aleck 吗？"}, {"role": "user", "text": "我聽你，誰？"}]
    asyncio.run(llm.analyze_call(t, None, "", language="zh"))
    assert "never a language barrier" in seen["prompt"] and "Chinese" in seen["prompt"]
    asyncio.run(llm.analyze_call(t, None, "", language="en"))
    assert "never a language barrier" not in seen["prompt"]


def test_screener_line_follows_the_agent_language():
    from app.agent.runtime import screener_line

    assert screener_line("zh", "Shu") == "喂，Shu，是我……"
    assert screener_line(None, "Sam") == "Hey Sam, it's just..." and screener_line("en") == "Hey, it's just..."
