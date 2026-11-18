"use client";

import { AlertTriangle, CheckCircle2, FileUp, Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useToast } from "@/components/toast";
import { Button, Card, CardHeader, Notice, Select } from "@/components/ui";
import { sessionToken } from "@/lib/clerk";
import { cn } from "@/lib/utils";

interface Preview {
  valid: number;
  errors: { row: number | null; load_id: string; reason: string }[];
  mapping: Record<string, string>;
  missing_columns: string[];
  fields: Record<string, { label: string; required: boolean }>;
  preview: Record<string, string | null>[];
}

interface Result {
  imported: number;
  updated: number;
  skipped: number;
  errors: Preview["errors"];
}

/** The header row of a CSV (handles quoted names). */
function headersOf(text: string): string[] {
  const line = text.replace(/^﻿/, "").split(/\r?\n/)[0] ?? "";
  const out: string[] = [];
  let cur = "";
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (ch === '"') {
      if (quoted && line[i + 1] === '"') { cur += '"'; i++; } else quoted = !quoted;
    } else if (ch === "," && !quoted) { out.push(cur.trim()); cur = ""; } else cur += ch;
  }
  out.push(cur.trim());
  return out.filter(Boolean);
}

async function upload(file: File, dryRun: boolean, mapping?: Record<string, string>) {
  const form = new FormData();
  form.append("file", file, file.name);
  form.append("dry_run", String(dryRun));
  if (mapping) form.append("mapping", JSON.stringify(mapping));
  const token = await sessionToken();
  const res = await fetch("/api/track-desk/loads/import", {
    method: "POST", body: form, headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't read that file.");
  return body;
}

const SAMPLE =
  "load_id,driver_name,driver_phone,pickup_city,pickup_state,pickup_window_start,pickup_window_end,delivery_city,delivery_state,delivery_window_start,delivery_window_end,shipper_name,notes\n" +
  "48213,Mike Ross,(312) 555-0101,Chicago,IL,2026-11-20 08:00,2026-11-20 12:00,Dallas,TX,2026-11-21 08:00,2026-11-21 14:00,Acme Foods,Reefer 34F\n";

/** Track Desk → Import: drop a CSV, check the column mapping and the rows, then import. */
export function ImportTab({ onDone }: { onDone: () => void }) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [drag, setDrag] = useState(false);

  async function pick(f: File | undefined) {
    if (!f) return;
    setFile(f);
    setResult(null);
    setHeaders(headersOf(await f.text()));
    setBusy(true);
    try {
      const p: Preview = await upload(f, true);
      setPreview(p);
      setMapping(p.mapping);
    } catch (e) {
      toast((e as Error).message, "error");
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function recheck(next: Record<string, string>) {
    setMapping(next);
    if (!file) return;
    setBusy(true);
    try {
      setPreview(await upload(file, true, next));
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function run() {
    if (!file) return;
    setBusy(true);
    try {
      const r: Result = await upload(file, false, mapping);
      setResult(r);
      toast(`${r.imported} loads imported${r.updated ? `, ${r.updated} updated` : ""}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  const sampleHref = `data:text/csv;charset=utf-8,${encodeURIComponent(SAMPLE)}`;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Import active loads"
          description="One row per load. Required: load_id, driver_phone, pickup city/state and window, delivery city/state and window. Times are read in your Track Desk time zone."
          action={<a href={sampleHref} download="track-desk-loads.csv" className="text-sm font-medium text-brand-700 hover:underline">Sample CSV</a>}
        />
        <div className="p-5">
          <div
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); pick(e.dataTransfer.files[0]); }}
            onClick={() => input.current?.click()}
            className={cn(
              "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition",
              drag ? "border-brand-500 bg-brand-50" : "border-zinc-200 hover:border-zinc-300 hover:bg-zinc-50",
            )}
          >
            <FileUp className="h-6 w-6 text-zinc-400" />
            <div className="text-sm font-medium text-zinc-800">{file ? file.name : "Drop a CSV here or click to choose"}</div>
            <div className="text-xs text-zinc-500">Re-importing a load_id updates that load instead of adding it twice.</div>
            <input ref={input} type="file" accept=".csv,text/csv" className="hidden" onChange={(e) => pick(e.target.files?.[0])} />
          </div>
        </div>
      </Card>

      {preview && (
        <Card>
          <CardHeader title="Columns" description="Check which column holds each field." />
          <div className="grid gap-3 p-5 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(preview.fields).map(([key, f]) => (
              <label key={key} className="text-sm">
                <span className="mb-1 block font-medium text-zinc-700">{f.label}{f.required && <span className="text-red-600"> *</span>}</span>
                <Select value={mapping[key] ?? ""} onChange={(e) => recheck({ ...mapping, [key]: e.target.value })}>
                  <option value="">— not in this file —</option>
                  {headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </Select>
              </label>
            ))}
          </div>
        </Card>
      )}

      {preview && (
        <Card>
          <CardHeader
            title={`${preview.valid} loads ready${preview.errors.length ? `, ${preview.errors.length} rows skipped` : ""}`}
            action={<Button variant="primary" loading={busy} disabled={!preview.valid} onClick={run}><Upload className="h-4 w-4" /> Import {preview.valid} loads</Button>}
          />
          <div className="space-y-4 p-5">
            {preview.missing_columns.length > 0 && (
              <Notice tone="red">Missing columns: {preview.missing_columns.join(", ")}. Pick them above.</Notice>
            )}
            {preview.errors.length > 0 && (
              <div className="rounded-lg border border-red-100 bg-red-50/50">
                {preview.errors.slice(0, 50).map((e, i) => (
                  <div key={i} className="flex gap-2 border-b border-red-100 px-3 py-2 text-sm last:border-0">
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                    <span className="text-zinc-800">{e.row ? `Row ${e.row}` : "Row"}{e.load_id ? ` (load ${e.load_id})` : ""}: {e.reason}</span>
                  </div>
                ))}
              </div>
            )}
            {preview.preview.length > 0 && (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs text-zinc-500">
                    <tr><th className="py-1 pr-4">Load</th><th className="pr-4">Driver</th><th className="pr-4">Pickup</th><th className="pr-4">Delivery</th></tr>
                  </thead>
                  <tbody className="divide-y divide-zinc-100">
                    {preview.preview.map((r) => (
                      <tr key={String(r.external_id)}>
                        <td className="py-1.5 pr-4 font-medium">{r.external_id}</td>
                        <td className="pr-4">{r.driver_name} <span className="text-zinc-500">{r.driver_phone}</span></td>
                        <td className="pr-4">{r.pickup_city}, {r.pickup_state} · {r.pickup_start ? new Date(r.pickup_start).toLocaleString() : ""}</td>
                        <td className="pr-4">{r.delivery_city}, {r.delivery_state} · {r.delivery_start ? new Date(r.delivery_start).toLocaleString() : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </Card>
      )}

      {result && (
        <Notice tone="green">
          <span className="inline-flex items-center gap-1.5"><CheckCircle2 className="h-4 w-4" /> {result.imported} imported, {result.updated} updated, {result.skipped} skipped.</span>
          <Button size="sm" className="ml-3" onClick={onDone}>View the board</Button>
          {result.errors.filter((e) => !e.row).map((e, i) => <div key={i} className="text-sm">Load {e.load_id}: {e.reason}</div>)}
        </Notice>
      )}
    </div>
  );
}
