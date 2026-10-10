"use client";

import { History, RotateCcw } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { Button, Card, CardHeader, Modal, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { formatDateTime, timeAgo } from "@/lib/utils";
import { REVISIONS_URL, type Revision } from "./api";

export function RevisionHistory({ onRestore }: { onRestore: (id: string) => Promise<void> }) {
  const { data, error, isLoading } = useSWR<{ revisions: Revision[] }>(REVISIONS_URL, fetcher);
  const [showAll, setShowAll] = useState(false);
  const [confirm, setConfirm] = useState<Revision | null>(null);
  const [restoring, setRestoring] = useState(false);
  const revisions = data?.revisions ?? [];
  const visible = showAll ? revisions : revisions.slice(0, 5);

  return (
    <Card>
      <CardHeader title="History" description="A snapshot is saved before every change. Restore any earlier version." />
      <div className="px-5 py-3">
        {isLoading ? (
          <div className="flex justify-center py-4">
            <Spinner />
          </div>
        ) : error ? (
          <p className="py-2 text-xs text-zinc-500">History isn&apos;t available right now.</p>
        ) : revisions.length === 0 ? (
          <p className="flex items-center gap-2 py-2 text-xs text-zinc-500">
            <History className="h-4 w-4" /> No earlier versions yet.
          </p>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {visible.map((r) => (
              <li key={r.id} className="flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-zinc-800">{r.summary || "Knowledge updated"}</div>
                  <div className="text-xs text-zinc-500" title={formatDateTime(r.created_at)}>
                    {timeAgo(r.created_at)}
                  </div>
                </div>
                <Button size="sm" variant="ghost" onClick={() => setConfirm(r)}>
                  <RotateCcw className="h-3.5 w-3.5" /> Restore
                </Button>
              </li>
            ))}
          </ul>
        )}
        {revisions.length > 5 && (
          <button className="mt-1 text-xs font-medium text-zinc-500 hover:text-zinc-800" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show fewer" : `Show all ${revisions.length}`}
          </button>
        )}
      </div>

      <Modal open={!!confirm} onClose={() => !restoring && setConfirm(null)} title="Restore this version?">
        {confirm && (
          <>
            <p className="text-sm text-zinc-600">
              Your knowledge base will go back to how it was {timeAgo(confirm.created_at)} ({formatDateTime(confirm.created_at)}). Anything changed since
              then will be replaced.
            </p>
            <div className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button onClick={() => setConfirm(null)} disabled={restoring}>
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={restoring}
                onClick={async () => {
                  setRestoring(true);
                  try {
                    await onRestore(confirm.id);
                    setConfirm(null);
                  } finally {
                    setRestoring(false);
                  }
                }}
              >
                Restore version
              </Button>
            </div>
          </>
        )}
      </Modal>
    </Card>
  );
}
