"use client";

import { Mic, Square, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Field, Input, Modal, Notice } from "@/components/ui";
import { sessionToken } from "@/lib/clerk";
import { del, fetcher } from "@/lib/api";
import type { Voice } from "@/lib/types";

export type MyVoices = { voices: Voice[]; limit: number };

const SCRIPT =
  "Hi, this is me recording a sample of my voice. I help people buy and sell homes in our area, and I love what I do. " +
  "When I call, I like to keep things short and friendly, ask a couple of questions, and see if there's a way I can help. " +
  "If now isn't a good time, no problem at all, we can always talk later.";

/** The account's own cloned voices (only this account sees them). */
export function useMyVoices() {
  return useSWR<MyVoices>("/api/settings/voices/mine", fetcher);
}

/** "Clone your voice": record (or upload) a minute of speech and the agent can call in that voice. */
export function CloneVoiceButton({ onCloned }: { onCloned: (voice: Voice) => void }) {
  const toast = useToast();
  const { data, mutate } = useMyVoices();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [file, setFile] = useState<Blob | null>(null);
  const [recording, setRecording] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => () => { if (timer.current) clearInterval(timer.current); }, []);

  async function startRecording() {
    setError("");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        setFile(new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
      };
      rec.start();
      recorder.current = rec;
      setSeconds(0);
      setRecording(true);
      timer.current = setInterval(() => setSeconds((s) => {
        if (s + 1 >= 120) stopRecording();
        return s + 1;
      }), 1000);
    } catch {
      setError("Couldn't use your microphone. Allow microphone access, or upload a recording instead.");
    }
  }

  function stopRecording() {
    recorder.current?.state === "recording" && recorder.current.stop();
    if (timer.current) clearInterval(timer.current);
    setRecording(false);
  }

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      const ext = file.type.includes("webm") ? "webm" : file.type.includes("mp4") ? "m4a" : file.type.includes("mpeg") ? "mp3" : "wav";
      form.append("file", file, (file as File).name || `voice.${ext}`);
      form.append("name", name.trim());
      form.append("language", "en");
      const token = await sessionToken();
      const res = await fetch("/api/settings/voices/clone", {
        method: "POST", body: form, headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't clone the voice. Try again.");
      await mutate();
      toast("Your voice is ready", "success");
      onCloned(body as Voice);
      setOpen(false);
      setFile(null);
      setName("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(v: Voice) {
    if (!window.confirm(`Delete the voice "${v.name}"? Agents using it will need a new voice.`)) return;
    try {
      await del(`/api/settings/voices/mine/${encodeURIComponent(v.id)}`);
      await mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  const full = (data?.voices.length ?? 0) >= (data?.limit ?? 5);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
        className="inline-flex items-center justify-center gap-2 rounded-xl border border-zinc-200 px-3 text-sm font-medium text-zinc-600 transition hover:border-brand-400 hover:text-brand-600">
        <Mic className="h-4 w-4" /><span className="hidden lg:inline">Clone your voice</span>
      </button>
      <Modal open={open} onClose={() => !busy && setOpen(false)} title="Clone your voice" wide>
        <div className="space-y-4">
          <p className="text-sm text-zinc-600">
            Record about a minute of yourself talking, and your agent can call in your voice. Only your account can use it.
          </p>
          {!!data?.voices.length && (
            <div className="rounded-xl border border-zinc-200">
              {data.voices.map((v) => (
                <div key={v.id} className="flex items-center justify-between border-b border-zinc-100 px-3 py-2 last:border-0">
                  <span className="text-sm text-zinc-800">{v.name}</span>
                  <button type="button" aria-label={`Delete ${v.name}`} onClick={() => void remove(v)}
                    className="rounded-lg p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-red-600">
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
          {full ? (
            <Notice>You have {data?.limit} cloned voices, the most an account can have. Delete one to add another.</Notice>
          ) : (
            <>
              <Field label="Voice name">
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Maxwell" maxLength={100} />
              </Field>
              <div className="rounded-xl bg-zinc-50 p-4">
                <div className="mb-2 text-xs font-medium text-zinc-600">Read this out loud, in a quiet room:</div>
                <p className="text-sm leading-relaxed text-zinc-800">{SCRIPT}</p>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                {recording ? (
                  <Button variant="primary" onClick={stopRecording}><Square className="h-4 w-4" /> Stop ({seconds}s)</Button>
                ) : (
                  <Button onClick={() => void startRecording()}><Mic className="h-4 w-4" /> {file ? "Record again" : "Record"}</Button>
                )}
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-xl border border-zinc-200 px-3 py-2 text-sm text-zinc-700 hover:bg-zinc-50">
                  <Upload className="h-4 w-4" /> Upload a recording
                  <input type="file" accept="audio/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) setFile(f); }} />
                </label>
                {file && !recording && <span className="text-xs text-zinc-500">Recording ready</span>}
              </div>
              {error && <Notice tone="red">{error}</Notice>}
              <div className="flex justify-end gap-2">
                <Button onClick={() => setOpen(false)} disabled={busy}>Cancel</Button>
                <Button variant="primary" loading={busy} disabled={!file || !name.trim() || recording} onClick={() => void submit()}>
                  Create my voice
                </Button>
              </div>
            </>
          )}
        </div>
      </Modal>
    </>
  );
}
