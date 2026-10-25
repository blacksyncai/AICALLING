"use client";
import { CallNotificationHistory, type AlertEvidence, type CopyEvidence } from "./CallNotificationHistory";
import { BellRing, CheckCircle2, Mail, Send } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Modal,
  Notice,
  Spinner,
  Toggle,
} from "@/components/ui";
import { fetcher, post, put } from "@/lib/api";
import { canManage, useSession } from "@/lib/session";

type Member = { id: string; name: string; email: string };
type Preferences = {
  enabled: boolean;
  outcomes: string[];
  user_ids: string[];
  agent_ids: string[];
  crm_base_url: string;
  sender: string;
  email_ready: boolean;
  available_outcomes: Record<string, string>;
  members: Member[];
  agents: { id: string; name: string }[];
};
type Preview = {
  sender: string;
  recipients: Member[];
  items: {
    call_id: string;
    subject: string;
    summary: string;
    contact: string;
    crm_url: string;
    call_url: string;
  }[];
};
const flip = (values: string[], id: string) =>
  values.includes(id) ? values.filter((x) => x !== id) : [...values, id];

export function CallAlertSettings({ orgId }: { orgId?: string }) {
  const { session } = useSession();
  if (!orgId && !canManage(session))
    return (
      <Card className="space-y-4 p-5">
        <h2 className="font-semibold">Call alerts</h2>
        <p className="text-sm text-zinc-500">
          Your workspace administrator manages which important call outcomes
          trigger emails.
        </p>
        <MuteAlerts />
      </Card>
    );
  return <AlertPreferences orgId={orgId} />;
}
function MuteAlerts() {
  const [message, setMessage] = useState("");
  return (
    <>
      <Button
        onClick={async () => {
          try {
            await post("/api/call-alerts/mute");
            setMessage("Automatic call alerts stopped for your account.");
          } catch (e) {
            setMessage((e as Error).message);
          }
        }}
      >
        Stop my automatic alerts
      </Button>
      {message && (
        <p role="status" className="text-sm">
          {message}
        </p>
      )}
    </>
  );
}
function AlertPreferences({ orgId }: { orgId?: string }) {
  const base = orgId
    ? `/api/admin/orgs/${orgId}/call-alerts`
    : "/api/call-alerts";
  const { data, error, mutate } = useSWR<Preferences>(base, fetcher);
  const [draft, setDraft] = useState<Preferences>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  useEffect(() => {
    if (data) setDraft(data);
  }, [data]);
  if (error) return <Notice tone="red">{error.message}</Notice>;
  if (!draft)
    return (
      <Card className="p-6">
        <Spinner />
      </Card>
    );
  const change = (next: Partial<Preferences>) =>
    setDraft({ ...draft, ...next });
  return (
    <Card className="overflow-hidden">
      <div className="flex items-start gap-3 border-b border-zinc-100 bg-gradient-to-r from-brand-50 to-white p-5">
        <span className="rounded-xl bg-white p-2.5 text-brand-600 shadow-sm">
          <BellRing size={20} />
        </span>
        <div>
          <h2 className="font-semibold text-zinc-900">
            The calls worth knowing about
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            Important outcomes, sent to the right people. No email for every
            dial.
          </p>
        </div>
      </div>
      <div className="space-y-5 p-5">
        <Toggle
          checked={draft.enabled}
          onChange={(enabled) => change({ enabled })}
          label="Automatic call alerts"
          description="Only qualifying phone calls completed after activation are eligible. Browser tests and old calls are excluded."
        />
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Notify when</legend>
          <div className="flex flex-wrap gap-2">
            {Object.entries(draft.available_outcomes).map(([key, label]) => (
              <label
                key={key}
                className="flex cursor-pointer items-center gap-2 rounded-xl border border-zinc-200 px-3 py-2 text-sm"
              >
                <input
                  type="checkbox"
                  checked={draft.outcomes.includes(key)}
                  onChange={() =>
                    change({ outcomes: flip(draft.outcomes, key) })
                  }
                />
                {label}
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">
            Default notification recipients
          </legend>
          <div className="grid gap-2 sm:grid-cols-2">
            {draft.members.map((u) => (
              <label
                key={u.id}
                className="flex min-w-0 items-start gap-2 rounded-xl bg-zinc-50 p-3 text-sm"
              >
                <input
                  className="mt-1"
                  type="checkbox"
                  checked={draft.user_ids.includes(u.id)}
                  onChange={() =>
                    change({ user_ids: flip(draft.user_ids, u.id) })
                  }
                />
                <span className="min-w-0">
                  <span className="block font-medium">{u.name}</span>
                  <span className="block break-all text-xs text-zinc-500">
                    {u.email}
                  </span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Agents</legend>
          <p className="mb-2 text-xs text-zinc-500">
            Leave all unchecked to include every agent. Choose agents to
            customize alerts by workflow or industry.
          </p>
          <div className="flex flex-wrap gap-2">
            {draft.agents.map((a) => (
              <label
                key={a.id}
                className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm"
              >
                <input
                  type="checkbox"
                  checked={draft.agent_ids.includes(a.id)}
                  onChange={() =>
                    change({ agent_ids: flip(draft.agent_ids, a.id) })
                  }
                />
                {a.name}
              </label>
            ))}
          </div>
        </fieldset>
        <Field label="Follow Up Boss workspace address (optional)">
          <Input
            aria-label="Follow Up Boss workspace address"
            value={draft.crm_base_url}
            placeholder="https://yourteam.followupboss.com"
            onChange={(e) => change({ crm_base_url: e.target.value })}
          />
          <p className="mt-1 text-xs text-zinc-500">
            Enables direct contact links using the lead’s saved FUB ID. Unlinked
            calls include the BlackSync call link instead.
          </p>
        </Field>
        <p className="flex flex-wrap items-center gap-2 text-xs text-zinc-500">
          <Mail size={14} /> From{" "}
          <span className="break-all">{draft.sender}</span>
        </p>
        {!draft.email_ready && (
          <Notice tone="amber">
            Email delivery is not configured. Alerts cannot be sent until the
            email provider is connected.
          </Notice>
        )}
        <p className="text-xs text-zinc-500">
          The sender domain must be verified in Resend. Each call is sent at
          most once per recipient; delivery and retries are tracked.
        </p>
        {message && (
          <p role="status" className="text-sm text-zinc-700">
            {message}
          </p>
        )}
        <Button
          variant="primary"
          loading={busy}
          onClick={async () => {
            setBusy(true);
            setMessage("");
            try {
              await mutate(
                await put<Preferences>(base, {
                  enabled: draft.enabled,
                  outcomes: draft.outcomes,
                  user_ids: draft.user_ids,
                  agent_ids: draft.agent_ids,
                  crm_base_url: draft.crm_base_url,
                }),
                false,
              );
              setMessage("Call alert settings saved.");
            } catch (e) {
              setMessage((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Save alert settings
        </Button>
        {!orgId && (
          <div className="border-t pt-4">
            <MuteAlerts />
          </div>
        )}
      </div>
    </Card>
  );
}

export function AdminCallNotifications({ orgId }: { orgId: string }) {
  const base = `/api/admin/orgs/${orgId}/call-alerts`;
  const [page, setPage] = useState(1);
  const [calls, setCalls] = useState<string[]>([]);
  const [users, setUsers] = useState<string[]>([]);
  const [preview, setPreview] = useState<Preview>();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const { data: prefs } = useSWR<Preferences>(base, fetcher);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [recipientSearch, setRecipientSearch] = useState("");
  const [outcome, setOutcome] = useState("");
  const [browse, setBrowse] = useState(true);
  const recipientsEdited = useRef(false);
  useEffect(() => {
    if (prefs && !recipientsEdited.current) {
      setUsers(
        prefs.user_ids.filter((id) => prefs.members.some((u) => u.id === id)),
      );
    }
  }, [prefs]);
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(search.trim());
      setPage(1);
      setCalls([]);
    }, 250);
    return () => clearTimeout(timer);
  }, [search]);
  const showResults = !!query || browse;
  const historyUrl = `${base}/calls?page=${page}&q=${encodeURIComponent(query)}&outcome=${encodeURIComponent(outcome)}`;

  const { data, error, mutate } = useSWR<{
    items: {
      id: string;
      name: string;
      outcome: string;
      summary: string;
      started_at: string;
      alerts: AlertEvidence[];
      internal_copy?: CopyEvidence;
    }[];
  }>(showResults ? historyUrl : null, fetcher, { refreshInterval: 10000 });
  const selected = { call_ids: calls, user_ids: users };
  return (
    <Card className="overflow-hidden">
      <div className="flex items-start justify-between gap-3 border-b p-5">
        <div>
          <h2 className="flex items-center gap-2 font-semibold">
            <Send size={17} className="text-brand-600" /> Notification history
          </h2>
          <p className="mt-1 text-sm text-zinc-500">
            Client alerts, delivery results, and the BlackSync copy in one place.
            Select calls below to preview a new notification.
          </p>
        </div>
        <Badge tone="gray">Admin</Badge>
      </div>
      <div className="space-y-4 p-5">
        {error && <Notice tone="red">{error.message}</Notice>}
        <div className="grid items-end gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <Field label="Find a contact's calls">
            <Input
              type="search"
              aria-label="Search calls by contact name or phone"
              placeholder="Type a name or phone number…"
              value={search}
              maxLength={120}
              onChange={(e) => {
                setSearch(e.target.value);
                setCalls([]);
              }}
            />
          </Field>
          <Field label="Call result">
            <select
              aria-label="Filter call result"
              className="rounded-xl border border-zinc-200 bg-white px-3 py-2 text-sm"
              value={outcome}
              onChange={(e) => {
                setOutcome(e.target.value);
                setBrowse(true);
                setPage(1);
                setCalls([]);
              }}
            >
              <option value="">All results</option>
              {Object.entries(prefs?.available_outcomes || {}).map(
                ([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ),
              )}
              <option value="completed">Completed</option>
              <option value="voicemail">Voicemail</option>
              <option value="no_answer">No answer</option>
              <option value="failed">Failed</option>
            </select>
          </Field>
        </div>
        {!showResults && (
          <div className="rounded-xl border border-dashed border-zinc-200 bg-zinc-50 p-6 text-center">
            <p className="text-sm font-medium">
              Who would you like to look up?
            </p>
            <p className="mt-1 text-xs text-zinc-500">
              Search all completed phone calls in this account, including older
              calls.
            </p>
            <Button size="sm" className="mt-3" onClick={() => setBrowse(true)}>
              Browse recent calls instead
            </Button>
          </div>
        )}
        <fieldset>
          <legend className="mb-2 text-sm font-medium">Notify</legend>
          <p className="mb-2 text-xs text-zinc-500">
            Saved notification recipients are selected by default. Change the
            defaults in Call alert settings above.
          </p>
          <Input
            type="search"
            aria-label="Search notification recipients"
            placeholder="Find a recipient by name or email…"
            value={recipientSearch}
            onChange={(e) => setRecipientSearch(e.target.value)}
            className="mb-3"
          />
          <div className="flex flex-wrap gap-3">
            {prefs?.members
              .filter((u) =>
                `${u.name} ${u.email}`
                  .toLowerCase()
                  .includes(recipientSearch.trim().toLowerCase()),
              )
              .map((u) => (
                <label key={u.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={users.includes(u.id)}
                    onChange={() => {
                      recipientsEdited.current = true;
                      setUsers(flip(users, u.id));
                    }}
                  />
                  {u.name}
                </label>
              ))}
          </div>
        </fieldset>
        {showResults && !data && !error && <Spinner />}
        {data?.items.length === 0 && (
          <p className="text-sm text-zinc-500">
            No calls found. Try a different name, phone number, or call result.
          </p>
        )}
        <div
          className={
            showResults
              ? "divide-y rounded-xl border border-zinc-200"
              : "hidden"
          }
        >
          {data?.items.map((c) => (
            <div key={c.id} className="p-4">
              <label className="flex items-start gap-3">
                <input
                  type="checkbox"
                  className="mt-1"
                  aria-label={`Select call with ${c.name}`}
                  checked={calls.includes(c.id)}
                  disabled={!calls.includes(c.id) && calls.length >= 10}
                  onChange={() => setCalls(flip(calls, c.id))}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-semibold">
                    {c.name}{" "}
                    <span className="font-normal text-zinc-500">
                      · {c.outcome.replaceAll("_", " ")}
                    </span>
                  </span>
                  <span className="mt-1 block text-xs text-zinc-500">
                    {new Date(c.started_at).toLocaleString()}
                  </span>
                  <span className="mt-2 block text-sm text-zinc-600">
                    {c.summary || "No summary yet."}
                  </span>
                </span>
              </label>
              <CallNotificationHistory alerts={c.alerts} internalCopy={c.internal_copy} onRetry={async (id) => {
                try {
                  await post(`${base}/deliveries/${id}/retry`);
                  setMessage("Notification queued for retry.");
                  void mutate();
                } catch (e) { setMessage((e as Error).message); }
              }} />
            </div>
          ))}
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              disabled={!showResults || page === 1}
              onClick={() => {
                setPage(page - 1);
                setCalls([]);
              }}
            >
              Previous
            </Button>
            <span className="text-xs">Page {page}</span>
            <Button
              size="sm"
              disabled={!data || data.items.length < 30}
              onClick={() => {
                setPage(page + 1);
                setCalls([]);
              }}
            >
              Next
            </Button>
          </div>
          <Button
            variant="primary"
            loading={busy}
            disabled={
              !calls.length || !users.length || search.trim() !== query || !data
            }
            onClick={async () => {
              setBusy(true);
              setMessage("");
              try {
                setPreview(await post<Preview>(`${base}/preview`, selected));
              } catch (e) {
                setMessage((e as Error).message);
              } finally {
                setBusy(false);
              }
            }}
          >
            Preview {calls.length || ""} selected{" "}
            {calls.length === 1 ? "call" : "calls"}
          </Button>
        </div>
        {message && (
          <p role="status" className="text-sm">
            {message}
          </p>
        )}
      </div>
      <Modal
        open={!!preview}
        onClose={() => {
          if (!busy) setPreview(undefined);
        }}
        title="Review call notification"
        wide
      >
        {preview && (
          <div className="space-y-5">
            <p className="break-all text-xs text-zinc-500">
              From {preview.sender}
            </p>
            <div>
              <h3 className="text-sm font-semibold">Recipients</h3>
              {preview.recipients.map((u) => (
                <p key={u.id} className="break-all text-sm text-zinc-600">
                  {u.name} · {u.email}
                </p>
              ))}
            </div>
            {preview.items.map((c) => (
              <div
                key={c.call_id}
                className="space-y-2 rounded-xl bg-zinc-50 p-4"
              >
                <h3 className="font-semibold">{c.subject}</h3>
                <p className="whitespace-pre-wrap text-sm text-zinc-600">
                  {c.summary}
                </p>
                {c.crm_url ? (
                  <a
                    href={c.crm_url}
                    target="_blank"
                    rel="noreferrer"
                    className="block text-sm text-brand-600"
                  >
                    View in Follow Up Boss →
                  </a>
                ) : (
                  <p className="text-xs text-zinc-500">
                    No direct CRM link: configure the FUB address and link this
                    contact first.
                  </p>
                )}
                <Link
                  className="block text-sm text-brand-600"
                  href={c.call_url}
                >
                  Review call →
                </Link>
              </div>
            ))}
            <p className="text-xs text-zinc-500">
              Already queued or notified recipients will be skipped. This sends
              a summary only; it does not place calls or change CRM records.
            </p>
            <Button
              variant="primary"
              loading={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const r = await post<{
                    queued: number;
                    already_notified_or_queued: number;
                  }>(`${base}/notify`, {
                    call_ids: preview.items.map((c) => c.call_id),
                    user_ids: preview.recipients.map((u) => u.id),
                  });
                  setPreview(undefined);
                  setCalls([]);
                  setMessage(
                    `${r.queued} notifications queued. ${r.already_notified_or_queued} already notified or queued.`,
                  );
                  void mutate();
                } catch (e) {
                  setMessage((e as Error).message);
                  setPreview(undefined);
                } finally {
                  setBusy(false);
                }
              }}
            >
              <CheckCircle2 size={16} /> Confirm and notify
            </Button>
          </div>
        )}
      </Modal>
    </Card>
  );
}
