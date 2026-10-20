// Run with Node 22.6+: node --experimental-strip-types --test src/components/ui/ai-orb-state.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { AI_ORB_STATES, AI_ORB_LABELS, callOrbState, orbStateFor } from './ai-orb-state.ts';
test('every public state has a readable accessible label', () => {
  assert.equal(new Set(AI_ORB_STATES).size, 10);
  for (const state of AI_ORB_STATES) assert.ok(AI_ORB_LABELS[state].startsWith('Assistant'));
});
test('errors and connection lifecycle take priority over stale speaking signals', () => {
  const base = { agentState: 'speaking', agentAudioLevel: 1, hasError: false };
  assert.equal(callOrbState({ ...base, phase: 'idle' }), 'idle');
  assert.equal(callOrbState({ ...base, phase: 'connecting' }), 'thinking');
  assert.equal(callOrbState({ ...base, phase: 'ended' }), 'done');
  assert.equal(callOrbState({ ...base, phase: 'ended', hasError: true }), 'error');
});
test('live call state follows reported activity without inventing tool or approval events', () => {
  const live = { phase: 'live', hasError: false };
  assert.equal(callOrbState({ ...live, agentState: 'listening' }), 'listening');
  assert.equal(callOrbState({ ...live, agentState: 'speaking' }), 'streaming');
  assert.equal(callOrbState({ ...live, agentState: 'thinking' }), 'thinking');
  assert.equal(callOrbState({ ...live, agentState: 'listening', agentAudioLevel: 0.1 }), 'streaming');
  for (const agentState of ['initializing', 'connecting', 'unknown', '']) assert.equal(callOrbState({ ...live, agentState }), 'thinking');
});
test('pending requests never imply streaming, success or tool execution', () => {
  assert.equal(orbStateFor({ status: 'submitted' }), 'thinking');
  assert.equal(orbStateFor({ status: 'error', activity: 'text', hasDraft: true }), 'error');
  assert.equal(orbStateFor({ status: 'streaming' }), 'thinking');
  assert.equal(orbStateFor({ status: 'streaming', activity: 'text' }), 'streaming');
});
test('explicit activity maps to distinct states and resting states stay honest', () => {
  const activities = { question:'waiting-approval', reasoning:'reasoning', text:'streaming', 'tool-call':'tool-call', 'tool-result':'tool-result' };
  for (const [activity, expected] of Object.entries(activities)) assert.equal(orbStateFor({ status:'streaming', activity }), expected);
  assert.equal(orbStateFor({ status:'ready' }), 'idle');
  assert.equal(orbStateFor({ status:'ready', hasDraft:true }), 'listening');
  assert.equal(orbStateFor({ status:'ready', hasAnswered:true }), 'done');
  assert.equal(orbStateFor({ status:'ready', activity:'question' }), 'waiting-approval');
});
