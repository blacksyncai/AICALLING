"use client";

import { Clock, MapPin, MessageSquare, Phone, Search, Truck, Upload } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { Badge, Button, Card, EmptyState, Input, Spinner } from "@/components/ui";
import { fetcher } from "@/lib/api";
import { cn, formatPhone, timeAgo } from "@/lib/utils";
import { CHECK_KIND, STATUS, etaText, when, windowText, type Board, type LoadStatus } from "./types";

const FILTERS: { value: "open" | LoadStatus | "all"; label: string }[] = [
  { value: "open", label: "All open" },
  { value: "late", label: "Late" },
  { value: "at_risk", label: "At risk" },
  { value: "unresponsive", label: "Unresponsive" },
  { value: "active", label: "On time" },
  { value: "delivered", label: "Delivered" },
];

/** Track Desk → Board: every load, late first, with the last check-in and the next one. */
export function BoardTab({ onImport }: { onImport: () => void }) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["value"]>("open");
  const [q, setQ] = useState("");
  const { data, error } = useSWR<Board>(
    `/api/track-desk/loads?status=${filter}&q=${encodeURIComponent(q.trim())}`,
    fetcher,
    { refreshInterval: 30000, keepPreviousData: true },
  );
  const counts = data?.counts ?? {};
  const open = (counts.late ?? 0) + (counts.at_risk ?? 0) + (counts.unresponsive ?? 0) + (counts.active ?? 0);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => {
          const n = f.value === "open" ? open : f.value === "all" ? undefined : counts[f.value];
          return (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={cn(
                "rounded-full px-3 py-1.5 text-sm font-medium ring-1 ring-inset transition",
                filter === f.value ? "bg-zinc-900 text-white ring-zinc-900" : "bg-white text-zinc-700 ring-zinc-200 hover:bg-zinc-50",
              )}
            >
              {f.label}
              {n ? <span className="ml-1.5 opacity-70">{n}</span> : null}
            </button>
          );
        })}
        <div className="relative ml-auto w-full sm:w-64">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Load, driver or city" className="pl-9" />
        </div>
      </div>

      {error ? (
        <Card><EmptyState icon={<Truck className="h-5 w-5" />} title="Couldn't load the board" description={error.message} /></Card>
      ) : !data ? (
        <div className="flex justify-center py-16"><Spinner /></div>
      ) : data.items.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Truck className="h-5 w-5" />}
            title={filter === "open" && !q ? "No active loads" : "Nothing matches"}
            description={filter === "open" && !q ? "Import your loads and Track Desk starts the check calls on schedule." : "Try another filter or search."}
            action={filter === "open" && !q ? <Button variant="primary" onClick={onImport}><Upload className="h-4 w-4" /> Import loads</Button> : undefined}
          />
        </Card>
      ) : (
        <Card className="divide-y divide-zinc-100 overflow-hidden p-0">
          {data.items.map((l) => {
            const s = STATUS[l.status];
            return (
              <div key={l.id} className="flex flex-col gap-3 p-4 lg:flex-row lg:items-center">
                <Link href={`/track-desk/${l.id}`} className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold text-zinc-900">Load {l.load_id}</span>
                    <Badge tone={s.tone}><span className={cn("h-1.5 w-1.5 rounded-full", s.dot)} />{s.label}</Badge>
                    {l.round && <Badge tone="blue">Checking now</Badge>}
                    {l.do_not_call && <Badge>Opted out</Badge>}
                    {l.sms_only && <Badge><MessageSquare className="h-3 w-3" /> Text only</Badge>}
                  </div>
                  <div className="mt-1 text-sm text-zinc-600">
                    {l.pickup.city}, {l.pickup.state} → {l.delivery.city}, {l.delivery.state}
                    <span className="text-zinc-400"> · </span>
                    {l.driver_name || formatPhone(l.driver_phone)}
                  </div>
                  <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
                    <span className="inline-flex items-center gap-1"><MapPin className="h-3 w-3" />{l.last_location || "No check-in yet"}</span>
                    <span>ETA <span className="font-medium text-zinc-700">{etaText(l)}</span></span>
                    <span>Delivery {windowText(l.delivery)}</span>
                    {l.delay_reason && <span className="text-red-600">{l.delay_reason}</span>}
                  </div>
                </Link>
                <div className="flex shrink-0 items-center gap-4 text-xs text-zinc-500">
                  <div className="text-right">
                    <div>Last check {l.last_check_at ? timeAgo(l.last_check_at) : "—"}</div>
                    {l.next_check_at && (
                      <div className="inline-flex items-center gap-1"><Clock className="h-3 w-3" />{CHECK_KIND[l.next_check_kind] ?? "Next check"} {when(l.next_check_at)}</div>
                    )}
                  </div>
                  <a href={`tel:${l.driver_phone}`} aria-label={`Call ${l.driver_name || "the driver"}`}>
                    <Button size="sm"><Phone className="h-3.5 w-3.5" /> Call</Button>
                  </a>
                </div>
              </div>
            );
          })}
        </Card>
      )}
    </div>
  );
}
