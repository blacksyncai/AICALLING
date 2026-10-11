"use client";

import { CheckCircle2, CircleAlert } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { Badge, Card, CardHeader, Field, Input, Notice, Spinner, Toggle } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fetcher, patch } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

interface Telephony {
  twilio_ready: boolean;
  recordings_ready: boolean;
  trunk_sid: string;
  trunk_error: string;
  owned: { sid: string; number: string; friendly: string; on_trunk: boolean; org_id: string | null; org_name: string | null }[];
  owned_error: string;
  settings: { self_serve_numbers: boolean; max_numbers_per_org: number };
  open_requests: { id: string; area_code: string; org_id: string; org_name: string; created_at: string | null }[];
}

function Status({ ok, label, detail }: { ok: boolean; label: string; detail: string }) {
  return (
    <div className="flex items-start gap-2.5">
      {ok ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" /> : <CircleAlert className="mt-0.5 h-4 w-4 text-amber-500" />}
      <div>
        <div className="text-sm font-medium text-zinc-900">{label}</div>
        <div className="text-xs text-zinc-500">{detail}</div>
      </div>
    </div>
  );
}

/** Admin portal: phone number setup, policy, pending requests and every number in the Twilio account. */
export function TelephonyTab() {
  const toast = useToast();
  const { data, mutate } = useSWR<Telephony>("/api/admin/telephony", fetcher);
  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  async function save(body: Partial<Telephony["settings"]>) {
    try {
      await patch("/api/admin/telephony/settings", body);
      await mutate();
      toast("Saved");
    } catch (e) {
      toast((e as Error).message, "error");
    }
  }

  return (
    <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
      <div className="flex min-w-0 flex-col gap-6">
        <Card>
          <CardHeader title="Setup" />
          <div className="flex flex-col gap-4 p-5">
            <Status ok={data.twilio_ready} label="Twilio" detail={data.twilio_ready ? "Connected" : "Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN"} />
            {data.twilio_ready && (
              <Status ok={!!data.trunk_sid} label="SIP trunk" detail={data.trunk_sid ? `Numbers attach to ${data.trunk_sid}` : data.trunk_error || "Not found"} />
            )}
            <Status
              ok={data.recordings_ready}
              label="Call recordings"
              detail={data.recordings_ready ? "Saving to the recordings bucket" : "Set the RECORDINGS_S3_* variables to turn on recording"}
            />
          </div>
        </Card>
        <Card>
          <CardHeader title="Policy" />
          <div className="flex flex-col gap-4 p-5">
            <Toggle
              checked={data.settings.self_serve_numbers}
              onChange={(v) => void save({ self_serve_numbers: v })}
              label="Customers can buy numbers themselves"
              description="Off: customers send a request and you assign a number from their account page."
            />
            <Field label="Max numbers per account">
              <Input
                type="number"
                min={0}
                max={100}
                defaultValue={data.settings.max_numbers_per_org}
                onBlur={(e) => {
                  const n = Number(e.target.value);
                  if (Number.isInteger(n) && n !== data.settings.max_numbers_per_org) void save({ max_numbers_per_org: n });
                }}
                className="w-28"
              />
            </Field>
          </div>
        </Card>
        <Card>
          <CardHeader title="Open requests" description={data.open_requests.length ? `${data.open_requests.length} waiting` : undefined} />
          {data.open_requests.length === 0 ? (
            <p className="px-5 py-4 text-sm text-zinc-500">No pending number requests.</p>
          ) : (
            <ul className="divide-y divide-zinc-100">
              {data.open_requests.map((r) => (
                <li key={r.id} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                  <Link href={`/admin/accounts/${r.org_id}`} className="font-medium text-zinc-900 hover:underline">
                    {r.org_name}
                  </Link>
                  <span className="text-xs text-zinc-500">
                    {r.area_code ? `Area ${r.area_code}` : "Any area"} · {r.created_at ? timeAgo(r.created_at) : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <Card className="min-w-0">
        <CardHeader title="Numbers in Twilio" description="Assign or buy numbers from an account's page" />
        {!data.twilio_ready ? (
          <p className="px-5 py-4 text-sm text-zinc-500">Connect Twilio to see numbers.</p>
        ) : data.owned_error ? (
          <div className="p-5">
            <Notice tone="red">{data.owned_error}</Notice>
          </div>
        ) : (
          <ul className="divide-y divide-zinc-100">
            {data.owned.map((o) => (
              <li key={o.sid} className="flex flex-wrap items-center gap-2 px-5 py-2.5">
                <span className="font-mono text-sm tabular-nums">{o.number}</span>
                {o.on_trunk && <Badge tone="gray">on trunk</Badge>}
                <span className="ml-auto text-sm">
                  {o.org_id ? (
                    <Link href={`/admin/accounts/${o.org_id}`} className="text-zinc-700 hover:underline">
                      {o.org_name}
                    </Link>
                  ) : (
                    <span className="text-zinc-400">Unassigned</span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
