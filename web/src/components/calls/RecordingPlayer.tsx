"use client";

import { Download } from "lucide-react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Card, CardHeader, Spinner } from "../ui";

interface Recording {
  status: "none" | "processing" | "ready";
  url: string | null;
}

/** Call audio. Links are short-lived, so SWR refreshes them; "processing" polls until the file lands. */
export function RecordingPlayer({ callId, live }: { callId: string; live: boolean }) {
  const { data } = useSWR<Recording>(`/api/calls/${callId}/recording`, fetcher, {
    refreshInterval: (r) => (r?.status === "processing" ? 5000 : r?.status === "ready" ? 10 * 60 * 1000 : 0),
    revalidateOnFocus: false,
  });
  if (!data || data.status === "none") return null;

  return (
    <Card>
      <CardHeader
        title="Recording"
        action={
          data.url ? (
            <a href={data.url} download className="inline-flex items-center gap-1 text-xs font-medium text-zinc-600 hover:text-zinc-900">
              <Download className="h-3.5 w-3.5" /> Download
            </a>
          ) : undefined
        }
      />
      <div className="p-5">
        {data.url ? (
          <audio controls preload="metadata" src={data.url} className="w-full">
            Your browser can&apos;t play this recording.
          </audio>
        ) : (
          <div className="flex items-center gap-2 text-sm text-zinc-500">
            <Spinner className="h-4 w-4" /> {live ? "Recording in progress…" : "Processing the recording…"}
          </div>
        )}
      </div>
    </Card>
  );
}
