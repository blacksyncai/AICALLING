/** UI states describe reported activity, not inferred tool execution or caller audibility. */
export const AI_ORB_STATES = ["idle", "listening", "thinking", "reasoning", "tool-call", "tool-result", "streaming", "waiting-approval", "error", "done"] as const;
export type AiOrbState = (typeof AI_ORB_STATES)[number];
export type AgentActivity = "reasoning" | "tool-call" | "tool-result" | "text" | "question";
export const AI_ORB_LABELS: Record<AiOrbState, string> = {
  done: "Assistant has finished", error: "Assistant ran into an error", idle: "Assistant is ready",
  listening: "Assistant is listening", reasoning: "Assistant is reasoning", streaming: "Assistant is writing the answer",
  thinking: "Assistant is thinking", "tool-call": "Assistant is using a tool", "tool-result": "Assistant is reading tool results",
  "waiting-approval": "Assistant is waiting for your answer",
};
const LIVE_STATE: Record<AgentActivity, AiOrbState> = { question: "waiting-approval", reasoning: "reasoning", text: "streaming", "tool-call": "tool-call", "tool-result": "tool-result" };
export function orbStateFor({ status, activity, hasDraft = false, hasAnswered = false }: {
  status: "ready" | "submitted" | "streaming" | "error"; activity?: AgentActivity; hasDraft?: boolean; hasAnswered?: boolean;
}): AiOrbState {
  if (status === "error") return "error";
  if (status === "submitted") return "thinking";
  if (status === "streaming") return activity ? LIVE_STATE[activity] : "thinking";
  if (activity === "question") return "waiting-approval";
  if (hasDraft) return "listening";
  return hasAnswered ? "done" : "idle";
}
export function callOrbState({ phase, agentState, hasError, agentAudioLevel = 0 }: {
  phase: "idle" | "connecting" | "live" | "ended"; agentState: string; hasError: boolean; agentAudioLevel?: number;
}): AiOrbState {
  if (hasError) return "error";
  if (phase === "ended") return "done";
  if (phase === "idle") return "idle";
  if (phase === "connecting") return "thinking";
  if (agentState === "speaking" || agentAudioLevel > 0.02) return "streaming";
  if (agentState === "listening") return "listening";
  // Initializing/connecting/unknown states never imply the microphone is being listened to.
  return "thinking";
}
