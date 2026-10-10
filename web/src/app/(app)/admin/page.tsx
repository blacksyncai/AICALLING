"use client";

import { BookOpen, Building2, Lock, LogIn, Plus, Search, Settings, ShieldCheck, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { NewAccountModal } from "@/components/admin/NewAccountModal";
import { PlaybooksTab } from "@/components/admin/playbooks";
import { AdminGuard, Avatar, StatTile, fmt } from "@/components/admin/shared";
import { Badge, Button, Card, EmptyState, Input, PageHeader, Spinner, Tabs } from "@/components/ui";
import { useToast } from "@/components/toast";
import { fetcher, post } from "@/lib/api";
import { switchOrg } from "@/lib/session";
import type { AdminOrg, PlatformOverview } from "@/lib/types";
import { cn, timeAgo } from "@/lib/utils";

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

type Tab = "accounts" | "users" | "playbooks";

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
        <div className="w-full sm:w-96">
          <Tabs<Tab>
            value={tab}
            onChange={setTab}
            tabs={[
              { value: "accounts", label: "Accounts", icon: <Building2 className="h-3.5 w-3.5" /> },
              { value: "users", label: "Users", icon: <Users className="h-3.5 w-3.5" /> },
              { value: "playbooks", label: "Playbooks", icon: <BookOpen className="h-3.5 w-3.5" /> },
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
        <Card className="min-w-0">
          {orgsError ? (
            <EmptyState icon={<Building2 className="h-5 w-5" />} title="Couldn't load accounts" description={orgsError.message} />
          ) : !orgs ? (
            <div className="flex justify-center py-16">
              <Spinner />
            </div>
          ) : orgs.orgs.length === 0 ? (
            <EmptyState
              icon={<Building2 className="h-5 w-5" />}
              title={q ? "No matching accounts" : "No accounts yet"}
              description={q ? `Nothing matches “${q}”.` : "Create the first customer account to get started."}
              action={
                !q && (
                  <Button variant="primary" size="sm" onClick={() => setCreating(true)}>
                    <Plus className="h-4 w-4" /> New account
                  </Button>
                )
              }
            />
          ) : (
            <AccountsTable orgs={orgs.orgs} onChanged={() => void mutateOrgs()} />
          )}
        </Card>
      ) : tab === "users" ? (
        <UsersTable />
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

function AccountsTable({ orgs, onChanged }: { orgs: AdminOrg[]; onChanged: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [opening, setOpening] = useState<string | null>(null);

  const open = async (id: string) => {
    setOpening(id);
    try {
      await switchOrg(id);
    } catch (e) {
      toast((e as Error).message, "error");
      setOpening(null);
    }
  };

  return (
    <div className="relative overflow-x-auto">
      <table className="w-full min-w-[960px] text-sm">
        <thead className="border-b border-zinc-100 text-left text-xs text-zinc-500">
          <tr>
            <th className="px-5 py-3 font-medium">Account</th>
            <th className="px-3 py-3 font-medium">Status</th>
            <th className="px-3 py-3 text-right font-medium">Calling credits</th>
            <th className="px-3 py-3 text-right font-medium">Lookup credits</th>
            <th className="px-3 py-3 text-right font-medium">Calls 30d</th>
            <th className="px-3 py-3 text-right font-medium">Minutes 30d</th>
            <th className="px-3 py-3 text-right font-medium">Members</th>
            <th className="px-3 py-3 text-right font-medium">Contacts</th>
            <th className="px-3 py-3 text-right font-medium">Created</th>
            <th className="px-5 py-3">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100">
          {orgs.map((o) => {
            const low = !o.unlimited_credits && o.credits_balance <= 10;
            return (
              <tr key={o.id} className="cursor-pointer hover:bg-zinc-50" onClick={() => router.push(`/admin/accounts/${o.id}`)}>
                <td className="max-w-[280px] px-5 py-3">
                  <Link href={`/admin/accounts/${o.id}`} className="flex min-w-0 items-center gap-3" onClick={(e) => e.stopPropagation()}>
                    <Avatar name={o.name} />
                    <span className="min-w-0">
                      <span className="block truncate font-medium text-zinc-900">{o.name}</span>
                      <span className="block truncate text-xs text-zinc-500">{o.owner?.email ?? "No owner"}</span>
                    </span>
                  </Link>
                </td>
                <td className="px-3 py-3">
                  <Badge tone={o.status === "active" ? "green" : "red"}>{o.status}</Badge>
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">
                  {o.unlimited_credits ? (
                    <Badge tone="violet">Unlimited</Badge>
                  ) : (
                    <span className={cn("font-medium", low ? "text-amber-700" : "text-zinc-900")}>{fmt(o.credits_balance)}</span>
                  )}
                </td>
                <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums" onClick={(e) => e.stopPropagation()}>
                  <LookupCreditsCell org={o} onChanged={onChanged} />
                </td>
                <td className="px-3 py-3 text-right tabular-nums text-zinc-600">{fmt(o.usage_30d.calls)}</td>
                <td className="px-3 py-3 text-right tabular-nums text-zinc-600">{fmt(o.usage_30d.minutes)}</td>
                <td className="px-3 py-3 text-right tabular-nums text-zinc-600">{fmt(o.members)}</td>
                <td className="px-3 py-3 text-right tabular-nums text-zinc-600">{fmt(o.contacts)}</td>
                <td className="whitespace-nowrap px-3 py-3 text-right text-xs text-zinc-500">{timeAgo(o.created_at)}</td>
                <td className="px-5 py-3 text-right">
                  <Button
                    size="sm"
                    loading={opening === o.id}
                    onClick={(e) => {
                      e.stopPropagation();
                      open(o.id);
                    }}
                  >
                    <LogIn className="h-3.5 w-3.5" /> Open
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
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


/** Lookup-credit balance with a quick "+" to add more (separate from calling credits). */
function LookupCreditsCell({ org, onChanged }: { org: AdminOrg; onChanged: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  if (org.lead_credits_unlimited) return <Badge tone="violet">Unlimited</Badge>;
  const credits = org.lead_credits ?? 0;
  async function add() {
    const raw = window.prompt(`Add lookup credits to ${org.name}`, "100");
    const n = Number(raw);
    if (!raw) return;
    if (!Number.isInteger(n) || n <= 0) return toast("Enter a whole number of credits.", "error");
    setBusy(true);
    try {
      const r = await post<{ credits: number }>(`/api/admin/orgs/${org.id}/lead-credits`, { amount: n, note: "Added from accounts list" });
      toast(`${org.name}: ${r.credits.toLocaleString()} lookup credits`);
      onChanged();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={cn("font-medium", credits <= 0 ? "text-amber-700" : "text-zinc-900")}>{fmt(credits)}</span>
      <button
        onClick={add}
        disabled={busy}
        className="rounded-md border border-zinc-200 px-1.5 text-xs font-medium text-zinc-600 hover:bg-zinc-100 disabled:opacity-50"
        aria-label={`Add lookup credits to ${org.name}`}
        title="Add lookup credits"
      >
        +
      </button>
    </span>
  );
}
