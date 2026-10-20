"""Offline installed-SDK sentence release benchmark, NOT caller-audible latency.
Run from backend: python scripts/benchmark_voice_streaming.py --output /tmp/result.json
"""
import argparse
import asyncio
import json
import math
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent.voice_trace import short_sentence_tokenizer

CASES = [
    ('Tuesday works.', ' Would morning or afternoon suit you?'),
    ('It is forty dollars.', ' That includes the initial consultation.'),
    ('We cover Oakland.', ' Which property are you asking about?'),
    ('I have your address.', ' What would you like the team to follow up on?'),
    ('No fee applies.', ' Would you prefer a call tomorrow afternoon?'),
    ('That slot is taken.', ' I can check another day for you.'),
]


def stats(values):
    values = sorted(values)
    return {'n': len(values), 'p50_ms': round(values[math.ceil(.5*len(values))-1], 2),
            'p95_ms': round(values[math.ceil(.95*len(values))-1], 2)} if values else {'n': 0}


async def sample(first, later, enabled):
    stream = short_sentence_tokenizer(enabled).stream()
    started = time.monotonic()
    async def produce():
        # A complete first sentence followed by 15 characters of lookahead.
        stream.push_text(first + later[:15])
        await asyncio.sleep(.15)  # deterministic stand-in for the upstream tail
        stream.push_text(later[15:])
        stream.end_input()
    producer = asyncio.create_task(produce())
    token = await anext(stream)
    elapsed = (time.monotonic() - started) * 1000
    await producer
    await stream.aclose()
    return {'ms': elapsed, 'first_chunk': token.token, 'enabled': enabled}


async def main(output):
    # Warm blingfire once; no provider connection, audio, or billing is involved.
    short_sentence_tokenizer(False).tokenize('Warm up. Next sentence.')
    before, after, results = [], [], []
    for repeat in range(3):
        for first, later in CASES:
            b, a = await sample(first, later, False), await sample(first, later, True)
            before.append(b['ms']); after.append(a['ms'])
            results.append({'repeat': repeat, 'first': first, 'before': b, 'after': a})
    concurrent = await asyncio.gather(*(sample(*CASES[i % len(CASES)], True) for i in range(20)))
    out = {'measurement': 'Local tokenizer first text release; simulated 150 ms upstream tail, no TTS or SIP',
           'sdk': 'livekit-agents 1.6.4', 'before': stats(before), 'after': stats(after),
           'concurrent_20_local_tokenizers': stats([x['ms'] for x in concurrent]), 'samples': results}
    Path(output).write_text(json.dumps(out, indent=2))
    print(json.dumps({k:v for k,v in out.items() if k != 'samples'}))


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--output', required=True)
    asyncio.run(main(p.parse_args().output))
