"""Observed session-state gaps; excludes carrier/network playback after the worker."""
import math

class TurnLatency:
    def __init__(self):
        self.agent_speaking=False
        self.user_speaking=False
        self.pending_stop=None
        self.interrupted=False
        self.interruptions=0
        self.responses=[]
        self.recoveries=[]

    def user_state(self, old, new, timestamp):
        if new=='speaking' and old!='speaking':
            self.user_speaking=True
            self.pending_stop=None
            self.interrupted=self.agent_speaking
            if self.interrupted:self.interruptions+=1
        elif old=='speaking' and new!='speaking':
            self.user_speaking=False
            self.pending_stop=timestamp

    def agent_state(self, old, new, timestamp):
        self.agent_speaking=new=='speaking'
        if new!='speaking' or old=='speaking' or self.user_speaking or self.pending_stop is None:
            return None
        gap=max(0.,timestamp-self.pending_stop)
        self.pending_stop=None
        bucket=self.recoveries if self.interrupted else self.responses
        bucket.append(gap)
        del bucket[:-200]
        return {'seconds':round(gap,3),'kind':'interruption_recovery' if self.interrupted else 'response'}

    def summary(self):
        out={'interruptions':self.interruptions,'response_gap_samples':len(self.responses),
             'interruption_recovery_samples':len(self.recoveries)}
        if self.responses:
            values=sorted(self.responses)
            out.update(avg_turn_gap=round(sum(values)/len(values),3),
                p50_turn_gap=round(values[math.ceil(.5*len(values))-1],3),
                p95_turn_gap=round(values[math.ceil(.95*len(values))-1],3),
                max_turn_gap=round(max(values),3))
        if self.recoveries:out['avg_interruption_recovery']=round(sum(self.recoveries)/len(self.recoveries),3)
        return out


def stage_timings(metrics):
    """Only numeric SDK timings; never log message text or provider credentials."""
    if not isinstance(metrics, dict):
        return {}
    allowed = ('transcription_delay', 'end_of_turn_delay', 'on_user_turn_completed_delay',
               'llm_node_ttft', 'tts_node_ttfb', 'playback_latency', 'e2e_latency')
    return {key: round(float(metrics[key]), 3) for key in allowed
            if isinstance(metrics.get(key), (int, float)) and not isinstance(metrics[key], bool)
            and math.isfinite(metrics[key]) and metrics[key] >= 0}
