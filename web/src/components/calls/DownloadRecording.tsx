"use client";

import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { useToast } from "@/components/toast";
import { fetcher } from "@/lib/api";
import { cn } from "@/lib/utils";

/** Downloads the call's audio as an MP3 file (browser recordings are converted the first time). */
export function DownloadRecording({ callId, className, label = "Download MP3" }: { callId: string; className?: string; label?: string }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function download() {
    if (busy) return;
    setBusy(true);
    try {
      const r = await fetcher<{ status: string; url: string | null }>(`/api/calls/${callId}/recording/download`);
      if (!r.url) return toast("The recording is still processing. Try again in a moment.", "error");
      // The link is served as an attachment, so the browser saves it and stays on this page.
      const a = document.createElement("a");
      a.href = r.url;
      a.rel = "noopener";
      document.body.appendChild(a);
      a.click();
      a.remove();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      onClick={() => void download()}
      disabled={busy}
      aria-label="Download recording as MP3"
      className={cn("inline-flex items-center gap-1 text-xs font-medium text-zinc-600 hover:text-zinc-900 disabled:opacity-60", className)}
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
      {label}
    </button>
  );
}
