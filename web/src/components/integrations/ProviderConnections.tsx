"use client";

import Link from "next/link";
import { FileUp, Info } from "lucide-react";
import { useState } from "react";
import { ImportContactsModal } from "@/components/contacts/ImportContactsModal";
import { Badge, Button, Card, Modal } from "@/components/ui";

const SOURCES = [
  { key: "vulcan7", name: "Vulcan7", description: "Import contacts from your Vulcan7 export.", requirements: "A Vulcan7 login alone does not enable account sync in BlackSync. Direct connection needs a verified API and the required account access. For now, export your contacts as CSV and import them here." },
  { key: "redx", name: "REDX", description: "Import contacts from your REDX export.", requirements: "A REDX login alone does not enable account sync in BlackSync. Direct connection needs a verified API and the required account access. For now, export your contacts as CSV and import them here." },
];
type Entry = typeof SOURCES[number];

export function ProviderConnections({ kind: _kind }: { kind: "lead_source" }) {
  const [details, setDetails] = useState<Entry | null>(null);
  const [importing, setImporting] = useState<Entry | null>(null);
  const [imported, setImported] = useState(false);
  const providers = SOURCES;
  return (
    <section aria-label="My lead sources" className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold">Your lead sources</h2>
        <p className="mt-1 text-sm text-zinc-500">Import contacts you already have. Direct account sync is not available for these providers yet.</p>
        {<p className="mt-1 text-xs text-zinc-500">Contact imports do not run property lookups or spend lookup credits.</p>}
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        {providers.map((p) => (
          <Card key={p.key} className="flex flex-col gap-3 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold">{p.name}</h3><Badge tone="gray">CSV available</Badge></div>
            <p className="text-sm text-zinc-500">{p.description}</p>
            <p className="text-xs text-zinc-500">Account sync unavailable</p>
            <div className="mt-auto flex flex-wrap gap-2">
              <Button onClick={() => setImporting(p)}><FileUp className="h-4 w-4" />Import CSV</Button>
              <Button variant="ghost" onClick={() => setDetails(p)} aria-label={`${p.name} connection requirements`}><Info className="h-4 w-4" />Setup details</Button>
            </div>
          </Card>
        ))}
      </div>
      {imported && <p className="text-sm text-emerald-700">Import completed. <Link className="underline" href="/contacts">View contacts</Link></p>}
      <Modal open={!!details} onClose={() => setDetails(null)} title={`${details?.name ?? "Provider"} connection`}>
        <p className="text-sm leading-relaxed text-zinc-600">{details?.requirements}</p>
        <p className="mt-3 text-xs text-zinc-500">No password or API key is collected until a supported connector can verify it.</p>
      </Modal>
      {importing && <ImportContactsModal key={importing.key} open onClose={() => setImporting(null)} campaigns={[]} sourceName={importing.name} defaultTags={[`source:${importing.key}`]} onDone={() => setImported(true)} />}
    </section>
  );
}
