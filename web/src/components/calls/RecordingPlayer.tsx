"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { Card, CardHeader, Spinner } from "../ui";
import { DownloadRecording } from "./DownloadRecording";

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
data.url ? <DownloadRecording callId={callId} /> : undefined
        }
      />
      <div className="p-5">
        {/* preload "auto": until Safari has the whole OGG file it guesses the length from the first chunk (0:04 for a 7 s call). */}
        {data.url ? (
          <audio controls preload="auto" src={data.url} className="w-full">
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
