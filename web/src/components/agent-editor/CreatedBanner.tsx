"use client";

import { ClipboardCheck, FileText, PartyPopper, PlayCircle, X } from "lucide-react";

export function CreatedBanner({
  onTest,
  onReview,
  onReadiness,
  onDismiss,
}: {
  onTest: () => void;
  onReview: () => void;
  onReadiness: () => void;
  onDismiss: () => void;
}) {
  const step = "inline-flex items-center gap-1.5 rounded-md border border-brand-200 bg-white px-2.5 py-1.5 text-xs font-medium text-brand-700 hover:bg-brand-50";
  return (
    <div role="status" className="relative rounded-xl border border-brand-200 bg-gradient-to-r from-brand-50 to-white p-4 pr-10">
      <button onClick={onDismiss} aria-label="Dismiss" className="absolute right-2 top-2 rounded-md p-1.5 text-brand-700/60 hover:bg-brand-100 hover:text-brand-700">
        <X className="h-4 w-4" />
      </button>
      <div className="flex items-start gap-3">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white">
          <PartyPopper className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-zinc-900">Your agent is ready</h2>
          <p className="mt-0.5 text-xs text-zinc-600">We wrote the script and loaded your business knowledge. Try a quick test call before you go live.</p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className={step} onClick={onTest}>
              <PlayCircle className="h-3.5 w-3.5" /> Test it now
            </button>
            <button className={step} onClick={onReview}>
              <FileText className="h-3.5 w-3.5" /> Review the script
            </button>
            <button className={step} onClick={onReadiness}>
              <ClipboardCheck className="h-3.5 w-3.5" /> Check launch readiness
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
