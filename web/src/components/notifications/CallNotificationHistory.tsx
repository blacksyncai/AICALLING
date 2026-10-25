"use client";
import { TrackBadge, type Track } from "@/components/admin/EmailTracking";
import { Badge } from "@/components/ui";

type Delivery = Track & { provider_id: string; to: string; from: string | null };
export type AlertEvidence = {
  id: string; user: string; status: string; error: string;
  recipient?: string | null; sender?: string | null; sent_at?: string | null;
  attempts?: number; automatic?: boolean; delivery?: Delivery | null;
};
export type CopyEvidence = { status: string; to?: string | null; error?: string | null; attempted_at?: string | null; delivery?: Delivery | null };
const label = (status: string) => ({sent:"Accepted by email provider", queued:"Queued", sending:"Sending", retry:"Retry scheduled", failed:"Failed", cancelled:"Cancelled", unconfirmed:"Send unconfirmed", disabled:"Not configured", unknown:"No linked record"}[status] || status);

export function CallNotificationHistory({ alerts, internalCopy, onRetry }: {
  alerts: AlertEvidence[]; internalCopy?: CopyEvidence; onRetry: (id: string) => Promise<void>;
}) {
  return <div className="ml-0 mt-3 space-y-3 rounded-xl border border-zinc-200 bg-zinc-50/70 p-3 text-xs sm:ml-6">
    <div className="font-semibold text-zinc-800">Client notifications</div>
    {!alerts.length && <p className="text-zinc-500">No notification queued for this call.</p>}
    {alerts.map(a => <div key={a.id} className="space-y-1 border-l-2 border-zinc-200 pl-3">
      <div className="flex flex-wrap items-center gap-2"><span className="font-medium text-zinc-900 break-all">{a.recipient || a.delivery?.to || a.user}</span>
        <Badge tone={a.status === "failed" ? "red" : "gray"}>{label(a.status)}</Badge>
        {a.delivery && <TrackBadge t={a.delivery} />}
      </div>
      <p className="text-zinc-500 break-all">{a.sender || a.delivery?.from ? `From ${a.sender || a.delivery?.from}` : "Sender not recorded"} · {a.automatic ? "Automatic" : "Manual"}{a.attempts !== undefined ? ` · ${a.attempts} attempt${a.attempts === 1 ? "" : "s"}` : ""}</p>
      {a.sent_at && <p className="text-zinc-500">Sent {new Date(a.sent_at).toLocaleString()}</p>}
      {!a.delivery && <p className="text-zinc-500">Delivery events not linked. This does not confirm delivery or failure.</p>}
      {a.error && <p className="text-red-700">{a.error}</p>}
      {["failed","retry"].includes(a.status) && <button type="button" className="font-semibold text-brand-700 underline" onClick={() => void onRetry(a.id)}>Retry client email</button>}
      {a.delivery?.provider_id && <p className="break-all font-mono text-[10px] text-zinc-400">Receipt: {a.delivery.provider_id}</p>}
    </div>)}
    <div className="border-t border-zinc-200 pt-2">
      <div className="flex flex-wrap items-center gap-2"><span className="font-semibold text-zinc-800">BlackSync copy</span>
        {internalCopy?.delivery ? <TrackBadge t={internalCopy.delivery} /> : <Badge tone={internalCopy?.status === "unconfirmed" ? "amber" : "gray"}>{label(internalCopy?.status || "unknown")}</Badge>}
      </div>
      {internalCopy?.to && <p className="mt-1 break-all text-zinc-500">To {internalCopy.to}</p>}
      {internalCopy?.error && <p className="mt-1 text-amber-800">{internalCopy.error}</p>}
      <p className="mt-1 text-zinc-500">One shared copy per call, separate from each client’s delivery. Historical copies may have no linked record.</p>
    </div>
  </div>;
}
