"""Read content-free JSONL voice_trace events, output per-speech overlapping timelines.

Durations are never summed. Unknown correlations/buckets stay unknown. Caller
 audibility and meaningful onset require separately synchronized listening tests.
"""
import argparse
from collections import Counter, defaultdict
import html
import json
import math
import re
from pathlib import Path


def parse_line(line):
    """Accept JSON logs, Railway message rows, or this app's console renderer."""
    try:
        row = json.loads(line)
    except (ValueError, TypeError):
        row = None
    if isinstance(row, dict) and row.get('event') == 'voice_trace':
        return row
    if isinstance(row, dict):
        line = row.get('message', '')
    line = re.sub(r'\x1b\[[0-9;]*m', '', line)
    if not re.search(r'\bvoice_trace\b', line):
        return None
    fields = {}
    for key, raw in re.findall(r'(\w+)=([^\s]+)', line):
        if raw in ('True', 'False', 'None'):
            value = {'True':True, 'False':False, 'None':None}[raw]
        else:
            try: value = float(raw) if '.' in raw else int(raw)
            except ValueError: value = raw
        fields[key] = value
    return {'event':'voice_trace', **fields} if all(k in fields for k in ('stage','clock_id','offset_ms')) else None


def distribution(values):
    x = sorted(values)
    return {'n': len(x), 'p50_ms': round(x[math.ceil(.5*len(x))-1], 2),
            'p95_ms': round(x[math.ceil(.95*len(x))-1], 2)} if x else {'n': 0}


def report(events):
    events = [e for e in events if e.get('event') == 'voice_trace']
    grouped = defaultdict(list)
    for e in events:
        grouped[(e['clock_id'], e.get('speech_id') or e.get('provider_speech_id') or 'uncorrelated')].append(e)
    groups = []
    values = defaultdict(list)
    for (clock, speech), rows in grouped.items():
        rows.sort(key=lambda x: x['offset_ms'])
        stages = Counter(x['stage'] for x in rows)
        source = next((x.get('source') for x in rows if x['stage'] == 'speech_created'), None)
        interrupted = any(x.get('interrupted') for x in rows if x['stage'] == 'speech_done')
        bucket = ('uncorrelated' if speech == 'uncorrelated' else 'interruption_recovery_or_interrupted'
                  if interrupted else 'manual_speech_or_startup' if source == 'say'
                  else 'tool_dependent' if stages['tool_request'] else 'ordinary_reply' if source == 'generate_reply'
                  else 'unknown')
        for x in rows:
            if x['stage'] == 'sdk_item_metrics' and x.get('role') == 'assistant' and 'e2e_latency' in x:
                values[bucket].append(x['e2e_latency'] * 1000)
        groups.append({'clock_id': clock, 'speech_id': speech, 'bucket': bucket, 'events': rows})
    # Reuse indicator: same turn fingerprint requested before commitment and a
    # matching speech produced worker output. It is not a private SDK invalidation verdict.
    by_clock = defaultdict(list)
    for e in events: by_clock[e['clock_id']].append(e)
    speculative, played, cancelled = set(), set(), set()
    for clock, rows in by_clock.items():
        commits = {x.get('turn_key'): x['offset_ms'] for x in rows if x['stage'] == 'turn_committed'}
        for e in rows:
            key = (clock, e.get('speech_id'))
            if e['stage'] == 'llm_request' and e.get('turn_key') in commits and e['offset_ms'] < commits[e['turn_key']]:
                speculative.add(key)
            if e['stage'] == 'agent_speaking': played.add(key)
            if e['stage'] == 'llm_chunk_end' and e.get('status') == 'cancelled_or_failed': cancelled.add(key)
    provider_usage = defaultdict(Counter)
    for e in events:
        if e['stage'] == 'provider_metrics':
            bucket = e.get('provider_metric', 'unknown')
            provider_usage[bucket]['requests'] += 1
            provider_usage[bucket]['cancelled'] += int(bool(e.get('cancelled')))
            for key in ('completion_tokens','prompt_tokens','audio_duration','characters_count'):
                if isinstance(e.get(key), (int,float)):
                    provider_usage[bucket][key] += e[key]
    return {'metric': 'SDK worker-output e2e, not caller-audible latency',
            'distributions': {k: distribution(v) for k,v in values.items()},
            'provider_consumption_not_invoice': dict(provider_usage),
            'speculation': {'precommit_speeches': len(speculative),
                            'subsequently_playing': len(speculative & played),
                            'cancelled_or_failed_streams': len(speculative & cancelled),
                            'invalidation_reason': 'not exposed by public SDK; requires SDK debug traces'},
            'gaps': ['No PSTN caller-audibility clock', 'Meaningful onset vs filler requires annotated listening',
                     'No inference of cross-service ordering', 'Interrupted generation is not necessarily false interruption'],
            'timelines': groups}


def write_html(result, path):
    lanes = []
    for g in result['timelines']:
        rows = g['events']; start = rows[0]['offset_ms']; span = max(1, rows[-1]['offset_ms'] - start)
        dots = ''.join(f'<tr><td>{html.escape(x["stage"])}</td><td>{x["offset_ms"]:.1f}</td><td><div style="margin-left:{(x["offset_ms"]-start)/span*95:.2f}%;width:5px;height:12px;background:#14b8a6"></div></td></tr>' for x in rows)
        lanes.append(f'<details open><summary>{html.escape(g["speech_id"])} · {g["bucket"]} · {g["clock_id"]}</summary><table><thead><tr><th>Stage</th><th>Process offset ms</th><th>Overlapping timeline</th></tr></thead>{dots}</table></details>')
    Path(path).write_text('<!doctype html><meta charset="utf-8"><title>BlackSync voice timelines</title><style>body{font:15px system-ui;background:#111827;color:#e5e7eb;padding:24px}table{width:100%;text-align:left}td{padding:5px}td:last-child{width:50%}details{margin:20px 0}summary{cursor:pointer}</style><h1>BlackSync voice timelines</h1><p>Worker observations only. Timelines share a clock only within the same clock ID. Stages overlap; do not add durations.</p>'+''.join(lanes))


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('jsonl');p.add_argument('--output',required=True)
    a=p.parse_args();result=report([row for line in Path(a.jsonl).read_text().splitlines()
                                 if (row := parse_line(line)) is not None])
    Path(a.output+'.json').write_text(json.dumps(result,indent=2));write_html(result,a.output+'.html')
    print(json.dumps({k:v for k,v in result.items() if k != 'timelines'}))
