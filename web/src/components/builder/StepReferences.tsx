"use client";

import { FileText, Trash2, Upload } from "lucide-react";
import { useRef, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Field, Input, Textarea } from "@/components/ui";
import { del, fetcher, post } from "@/lib/api";
import type { ReferenceDoc } from "@/lib/builder";
import { StepTitle } from "./parts";

const MAX_BYTES = 5 * 1024 * 1024;
const KIND = { pdf: "PDF", docx: "Word", txt: "Text", paste: "Pasted" } as const;

function toBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(",", 2)[1] ?? "");
    r.onerror = () => reject(new Error("We couldn't read that file."));
    r.readAsDataURL(file);
  });
}

/** Step 4 (optional): scripts or notes the customer already uses. Private to their account. */
export function StepReferences({ draftId }: { draftId: string }) {
  const toast = useToast();
  const url = `/api/agent-builder/drafts/${draftId}/references`;
  const { data, mutate } = useSWR<{ references: ReferenceDoc[] }>(url, fetcher);
  const refs = data?.references ?? [];
  const [busy, setBusy] = useState(false);
  const [pasteName, setPasteName] = useState("");
  const [pasteText, setPasteText] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function upload(file: File) {
    if (file.size > MAX_BYTES) return toast("That file is over 5 MB. Upload a smaller file or paste the relevant part.", "error");
    setBusy(true);
    try {
      await post(url, { filename: file.name, content_base64: await toBase64(file) });
      await mutate();
      toast(`Added ${file.name}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  async function addPasted() {
    setBusy(true);
    try {
      await post(url, { name: pasteName.trim(), text: pasteText });
      setPasteName("");
      setPasteText("");
      await mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove(id: string) {
    try {
      await del(`/api/agent-builder/references/${id}`);
      await mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  return (
    <div className="space-y-5">
      <StepTitle
        title="Have a script or reference material? (optional)"
        description="Upload a call script, objection list or notes you already use. Your agent follows their structure and wording where it fits. They stay private to your account."
      />

      {refs.length > 0 && (
        <ul className="divide-y divide-zinc-100 rounded-xl border border-zinc-200 bg-white">
          {refs.map((r) => (
            <li key={r.id} className="flex items-start gap-3 px-3 py-2.5">
              <FileText className="mt-0.5 h-4 w-4 shrink-0 text-zinc-400" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-zinc-900">{r.name}</div>
                <div className="text-xs text-zinc-500">
                  {KIND[r.kind] ?? r.kind} · {r.chars.toLocaleString()} characters
                </div>
                <p className="mt-1 line-clamp-2 text-xs text-zinc-500">{r.preview}</p>
              </div>
              <button onClick={() => remove(r.id)} className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-red-600" aria-label={`Remove ${r.name}`}>
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {refs.length < 5 && (
        <>
          <div className="rounded-xl border border-dashed border-zinc-300 p-4 text-center">
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
            />
            <Button variant="secondary" onClick={() => fileRef.current?.click()} loading={busy}>
              <Upload className="h-4 w-4" /> Upload PDF, Word or text file
            </Button>
            <p className="mt-2 text-xs text-zinc-500">Up to 5 MB. Scanned documents can&apos;t be read — paste the text instead.</p>
          </div>

          <div className="space-y-2">
            <span className="block text-xs font-medium text-zinc-700">Or paste it</span>
            <Field label="Name (optional)">
              <Input value={pasteName} onChange={(e) => setPasteName(e.target.value)} placeholder="e.g. Our current cold-call script" maxLength={255} />
            </Field>
            <Textarea rows={6} value={pasteText} onChange={(e) => setPasteText(e.target.value)} placeholder="Paste your script, talk track or notes…" aria-label="Pasted script" />
            <div className="flex justify-end">
              <Button size="sm" onClick={addPasted} disabled={pasteText.trim().length < 20} loading={busy}>
                Add
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
