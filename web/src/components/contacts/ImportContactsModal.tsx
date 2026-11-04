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

/** Phone columns the server detects on its own (Phone, Phone 2, Mobile, Home, Work, Cell...). */
const PHONE_COL = /^(?:primary |owner |contact |best )?(phone|phone number|phone_number|phonenumber|mobile|mobile phone|cell|cell phone|cellphone|home|home phone|work|work phone|office phone|telephone|tel|landline|wireless|number)(?:[\s_#-]*\d{1,2})?(?: number)?$/i;
const COMPANION = /dnc|do[\s_-]*not[\s_-]*call|status|type|litigator/i;
const isPhoneCol = (h: string) => PHONE_COL.test(h.trim()) && !COMPANION.test(h);

/** Naive split — good enough for a preview; the server does the real parsing. */
function splitLine(line: string) {
  return line.split(",").map((c) => c.trim().replace(/^"|"$/g, ""));
}

export function ImportContactsModal({
  open,
  onClose,
  campaigns,
  onDone,
  sourceName,
  defaultTags = [],
}: {
  open: boolean;
  onClose: () => void;
  campaigns: Campaign[];
  onDone: () => void;
  sourceName?: string;
  defaultTags?: string[];
}) {
  const toast = useToast();
  const [csv, setCsv] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [campaignId, setCampaignId] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  // Phone columns in call order; null = the server's automatic detection.
  const [phoneCols, setPhoneCols] = useState<string[] | null>(null);
  const [updateExisting, setUpdateExisting] = useState(false);
  const [skipDnc, setSkipDnc] = useState(false);

  const lines = useMemo(() => csv.trim().split(/\r?\n/).filter((l) => l.trim()), [csv]);
  const rows = Math.max(0, lines.length - 1);
  const header = lines[0] ? splitLine(lines[0]) : [];
  const preview = lines.slice(1, 4).map(splitLine);
  const detected = header.filter(isPhoneCol);
  const chosen = phoneCols ?? detected;
  const hasPhone = chosen.length > 0;
  const togglePhoneCol = (h: string) =>
    setPhoneCols(header.filter((c) => (c === h ? !chosen.includes(h) : chosen.includes(c))));

  function readFile(f: File) {
    const reader = new FileReader();
    reader.onload = () => {
      setCsv(String(reader.result ?? ""));
      setFileName(f.name);
      setResult(null);
      setPhoneCols(null);
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
      const res = await post<ImportResult>("/api/contacts/import", {
        csv,
        campaign_id: campaignId || null,
        tags: [...new Set([...defaultTags, ...parseTags(tags)])],
        phone_columns: phoneCols && phoneCols.length ? phoneCols : null,
        update_existing: updateExisting,
        skip_dnc: skipDnc,
      });
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
    <Modal open={open} onClose={close} title={sourceName ? `Import ${sourceName} contacts` : "Import contacts from CSV"} wide>
      <div className="space-y-4">
        {result && (
          <Notice tone="green">
            <b>{result.created}</b> created · {result.updated ? <><b>{result.updated}</b> updated · </> : null}
            <b>{result.duplicates}</b> duplicate{result.duplicates === 1 ? "" : "s"} skipped (phone already in contacts) ·{" "}
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
            {!hasPhone && <p className="mt-1.5 text-xs text-amber-700">No phone column detected. Pick it below.</p>}
            <div className="mt-3">
              <div className="mb-1.5 text-xs font-medium text-zinc-700">Phone columns, in call order</div>
              <div className="flex flex-wrap gap-1.5">
                {header.filter(Boolean).map((h) => {
                  const on = chosen.includes(h);
                  return (
                    <button
                      key={h}
                      type="button"
                      aria-pressed={on}
                      onClick={() => togglePhoneCol(h)}
                      className={cn(
                        "rounded-full border px-2.5 py-1 text-xs transition-colors",
                        on ? "border-brand-600 bg-brand-600 text-white" : isPhoneCol(h) ? "border-zinc-300 bg-white text-zinc-700" : "border-zinc-200 bg-white text-zinc-400 hover:text-zinc-700",
                      )}
                    >
                      {on ? `${chosen.indexOf(h) + 1}. ` : ""}
                      {h}
                    </button>
                  );
                })}
              </div>
              <p className="mt-1.5 text-xs text-zinc-500">
                Every selected column is saved on the same contact.
              </p>
            </div>
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

        <label className="flex items-start gap-2 text-sm text-zinc-700">
          <input type="checkbox" className="mt-0.5 accent-brand-600" checked={skipDnc} onChange={(e) => setSkipDnc(e.target.checked)} />
          <span>
            Skip DNC numbers
            <span className="block text-xs text-zinc-500">Numbers your file flags as DNC are saved but never called. Off: they&apos;re called like any other number.</span>
          </span>
        </label>
        <label className="flex items-start gap-2 text-sm text-zinc-700">
          <input type="checkbox" className="mt-0.5 accent-brand-600" checked={updateExisting} onChange={(e) => setUpdateExisting(e.target.checked)} />
          <span>
            Update contacts that are already here
            <span className="block text-xs text-zinc-500">Adds missing numbers and columns to a contact that has one of the row&apos;s numbers, instead of skipping it.</span>
          </span>
        </label>

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
