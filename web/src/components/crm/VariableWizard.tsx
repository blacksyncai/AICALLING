"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { Button, Modal, Notice, Select, Spinner } from "@/components/ui";
import { fetcher, put } from "@/lib/api";

/**
 * Self-serve CRM field-mapping wizard: walks through the {{variables}} an agent's
 * script uses, shows how each maps to the connected CRM's fields with a real sample
 * contact, and previews the resolved opening line as spoken audio before saving.
 */
interface VarRow {
  name: string;
  built_in: boolean;
  mapped_to: string;
  auto: string | null;
  sample: string;
}
interface VariablesData {
  variables: VarRow[];
  fields: { key: string; label: string }[];
  sample_contact: string | null;
}

const STEPS = ["Match your fields", "Preview the opening line", "Save"] as const;

export function VariableWizard({
  open,
  onClose,
  providerKey,
  providerName,
  agentId,
  agentName,
  firstMessage,
  voiceId,
}: {
  open: boolean;
  onClose: () => void;
  providerKey: string;
  providerName: string;
  agentId: string;
  agentName: string;
  firstMessage: string;
  voiceId: string;
}) {
  const [step, setStep] = useState(0);
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const audio = useRef<HTMLAudioElement | null>(null);

  const { data, error: loadError, isLoading, mutate } = useSWR<VariablesData>(
    open ? `/api/integrations/crm/${providerKey}/variables?agent_id=${agentId}` : null,
    fetcher,
  );

  useEffect(() => {
    if (open) {
      setStep(0);
      setEdits({});
      setSaved(null);
      setError(null);
    }
    return () => {
      audio.current?.pause();
      audio.current = null;
      setPlaying(false);
    };
  }, [open]);

  const value = (r: VarRow) => (r.name in edits ? edits[r.name] : r.mapped_to);
  const fieldLabel = (key: string | null) =>
    data?.fields.find((f) => f.key === key)?.label ?? key ?? "";

  // The opening line with the sample contact's values substituted — the "hear it before
  // your contacts do" moment. Unmapped variables read as a neutral fallback.
  const previewLine = useMemo(() => {
    if (!data || !firstMessage) return "";
    let line = firstMessage;
    for (const r of data.variables) {
      const v = value(r);
      const effective = v === "-" ? null : v || r.auto;
      const sampleValue = effective ? (r.sample || "") : "";
      line = line.split(`{{${r.name}}}`).join(sampleValue || "");
    }
    // A leading "Hi there," reads better than a dangling comma when values are missing.
    return line.replace(/^(Hi|Hey|Hello)[^a-zA-Z0-9]*,?\s*/i, (m) => m);
  }, [data, edits, firstMessage]);

  async function playPreview() {
    if (!previewLine.trim()) return;
    setPlaying(true);
    setError(null);
    try {
      const res = await fetch("/api/settings/voices/preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ voice_id: voiceId, text: previewLine, speed: 1, language: "en" }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail ?? "Preview failed");
      const url = URL.createObjectURL(await res.blob());
      audio.current?.pause();
      const a = new Audio(url);
      audio.current = a;
      a.onended = () => setPlaying(false);
      await a.play();
    } catch (e) {
      setError((e as Error).message);
      setPlaying(false);
    }
  }

  async function save() {
    if (!data) return;
    setSaving(true);
    setSaved(null);
    try {
      const map = Object.fromEntries(data.variables.map((r) => [r.name, value(r)]));
      await put(`/api/integrations/crm/${providerKey}/variables`, { agent_id: agentId, map });
      setSaved("Saved — every call from this agent fills these in.");
      void mutate();
      setTimeout(onClose, 1400);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  const unmapped = (data?.variables ?? []).filter((r) => {
    const v = value(r);
    return !r.built_in && v !== "-" && !(v || r.auto);
  });

  return (
    <Modal open={open} onClose={onClose} title={`${agentName} · ${providerName} fields`} wide>
      <div className="flex items-center gap-2 px-1 pb-4">
        {STEPS.map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
                i < step ? "bg-brand-600 text-white" : i === step ? "bg-brand-100 text-brand-800 ring-1 ring-brand-600" : "bg-zinc-100 text-zinc-400"
              }`}
            >
              {i + 1}
            </span>
            <span className={`text-xs ${i === step ? "font-semibold text-zinc-900" : "text-zinc-500"}`}>{s}</span>
            {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-zinc-200" />}
          </div>
        ))}
      </div>

      {loadError ? (
        <Notice tone="red">{(loadError as Error).message}</Notice>
      ) : isLoading || !data ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : data.variables.length === 0 ? (
        <p className="py-8 text-center text-sm text-zinc-500">
          This agent&apos;s script doesn&apos;t use any variables yet — nothing to map.
        </p>
      ) : step === 0 ? (
        <div className="space-y-3">
          <p className="text-sm text-zinc-600">
            Your script uses <strong>{data.variables.length}</strong> variable{data.variables.length === 1 ? "" : "s"}.
            {data.sample_contact ? (
              <> Examples below are from <strong>{data.sample_contact}</strong>, a real contact from your {providerName}.</>
            ) : null}
          </p>
          {unmapped.length > 0 && (
            <Notice tone="amber">
              {unmapped.length} variable{unmapped.length === 1 ? "" : "s"} won&apos;t be filled from {providerName} —
              pick a field or the agent will skip {unmapped.length === 1 ? "it" : "them"} on calls.
            </Notice>
          )}
          <div className="divide-y divide-zinc-100 rounded-xl border border-zinc-200">
            {data.variables.map((r) => {
              const v = value(r);
              const effective = v === "-" ? null : v || r.auto;
              return (
                <div key={r.name} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <code className="rounded-md bg-brand-50 px-1.5 py-0.5 text-[13px] text-brand-800">{`{{${r.name}}}`}</code>
                  <span className="text-zinc-400">←</span>
                  <Select
                    value={v}
                    onChange={(e) => setEdits((x) => ({ ...x, [r.name]: e.target.value }))}
                    className="h-9 min-w-44 flex-1 text-sm"
                    aria-label={`Field for ${r.name}`}
                  >
                    <option value="">
                      {r.auto ? `Automatic · ${fieldLabel(r.auto)}` : r.built_in ? "Automatic · BlackSync contact" : "Not mapped — pick a field"}
                    </option>
                    {data.fields.map((f) => (
                      <option key={f.key} value={f.key}>{f.label}</option>
                    ))}
                    <option value="-">Don&apos;t fill from {providerName}</option>
                  </Select>
                  <span className="min-w-32 flex-1 truncate text-xs text-zinc-500">
                    {r.name in edits && edits[r.name] !== r.mapped_to ? (
                      <span className="text-zinc-400">Save to preview</span>
                    ) : r.sample ? (
                      <span className="text-zinc-800">e.g. {r.sample}</span>
                    ) : effective ? (
                      "— empty for this contact"
                    ) : r.built_in ? (
                      "From the contact"
                    ) : (
                      <span className="text-amber-700">Won&apos;t be filled</span>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
          <div className="flex justify-end pt-2">
            <Button variant="primary" onClick={() => setStep(1)}>Next: preview</Button>
          </div>
        </div>
      ) : step === 1 ? (
        <div className="space-y-4">
          <p className="text-sm text-zinc-600">
            Here&apos;s the agent&apos;s opening line with {data.sample_contact ? `${data.sample_contact}'s` : "a sample"} values.
            Hear it the way your contacts will:
          </p>
          <div className="rounded-xl bg-zinc-50 p-4 text-[15px] leading-relaxed text-zinc-800">
            {previewLine || <span className="text-zinc-400">This agent has no opening line yet.</span>}
          </div>
          {error && <Notice tone="red">{error}</Notice>}
          <div className="flex items-center justify-between">
            <Button variant="ghost" onClick={() => setStep(0)}>Back</Button>
            <div className="flex gap-2">
              {previewLine.trim() && (
                <Button variant="secondary" onClick={() => void playPreview()} disabled={playing}>
                  {playing ? "Playing…" : "▶ Hear it"}
                </Button>
              )}
              <Button variant="primary" onClick={() => setStep(2)}>Next: save</Button>
            </div>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-zinc-600">
            {unmapped.length === 0
              ? "Everything is mapped. Save it and every call from this agent will fill these in automatically."
              : `Saving with ${unmapped.length} unmapped variable${unmapped.length === 1 ? "" : "s"} — you can come back any time.`}
          </p>
          <ul className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 text-sm">
            {data.variables.map((r) => (
              <li key={r.name} className="flex items-center justify-between gap-3 px-4 py-2.5">
                <code className="rounded-md bg-zinc-100 px-1.5 py-0.5 text-[13px]">{`{{${r.name}}}`}</code>
                <span className="text-zinc-600">
                  {value(r) === "-" ? "Not filled" : fieldLabel(value(r) || r.auto) || (r.built_in ? "From the contact" : "Not mapped")}
                </span>
              </li>
            ))}
          </ul>
          {saved && <Notice tone="green">{saved}</Notice>}
          {error && <Notice tone="red">{error}</Notice>}
          <div className="flex items-center justify-between">
            <Button variant="ghost" onClick={() => setStep(1)}>Back</Button>
            <Button variant="primary" loading={saving} onClick={() => void save()}>Save mapping</Button>
          </div>
        </div>
      )}
    </Modal>
  );
}
