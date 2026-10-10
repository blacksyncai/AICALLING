"use client";

import { FileUp } from "lucide-react";
import { useMemo, useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Field, Input, Modal, Notice, Select, Textarea } from "@/components/ui";
import { post } from "@/lib/api";
import type { Campaign } from "@/lib/types";
import { cn } from "@/lib/utils";
import { type ImportResult, parseTags } from "./shared";

const SAMPLE_CSV = `name,phone,company,email,role,city
Jane Cooper,+14155550123,Acme Inc,jane@acme.com,Head of Sales,San Francisco
Marcus Lee,+14155550188,Globex,marcus@globex.com,Founder,Austin`;

/** Naive split — good enough for a preview; the server does the real parsing. */
function splitLine(line: string) {
  return line.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
}

export function ImportContactsModal({
  open,
  onClose,
  campaigns,
  onDone,
}: {
  open: boolean;
  onClose: () => void;
  campaigns: Campaign[];
  onDone: () => void;
}) {
  const toast = useToast();
  const [csv, setCsv] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [campaignId, setCampaignId] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);

  const lines = useMemo(() => csv.trim().split(/\r?\n/).filter((l) => l.trim()), [csv]);
  const rows = Math.max(0, lines.length - 1);
  const header = lines[0] ? splitLine(lines[0]) : [];
  const preview = lines.slice(1, 4).map(splitLine);
  const hasPhone = header.some((h) => /phone|mobile|number|tel/i.test(h));

  function readFile(f: File) {
    const reader = new FileReader();
    reader.onload = () => {
      setCsv(String(reader.result ?? ""));
      setFileName(f.name);
      setResult(null);
    };
    reader.onerror = () => toast("Couldn't read that file", "error");
    reader.readAsText(f);
  }

  function close() {
    setResult(null);
    onClose();
  }

  async function submit() {
    setBusy(true);
    try {
      const res = await post<ImportResult>("/api/contacts/import", { csv, campaign_id: campaignId || null, tags: parseTags(tags) });
      setResult(res);
      toast(`Imported ${res.created} contact${res.created === 1 ? "" : "s"}`);
      setCsv("");
      setFileName(null);
      onDone();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={close} title="Import contacts from CSV" wide>
      <div className="space-y-4">
        {result && (
          <Notice tone="green">
            <b>{result.created}</b> created · <b>{result.duplicates}</b> duplicate{result.duplicates === 1 ? "" : "s"} skipped (phone already in contacts) ·{" "}
            <b>{result.skipped}</b> skipped (missing or invalid phone)
          </Notice>
        )}
        <Notice tone="blue">
          Include a header row and a <b>phone</b> column. <b>name</b> (or first/last name), <b>company</b>, <b>email</b> and <b>role</b>/<b>title</b> are recognised;
          every other column becomes a custom field you can use in agent prompts, e.g. <code>{"{{city}}"}</code>.
        </Notice>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const f = e.dataTransfer.files?.[0];
            if (f) readFile(f);
          }}
          className={cn(
            "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-6 text-center transition-colors",
            dragging ? "border-brand-400 bg-brand-50" : "border-zinc-200 bg-zinc-50/60",
          )}
        >
          <FileUp className="h-5 w-5 text-zinc-400" />
          <p className="text-sm text-zinc-600">
            {fileName ? (
              <>
                Loaded <span className="font-medium text-zinc-900">{fileName}</span>
              </>
            ) : (
              "Drag a .csv file here"
            )}
          </p>
          <div className="flex flex-wrap justify-center gap-2">
            <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-zinc-200 bg-white px-3 py-1.5 text-xs font-medium hover:bg-zinc-50">
              Choose file
              <input
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) readFile(f);
                  e.target.value = "";
                }}
              />
            </label>
            <Button size="sm" variant="ghost" onClick={() => (setCsv(SAMPLE_CSV), setFileName(null))}>
              Use sample
            </Button>
          </div>
        </div>

        <Field label="…or paste CSV">
          <Textarea
            rows={5}
            value={csv}
            onChange={(e) => {
              setCsv(e.target.value);
              setFileName(null);
            }}
            placeholder={SAMPLE_CSV}
            className="font-mono text-xs"
          />
        </Field>

        {preview.length > 0 && (
          <div>
            <div className="mb-1.5 flex items-center justify-between text-xs">
              <span className="font-medium text-zinc-700">Preview</span>
              <span className="text-zinc-500">
                {rows} row{rows === 1 ? "" : "s"}
              </span>
            </div>
            <div className="overflow-x-auto rounded-lg border border-zinc-200">
              <table className="w-full text-xs">
                <thead className="bg-zinc-50 text-left text-zinc-500">
                  <tr>
                    {header.map((h, i) => (
                      <th key={i} className="whitespace-nowrap px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-zinc-100">
                  {preview.map((r, i) => (
                    <tr key={i}>
                      {header.map((_, j) => (
                        <td key={j} className="max-w-[180px] truncate whitespace-nowrap px-3 py-1.5 text-zinc-700">
                          {r[j] ?? ""}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {!hasPhone && <p className="mt-1.5 text-xs text-amber-700">No phone column detected in the header row.</p>}
          </div>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Add to campaign">
            <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
              <option value="">No campaign</option>
              {campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Tags" hint="Comma-separated, applied to every imported contact">
            <Input value={tags} onChange={(e) => setTags(e.target.value)} placeholder="webinar, q4" />
          </Field>
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button onClick={close}>{result ? "Done" : "Cancel"}</Button>
          <Button variant="primary" onClick={submit} loading={busy} disabled={rows < 1}>
            Import {rows > 0 ? rows : ""} contact{rows === 1 ? "" : "s"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
