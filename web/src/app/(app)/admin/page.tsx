"use client";

import { BookOpen, Building2, CreditCard, Hash, LifeBuoy, Lock, Plus, Search, Settings, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { ClientCards } from "@/components/admin/ClientCards";
import { NewAccountModal } from "@/components/admin/NewAccountModal";
import { PlaybooksTab } from "@/components/admin/playbooks";
import { BillingAdminTab } from "@/components/admin/BillingAdminTab";
import { TelephonyTab } from "@/components/admin/TelephonyTab";
import { AdminGuard, Avatar, StatTile, fmt } from "@/components/admin/shared";
import { Badge, Button, Card, EmptyState, Input, PageHeader, Spinner, Tabs } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { AdminOrg, PlatformOverview } from "@/lib/types";
import { timeAgo } from "@/lib/utils";

type AdminUser = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  phone: string;
  is_superadmin: boolean;
  created_at: string | null;
  last_login_at: string | null;
  accounts: { org_id: string; org_name: string; role: string }[];
};

type Tab = "accounts" | "users" | "playbooks" | "numbers" | "billing";

export default function AdminPage() {
  return (
    <AdminGuard>
      <AdminPortal />
    </AdminGuard>
  );
}

function AdminPortal() {
  const [tab, setTab] = useState<Tab>("accounts");
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("tab") === "playbooks") setTab("playbooks");
  }, []);
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");
  const [q, setQ] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setQ(query.trim()), 300);
    return () => clearTimeout(t);
  }, [query]);

  const { data: overview, mutate: mutateOverview } = useSWR<PlatformOverview>("/api/admin/overview", fetcher, { refreshInterval: 30000 });
  const { data: orgs, error: orgsError, mutate: mutateOrgs } = useSWR<{ orgs: AdminOrg[] }>(`/api/admin/orgs?q=${encodeURIComponent(q)}`, fetcher, { keepPreviousData: true });

  return (
    <>
      <PageHeader
        title="Admin portal"
        description="Every BlackSync account, its usage and credits."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <Link href="/admin/support">
              <Button>
                <LifeBuoy className="h-4 w-4" /> Support
              </Button>
            </Link>
            <Link href="/settings">
              <Button>
                <Settings className="h-4 w-4" /> Platform settings
              </Button>
            </Link>
            <Button
              onClick={async () => {
                await post("/api/admin/lock");
                window.location.href = "/dashboard";
              }}
            >
              <Lock className="h-4 w-4" /> Lock
            </Button>
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus className="h-4 w-4" /> New account
            </Button>
          </div>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        <StatTile label="Accounts" value={overview ? fmt(overview.accounts) : "—"} />
        <StatTile label="Users" value={overview ? fmt(overview.users) : "—"} />
        <StatTile label="Calls (30d)" value={overview ? fmt(overview.calls_30d) : "—"} />
        <StatTile label="Talk minutes (30d)" value={overview ? fmt(overview.minutes_30d) : "—"} />
        <StatTile label="Credits used (30d)" value={overview ? fmt(overview.credits_used_30d) : "—"} />
        <StatTile label="Credits outstanding" value={overview ? fmt(overview.credits_outstanding) : "—"} />
      </div>

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="w-full overflow-x-auto sm:w-[36rem]">
          <Tabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              { value: "accounts", label: "Clients", icon: <Building2 className="h-3.5 w-3.5" /> },
              { value: "users", label: "Users", icon: <Users className="h-3.5 w-3.5" /> },
              { value: "playbooks", label: "Playbooks", icon: <BookOpen className="h-3.5 w-3.5" /> },
              { value: "numbers", label: "Numbers", icon: <Hash className="h-3.5 w-3.5" /> },
              { value: "billing", label: "Billing", icon: <CreditCard className="h-3.5 w-3.5" /> },
            ]}
          />
        </div>
        {tab === "accounts" && (
          <div className="relative w-full sm:w-72">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-400" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search accounts or owner email" className="pl-9" aria-label="Search accounts" />
          </div>
        )}
      </div>

      {tab === "accounts" ? (
        orgsError ? (
          <Card>
            <EmptyState icon={<Building2 className="h-5 w-5" />} title="Couldn't load accounts" description={orgsError.message} />
          </Card>
        ) : !orgs ? (
          <div className="flex justify-center py-16">
            <Spinner />
          </div>
        ) : orgs.orgs.length === 0 ? (
          <Card>
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title={q ? "No matching clients" : "No clients yet"}
              description={q ? `Nothing matches “${q}”.` : "Create the first client account to get started."}
              action={
                !q && (
                  <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
                    <Plus className="h-4 w-4" /> New client
                  </Button>
                )
              }
            />
          </Card>
        ) : (
          <ClientCards orgs={orgs.orgs} onChanged={() => void mutateOrgs()} />
        )
      ) : tab === "users" ? (
        <UsersTable />
      ) : tab === "numbers" ? (
        <TelephonyTab />
      ) : tab === "billing" ? (
        <BillingAdminTab />
      ) : (
        <PlaybooksTab />
      )}

      <NewAccountModal
        open={creating}
        onClose={() => setCreating(false)}
        onCreated={() => {
          mutateOrgs();
          mutateOverview();
        }}
      />
    </>
  );
}

function UsersTable() {
  const { data, error } = useSWR<{ users: AdminUser[] }>("/api/admin/users", fetcher);
  return (
    <Card className="min-w-0">
      {error ? (
        <EmptyState icon={<Users className="h-5 w-5" />} title="Couldn't load users" description={error.message} />
      ) : !data ? (
        <div className="flex justify-center py-16">
          <Spinner />
        </div>
      ) : data.users.length === 0 ? (
        <EmptyState icon={<Users className="h-5 w-5" />} title="No users yet" description="Users appear here once accounts are created." />
      ) : (
        <div className="relative overflow-x-auto">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b border-zinc-100 text-left text-xs text-zinc-500">
              <tr>
                <th className="px-5 py-3 font-medium">User</th>
                <th className="px-3 py-3 font-medium">Accounts</th>
                <th className="px-3 py-3 text-right font-medium">Last login</th>
                <th className="px-5 py-3 text-right font-medium">Joined</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {data.users.map((u) => {
                const name = `${u.first_name} ${u.last_name}`.trim();
                return (
                  <tr key={u.id} className="hover:bg-zinc-50">
                    <td className="max-w-[300px] px-5 py-3">
                      <div className="flex min-w-0 items-center gap-3">
                        <Avatar name={name || u.email} />
                        <span className="min-w-0">
                          <span className="flex min-w-0 items-center gap-1.5">
                            <span className="truncate font-medium text-zinc-900">{name || u.email}</span>
                            {u.is_superadmin && (
                              <Badge tone="brand" className="shrink-0">
                                <ShieldCheck className="h-3 w-3" /> Superadmin
                              </Badge>
                            )}
                          </span>
                          {name && <span className="block truncate text-xs text-zinc-500">{u.email}</span>}
                        </span>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      {u.accounts.length === 0 ? (
                        <span className="text-xs text-zinc-400">No accounts</span>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {u.accounts.map((a) => (
                            <Link
                              key={a.org_id}
                              href={`/admin/accounts/${a.org_id}`}
                              className="inline-flex max-w-[220px] items-center gap-1 rounded-md border border-zinc-200 bg-white px-2 py-0.5 text-xs hover:border-brand-300 hover:bg-brand-50"
                            >
                              <span className="truncate text-zinc-800">{a.org_name}</span>
                              <span className="shrink-0 text-zinc-500">· {a.role}</span>
                            </Link>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-3 py-3 text-right text-xs text-zinc-500">{u.last_login_at ? timeAgo(u.last_login_at) : "Never"}</td>
                    <td className="whitespace-nowrap px-5 py-3 text-right text-xs text-zinc-500">{timeAgo(u.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}


