"use client";

import { ArrowLeft, Building2, LogIn } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import useSWR from "swr";
import { CreditsCard, LedgerCard, SettingsCard, TeamCard } from "@/components/admin/AccountCards";
import { LeadFinderCard } from "@/components/admin/LeadFinderCard";
import { PhoneNumbersCard } from "@/components/admin/PhoneNumbersCard";
import { AdminGuard, StatTile, fmt } from "@/components/admin/shared";
import { Badge, Button, Card, EmptyState, Spinner } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fetcher } from "@/lib/api";
import { switchOrg } from "@/lib/session";
import type { AdminOrgDetail } from "@/lib/types";
import { parseDate } from "@/lib/utils";

export default function AdminAccountPage() {
  return (
    <AdminGuard>
      <AccountDetail />
    </AdminGuard>
  );
}

function AccountDetail() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const [opening, setOpening] = useState(false);
  const { data: org, error, mutate } = useSWR<AdminOrgDetail>(id ? `/api/admin/orgs/${id}` : null, fetcher);

  const back = (
    <Link href="/admin" className="mb-4 inline-flex items-center gap-1 text-xs font-medium text-zinc-500 hover:text-zinc-900">
      <ArrowLeft className="h-3.5 w-3.5" /> All accounts
    </Link>
  );

  if (error) {
    return (
      <>
        {back}
        <Card>
          <EmptyState icon={<Building2 className="h-5 w-5" />} title="Couldn't load this account" description={error.message} />
        </Card>
      </>
    );
  }
  if (!org) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  const refresh = () => void mutate();
  const created = parseDate(org.created_at);
  const low = !org.unlimited_credits && org.credits_balance <= 10;

  const open = async () => {
    setOpening(true);
    try {
      await switchOrg(org.id);
    } catch (e) {
      toast((e as Error).message, "error");
      setOpening(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <div>
        {back}
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <h1 className="min-w-0 truncate text-2xl font-semibold tracking-tight text-zinc-900">{org.name}</h1>
              <Badge tone={org.status === "active" ? "green" : "red"}>{org.status}</Badge>
              {org.unlimited_credits && <Badge tone="violet">Unlimited</Badge>}
            </div>
            <p className="mt-1 text-sm text-zinc-500">
              {created ? `Created ${created.toLocaleDateString(undefined, { dateStyle: "medium" })}` : "Creation date unknown"} · {fmt(org.all_time.calls)} calls,{" "}
              {fmt(org.all_time.minutes)} min all time
            </p>
          </div>
          <Button variant="primary" onClick={open} loading={opening}>
            <LogIn className="h-4 w-4" /> Open account
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-5">
        <StatTile label="Credits balance" value={org.unlimited_credits ? "Unlimited" : fmt(org.credits_balance)} tone={low ? "amber" : undefined} sub={org.unlimited_credits ? `${fmt(org.credits_balance)} on ledger` : "minutes left"} />
        <StatTile label="Calls (30d)" value={fmt(org.usage_30d.calls)} />
        <StatTile label="Minutes (30d)" value={fmt(org.usage_30d.minutes)} />
        <StatTile label="Credits used (30d)" value={fmt(org.usage_30d.credits_used)} />
        <StatTile label="Agents / Campaigns / Contacts" value={`${fmt(org.agents)} / ${fmt(org.campaigns)} / ${fmt(org.contacts)}`} />
      </div>

      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex min-w-0 flex-col gap-6">
          <CreditsCard org={org} refresh={refresh} />
          <LedgerCard org={org} />
        </div>
        <div className="flex min-w-0 flex-col gap-6">
          <SettingsCard org={org} refresh={refresh} />
          <PhoneNumbersCard orgId={org.id} />
          <LeadFinderCard orgId={org.id} />
          <TeamCard org={org} refresh={refresh} />
        </div>
      </div>
    </div>
  );
}
