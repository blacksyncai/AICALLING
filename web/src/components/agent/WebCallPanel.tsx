"use client";

import { ConnectionState, Room, RoomEvent, Track, type RemoteParticipant, type RemoteTrack, type TextStreamReader } from "livekit-client";
import { ExternalLink, Mic, MicOff, PhoneCall, PhoneOff } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { post } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Button, Notice } from "../ui";

type Line = { id: string; who: "agent" | "you"; text: string; final: boolean };
type Phase = "idle" | "connecting" | "live" | "ended";

function useLevel(getLevel: () => number, active: boolean) {
  const [level, setLevel] = useState(0);
  useEffect(() => {
    if (!active) return setLevel(0);
    let raf = 0;
    const tick = () => {
      setLevel((prev) => prev * 0.6 + getLevel() * 0.4);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [active, getLevel]);
  return level;
}

export function WebCallPanel({
  agentId,
  enabled,
  variables,
  beforeStart,
}: {
  agentId: string;
  enabled: boolean;
  variables: Record<string, string>;
  beforeStart: () => Promise<boolean>;
}) {
  const roomRef = useRef<Room | null>(null);
  const audioRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState("");
  const [lines, setLines] = useState<Line[]>([]);
  const [muted, setMuted] = useState(false);
  const [agentState, setAgentState] = useState("connecting");
  const [callId, setCallId] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);

  const agentLevel = useLevel(() => {
    const room = roomRef.current;
    const agent = room ? [...room.remoteParticipants.values()][0] : undefined;
    return agent?.audioLevel ?? 0;
  }, phase === "live");
  const youLevel = useLevel(() => roomRef.current?.localParticipant.audioLevel ?? 0, phase === "live" && !muted);

  useEffect(() => {
    if (phase !== "live") return;
    const t0 = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(id);
  }, [phase]);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [lines]);

  useEffect(() => () => void roomRef.current?.disconnect(), []);

  // Guards a double-click on Start, and lets End cancel a call that's still connecting.
  const startingRef = useRef(false);
  const cancelledRef = useRef(false);

  async function start() {
    if (startingRef.current) return;
    startingRef.current = true;
    cancelledRef.current = false;
    setError("");
    try {
      await connect();
    } finally {
      startingRef.current = false;
    }
  }

  async function connect() {
    if (!(await beforeStart())) return;
    if (cancelledRef.current) return;
    setPhase("connecting");
    setLines([]);
    setElapsed(0);
    setAgentState("connecting");
    try {
      const { url, token, call_id } = await post<{ url: string; token: string; call_id: string }>(
        `/api/agents/${agentId}/web-call`,
        { variables },
      );
      setCallId(call_id);
      const room = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = room;

      room.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === Track.Kind.Audio) {
          const el = track.attach();
          audioRef.current?.appendChild(el);
        }
      });
      room.on(RoomEvent.TrackUnsubscribed, (track: RemoteTrack) => track.detach().forEach((el) => el.remove()));
      room.on(RoomEvent.ParticipantAttributesChanged, (attrs: Record<string, string>, p) => {
        if ((p as RemoteParticipant).isAgent !== false && attrs["lk.agent.state"]) setAgentState(attrs["lk.agent.state"]);
      });
      room.on(RoomEvent.ConnectionStateChanged, (s: ConnectionState) => {
        if (s === ConnectionState.Disconnected) setPhase("ended");
      });

      room.registerTextStreamHandler("lk.transcription", async (reader: TextStreamReader, from: { identity: string }) => {
        const attrs = reader.info.attributes ?? {};
        const id = attrs["lk.segment_id"] ?? reader.info.id;
        const who: Line["who"] = from.identity === room.localParticipant.identity ? "you" : "agent";
        for await (const chunk of reader) {
          setLines((prev) => {
            const i = prev.findIndex((l) => l.id === id);
            if (i === -1) return [...prev, { id, who, text: chunk, final: false }];
            const next = [...prev];
            next[i] = { ...next[i], text: next[i].text + chunk };
            return next;
          });
        }
        setLines((prev) => prev.map((l) => (l.id === id ? { ...l, final: true } : l)));
      });

      if (cancelledRef.current) return void room.disconnect();
      await room.connect(url, token);
      if (cancelledRef.current) return void room.disconnect();
      await room.localParticipant.setMicrophoneEnabled(true);
      if (cancelledRef.current) return void room.disconnect();
      setPhase("live");
    } catch (e) {
      setError((e as Error).message);
      setPhase("idle");
      roomRef.current?.disconnect();
    }
  }

  async function end() {
    cancelledRef.current = true;
    await roomRef.current?.disconnect();
    setPhase("ended");
  }

  async function toggleMute() {
    const next = !muted;
    await roomRef.current?.localParticipant.setMicrophoneEnabled(!next);
    setMuted(next);
  }

  const stateLabel =
    phase === "connecting"
      ? "Connecting…"
      : phase === "ended"
        ? "Call ended"
        : { listening: "Listening", thinking: "Thinking…", speaking: "Speaking", initializing: "Joining…", connecting: "Joining…" }[agentState] ?? "Live";

  return (
    <div className="flex h-full flex-col">
      <div ref={audioRef} className="hidden" />
      <div className="flex flex-col items-center gap-4 py-6">
        <div className="relative flex h-28 w-28 items-center justify-center">
          <div
            className="absolute inset-0 rounded-full bg-brand-500/15 transition-transform duration-100"
            style={{ transform: `scale(${1 + Math.min(agentLevel * 2.2, 0.45)})` }}
          />
          <div
            className={cn(
              "relative flex h-20 w-20 items-center justify-center rounded-full bg-gradient-to-br text-white shadow-lg",
              phase === "live" ? "brand-gradient" : "from-zinc-400 to-zinc-500",
            )}
          >
            <PhoneCall className="h-7 w-7" />
          </div>
        </div>
        <div className="text-center">
          <div className="text-sm font-medium">{phase === "idle" ? "Talk to your agent" : stateLabel}</div>
          <div className="text-xs text-zinc-500">
            {phase === "live" ? `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, "0")}` : "Uses your microphone — headphones recommended"}
          </div>
        </div>
        {phase === "live" && (
          <div className="flex h-4 items-end gap-0.5" aria-hidden>
            {Array.from({ length: 12 }).map((_, i) => (
              <span
                key={i}
                className="w-1 rounded-full bg-emerald-500 transition-all duration-75"
                style={{ height: `${Math.max(3, Math.min(16, youLevel * 60 * (0.5 + ((i * 7) % 5) / 5)))}px` }}
              />
            ))}
          </div>
        )}
        <div className="flex gap-2">
          {phase === "live" || phase === "connecting" ? (
            <>
              <Button onClick={toggleMute} disabled={phase !== "live"}>
                {muted ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
                {muted ? "Unmute" : "Mute"}
              </Button>
              <Button variant="danger" onClick={end}>
                <PhoneOff className="h-4 w-4" /> End
              </Button>
            </>
          ) : (
            <Button variant="primary" onClick={start} disabled={!enabled}>
              <PhoneCall className="h-4 w-4" /> {phase === "ended" ? "Call again" : "Start voice test"}
            </Button>
          )}
        </div>
        {!enabled && (
          <Notice>
            Voice testing isn&apos;t available right now. Message us in the chat and we&apos;ll get it sorted.
          </Notice>
        )}
        {error && <Notice tone="red">{error}</Notice>}
        {phase === "ended" && callId && (
          <Link href={`/calls/${callId}`} className="inline-flex items-center gap-1 text-xs font-medium text-brand-600 hover:text-brand-700">
            View call log & AI summary <ExternalLink className="h-3 w-3" />
          </Link>
        )}
      </div>
      <div ref={scrollRef} className="scroll-thin min-h-0 flex-1 space-y-2 overflow-y-auto border-t border-zinc-100 px-1 pt-3">
        {lines.length === 0 && phase !== "idle" && <p className="text-center text-xs text-zinc-400">Live transcript appears here.</p>}
        {lines.map((l) => (
          <div key={l.id} className={cn("flex", l.who === "you" ? "justify-end" : "justify-start")}>
            <div
              className={cn(
                "max-w-[85%] rounded-2xl px-3 py-2 text-sm",
                l.who === "you" ? "rounded-br-sm bg-brand-600 text-white" : "rounded-bl-sm bg-zinc-100 text-zinc-800",
                !l.final && "opacity-70",
              )}
            >
              {l.text}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
