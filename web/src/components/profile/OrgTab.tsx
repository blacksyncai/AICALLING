"use client";

import { Building2 } from "lucide-react";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, Field, Input, Select, Spinner } from "@/components/ui";
import { fetcher, patch } from "@/lib/api";
import { useSession } from "@/lib/session";
import type { OrgDetail } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";
import { CopyButton, ROLE_TONE } from "./shared";

const DEFAULT_TZ = "America/New_York";
// Shown first; the full IANA list follows when the browser can provide it.
const COMMON_TZ = [
  "America/New_York", "America/Chicago", "America/Denver", "America/Phoenix", "America/Los_Angeles",
  "America/Anchorage", "Pacific/Honolulu", "America/Toronto", "America/Vancouver", "Europe/London",
  "Europe/Paris", "Europe/Berlin", "Asia/Dubai", "Asia/Kolkata", "Asia/Singapore", "Asia/Tokyo",
  "Australia/Sydney", "UTC",
];

function allTimeZones(): string[] {
  try {
    const list = (Intl as unknown as { supportedValuesOf?: (k: string) => string[] }).supportedValuesOf?.("timeZone");
    if (list?.length) return list;
  } catch {
    /* fall back to the common list */
  }
  return [];
}

export function OrgTab() {
  const { mutate: mutateSession } = useSession();
  const toast = useToast();
  const { data, error, mutate } = useSWR<OrgDetail>("/api/account/org", fetcher);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [tz, setTz] = useState(DEFAULT_TZ);
  const [tzBusy, setTzBusy] = useState(false);
  // Filled after mount so server and client render the same options.
  const [zones, setZones] = useState<string[]>([]);

  useEffect(() => {
    if (data) {
      setName(data.name);
      setTz(data.timezone || DEFAULT_TZ);
    }
  }, [data]);
  useEffect(() => setZones(allTimeZones()), []);

  if (error) return <Card><EmptyState icon={<Building2 className="h-5 w-5" />} title="Couldn't load your organization" description={error.message} /></Card>;
  if (!data)
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await patch("/api/account/org", { name: name.trim() });
      await Promise.all([mutate(), mutateSession()]);
      toast("Organization name updated");
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function saveTz(e: React.FormEvent) {
    e.preventDefault();
    setTzBusy(true);
    try {
      await patch("/api/account/org", { timezone: tz });
      await Promise.all([mutate(), mutateSession()]);
      toast("Time zone updated");
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setTzBusy(false);
    }
  }

  const current = data.timezone || DEFAULT_TZ;
  const rest = zones.filter((z) => !COMMON_TZ.includes(z));
  const options = [...COMMON_TZ, ...(COMMON_TZ.includes(current) || rest.includes(current) ? [] : [current])];

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title="Organization"
          description={data.can_manage ? "The company name your team sees across BlackSync." : "Only owners and admins can rename the organization."}
        />
        <form onSubmit={save} className="flex flex-col gap-3 p-5 sm:flex-row sm:items-end">
          <Field label="Company / organization name" className="min-w-0 flex-1">
            <Input value={name} onChange={(e) => setName(e.target.value)} disabled={!data.can_manage} required />
          </Field>
          {data.can_manage && (
            <Button variant="primary" loading={busy} disabled={!name.trim() || name.trim() === data.name}>
              Save
            </Button>
          )}
        </form>
        <form onSubmit={saveTz} className="flex flex-col gap-3 border-t border-zinc-100 p-5 sm:flex-row sm:items-end">
          <Field
            label="Time zone"
            hint="Used to decide which day a call happened on — the dashboard's activity map and the call-log day filter."
            className="min-w-0 flex-1"
          >
            <Select value={tz} onChange={(e) => setTz(e.target.value)} disabled={!data.can_manage}>
              <optgroup label="Common">
                {options.map((z) => (
                  <option key={z} value={z}>
                    {z.replace(/_/g, " ")}
                  </option>
                ))}
              </optgroup>
              {rest.length > 0 && (
                <optgroup label="All time zones">
                  {rest.map((z) => (
                    <option key={z} value={z}>
                      {z.replace(/_/g, " ")}
                    </option>
                  ))}
                </optgroup>
              )}
            </Select>
          </Field>
          {data.can_manage && (
            <Button variant="primary" loading={tzBusy} disabled={tz === current}>
              Save
            </Button>
          )}
        </form>
      </Card>

      <Card>
        <CardHeader title="Account details" />
        <dl className="divide-y divide-zinc-100 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
            <dt className="text-zinc-500">Account ID</dt>
            <dd className="flex min-w-0 items-center gap-2">
              <code className="truncate rounded bg-zinc-100 px-1.5 py-0.5 font-mono text-xs text-zinc-700">{data.id}</code>
              <CopyButton text={data.id} className="h-7 px-2" />
            </dd>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
            <dt className="text-zinc-500">Status</dt>
            <dd>
              <Badge tone={data.status === "active" ? "green" : "red"} className="capitalize">
                {data.status}
              </Badge>
            </dd>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
            <dt className="text-zinc-500">Your role</dt>
            <dd>
              <Badge tone={ROLE_TONE[data.role]} className="capitalize">
                {data.role}
              </Badge>
            </dd>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
            <dt className="text-zinc-500">Created</dt>
            <dd className="text-zinc-800">{formatDateTime(data.created_at)}</dd>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
            <dt className="text-zinc-500">Members</dt>
            <dd className="text-zinc-800">{data.members.length}</dd>
          </div>
        </dl>
      </Card>
    </div>
  );
}
