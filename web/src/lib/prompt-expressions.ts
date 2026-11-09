/** Existing speech markup stays the storage format; editors work with readable text and range markers. */
export type ExpressionMarker = { offset: number; kind: "emotion" | "break"; value: string; raw: string };
export type ExpressionRange = { marker: number; start: number; end: number; label: string; kind: "emotion" | "break" };

export const EXPRESSION_EMOTIONS = ("neutral happy excited enthusiastic elated euphoric triumphant amazed surprised flirtatious curious content peaceful serene calm grateful affectionate trust sympathetic anticipation mysterious angry mad outraged frustrated agitated threatened disgusted contempt envious sarcastic ironic sad dejected melancholic disappointed hurt guilty bored tired rejected nostalgic wistful apologetic hesitant insecure confused resigned anxious panicked alarmed scared proud confident distant skeptical contemplative determined").split(" ");
const EMOTIONS = new Set(EXPRESSION_EMOTIONS);
const LABELS: Record<string, string> = { content: "Warm", sympathetic: "Reassuring" };
const COMMON_EMOTIONS = ["curious", "calm", "content", "confident", "sympathetic", "happy", "neutral"];
export const EXPRESSION_CHOICES: ReadonlyArray<readonly [string, string]> = [
  ...COMMON_EMOTIONS.map((value) => [value, expressionLabel(value)] as const),
  ...EXPRESSION_EMOTIONS.filter((value) => !COMMON_EMOTIONS.includes(value))
    .sort((a, b) => a.localeCompare(b)).map((value) => [value, expressionLabel(value)] as const),
  ["pause:200", "Short pause after · 200 ms"], ["pause:500", "Longer pause after · 500 ms"],
];
export function expressionLabel(value: string) { return LABELS[value] ?? value.charAt(0).toUpperCase() + value.slice(1); }

export function parseExpressions(raw: string) {
  const tokens = /<emotion\s+value\s*=\s*(["'])([a-z]+)\1\s*\/>|<break\s+time\s*=\s*(["'])(\d+(?:\.\d+)?)(ms|s)\3\s*\/>/gi;
  const markers: ExpressionMarker[] = [];
  let text = "", cursor = 0;
  for (const match of raw.matchAll(tokens)) {
    const emotion = match[2]?.toLowerCase();
    const duration = Number(match[4]) * (match[5]?.toLowerCase() === "s" ? 1000 : 1);
    if (emotion ? !EMOTIONS.has(emotion) : !Number.isInteger(duration) || duration <= 0 || duration > 2000) continue;
    text += raw.slice(cursor, match.index);
    markers.push({ offset: text.length, kind: emotion ? "emotion" : "break", value: emotion || String(duration), raw: match[0] });
    cursor = match.index + match[0].length;
  }
  return { text: text + raw.slice(cursor), markers };
}

function serialize(text: string, markers: ExpressionMarker[]) {
  const ordered = [...markers].sort((a, b) => a.offset - b.offset);
  const normalized: ExpressionMarker[] = [];
  let emotion: string | undefined;
  for (const marker of ordered) {
    if (marker.kind === "emotion") {
      if (marker.value === emotion) continue;
      const previous = normalized.at(-1);
      if (previous?.kind === "emotion" && previous.offset === marker.offset) normalized.pop();
      emotion = marker.value;
    }
    normalized.push(marker);
  }
  let raw = "", cursor = 0;
  for (const marker of normalized) {
    const offset = Math.max(cursor, Math.min(text.length, marker.offset));
    raw += text.slice(cursor, offset) + marker.raw;
    cursor = offset;
  }
  return raw + text.slice(cursor);
}
function emotionAt(markers: ExpressionMarker[], offset: number) {
  return markers.filter((m) => m.kind === "emotion" && m.offset <= offset).at(-1)?.value ?? "neutral";
}
function emotionMarker(offset: number, value: string): ExpressionMarker {
  return { offset, kind: "emotion", value, raw: `<emotion value="${value}"/>` };
}

export function expressionRanges(raw: string): ExpressionRange[] {
  const { text, markers } = parseExpressions(raw);
  return markers.flatMap<ExpressionRange>((marker, index) => {
    if (marker.kind === "break") return [{ marker: index, start: marker.offset, end: marker.offset, label: `${marker.value} ms pause`, kind: "break" as const }];
    const end = markers.slice(index + 1).find((m) => m.kind === "emotion")?.offset ?? text.length;
    if (marker.value === "neutral" || end <= marker.offset || !text.slice(marker.offset, end).trim()) return [];
    return [{ marker: index, start: marker.offset, end, label: expressionLabel(marker.value), kind: "emotion" as const }];
  });
}

export function addExpression(raw: string, start: number, end: number, choice: string) {
  const { text, markers } = parseExpressions(raw);
  if (start < 0 || end > text.length || start >= end) return raw;
  // Speech controls must never split a lead placeholder such as {{first_name}}.
  for (const match of text.matchAll(/\{\{[^{}]+\}\}/g)) {
    const stop = match.index + match[0].length;
    if (start < stop && end > match.index) { start = Math.min(start, match.index); end = Math.max(end, stop); }
  }
  while (/[?!]/.test(text[end] ?? "")) end++;
  if (choice.startsWith("pause:")) {
    const duration = Number(choice.slice(6));
    if (!Number.isInteger(duration) || duration <= 0 || duration > 2000) return raw;
    return serialize(text, [...markers, { offset: end, kind: "break", value: String(duration), raw: `<break time="${duration}ms"/>` }]);
  }
  if (!EMOTIONS.has(choice)) return raw;
  const restore = emotionAt(markers, end);
  return serialize(text, [...markers.filter((m) => m.kind !== "emotion" || m.offset < start || m.offset > end),
    emotionMarker(start, choice), emotionMarker(end, restore)]);
}

export function removeExpression(raw: string, index: number) {
  const { text, markers } = parseExpressions(raw);
  const target = markers[index];
  if (!target) return raw;
  return serialize(text, markers.flatMap((m, i) => i !== index ? [m] : m.kind === "break" ? [] : [emotionMarker(m.offset, "neutral")]));
}

export function editExpressionText(raw: string, next: string) {
  const { text, markers } = parseExpressions(raw);
  if (next === text) return raw;
  if (!next.trim()) return next;
  let start = 0;
  while (start < text.length && start < next.length && text[start] === next[start]) start++;
  let oldEnd = text.length, newEnd = next.length;
  while (oldEnd > start && newEnd > start && text[oldEnd - 1] === next[newEnd - 1]) { oldEnd--; newEnd--; }
  const delta = newEnd - oldEnd;
  const shifted = markers.filter((m) => m.offset <= start || m.offset >= oldEnd).map((m) => ({ ...m, offset: m.offset <= start ? m.offset : m.offset + delta }));
  if (emotionAt(markers, start) !== emotionAt(markers, oldEnd)) shifted.push(emotionMarker(newEnd, emotionAt(markers, oldEnd)));
  return serialize(next, shifted);
}
