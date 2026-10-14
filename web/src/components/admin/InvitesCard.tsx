"use client";

import { Check, Plus, Send, UserPlus, X } from "lucide-react";
import {
  useDeferredValue,
  useEffect,
  useState,
  type ClipboardEvent,
} from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import {
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  Spinner,
  Textarea,
} from "@/components/ui";
import { fetcher, post } from "@/lib/api";

interface Invite {
  id: string;
  email: string;
  first_name: string;
  inviter: string;
  sent_at: string | null;
  send_count: number;
  joined_at: string | null;
}
interface Invites {
  default_inviter: string;
  items: Invite[];
}
interface Result {
  sent: string[];
  skipped: { email: string; reason: string }[];
  failed: string[];
  invalid: string[];
}
type Person = { first_name: string; email: string };

const EMAIL = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const day = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
      })
    : "—";

/** "Jordan Lee, jordan@x.com" / "jordan@x.com" / tab-separated → people. */
function parseLines(text: string): Person[] {
  return text
    .split(/\r?\n/)
    .map((line) => {
      const email = line.match(/[^\s,;<>]+@[^\s,;<>]+\.[^\s,;<>]+/)?.[0] ?? "";
      const name =
        line
          .replace(email, "")
          .replace(/[<>,;\t]/g, " ")
          .trim()
          .split(/\s+/)[0] ?? "";
      return { first_name: name, email };
    })
    .filter((p) => p.email);
}

/** Admin → Emails → Invite people: a personal "X invited you to try BlackSync" email for people without an account. */
export function InvitesCard({ emailEnabled }: { emailEnabled: boolean }) {
  const toast = useToast();
  const { data, mutate } = useSWR<Invites>(
    "/api/admin/emails/invites",
    fetcher,
  );
  const [inviter, setInviter] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [people, setPeople] = useState<Person[]>([
    { first_name: "", email: "" },
  ]);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    if (data && inviter === null) setInviter(data.default_inviter);
  }, [data, inviter]);

  const ready = people.filter((p) => EMAIL.test(p.email.trim()));
  const sample = ready[0] ?? people[0];
  const q = useDeferredValue(
    new URLSearchParams({
      first_name: sample.first_name,
      email: sample.email,
      inviter: inviter ?? "",
      note,
    }).toString(),
  );
  const { data: preview } = useSWR<{ subject: string; html: string }>(
    `/api/admin/emails/invites/preview?${q}`,
    fetcher,
    {
      keepPreviousData: true,
    },
  );

  const update = (i: number, patch: Partial<Person>) =>
    setPeople((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p)));

  function onPaste(i: number, e: ClipboardEvent<HTMLInputElement>) {
    const text = e.clipboardData.getData("text");
    if (!/\n/.test(text.trim())) return; // a single address pastes normally
    const parsed = parseLines(text);
    if (!parsed.length) return;
    e.preventDefault();
    setPeople((ps) =>
      [...ps.slice(0, i), ...parsed, ...ps.slice(i + 1)].filter(
        (p, j, all) => p.email || all.length === 1,
      ),
    );
  }

  async function send(list: Person[], resend = false) {
    setSending(true);
    try {
      const r = await post<Result>("/api/admin/emails/invites", {
        people: list,
        inviter: inviter ?? "",
        note,
        resend,
      });
      const parts = [`Sent ${r.sent.length}`];
      if (r.skipped.length)
        parts.push(
          `skipped ${r.skipped.length} (${[...new Set(r.skipped.map((s) => s.reason))].join(", ")})`,
        );
      if (r.invalid.length) parts.push(`${r.invalid.length} invalid`);
      if (r.failed.length) parts.push(`${r.failed.length} failed`);
      toast(
        parts.join(" · "),
        r.failed.length || (!r.sent.length && !resend) ? "error" : "success",
      );
      if (!resend) setPeople([{ first_name: "", email: "" }]);
      void mutate();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setSending(false);
    }
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-brand-600" /> Invite people
          </span>
        }
        description="Email someone a personal invite to try BlackSync. Their button opens sign-up with their email filled in."
      />
      <div className="grid gap-5 p-5 xl:grid-cols-[minmax(0,1fr)_440px]">
        <div className="space-y-4">
          <Field
            label="From"
            hint="Shown as “… invited you to test out BlackSync AI.”"
          >
            <Input
              value={inviter ?? ""}
              onChange={(e) => setInviter(e.target.value)}
              placeholder="Your name"
              maxLength={100}
            />
          </Field>
          <div>
            <span className="mb-1.5 block text-xs font-medium text-zinc-700">
              People
            </span>
            <div className="space-y-2">
              {people.map((p, i) => (
                <div key={i} className="flex items-center gap-2">
                  <div className="w-28 shrink-0 sm:w-40">
                    <Input
                      value={p.first_name}
                      onChange={(e) =>
                        update(i, { first_name: e.target.value })
                      }
                      placeholder="First name"
                      aria-label={`First name ${i + 1}`}
                    />
                  </div>
                  <div className="min-w-0 flex-1">
                    <Input
                      type="email"
                      value={p.email}
                      onChange={(e) => update(i, { email: e.target.value })}
                      onPaste={(e) => onPaste(i, e)}
                      placeholder="name@company.com"
                      aria-label={`Email ${i + 1}`}
                    />
                  </div>
                  {people.length > 1 && (
                    <button
                      type="button"
                      aria-label={`Remove ${p.email || "person"}`}
                      onClick={() =>
                        setPeople((ps) => ps.filter((_, j) => j !== i))
                      }
                      className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-3">
              <Button
                size="sm"
                variant="ghost"
                onClick={() =>
                  setPeople((ps) => [...ps, { first_name: "", email: "" }])
                }
              >
                <Plus className="h-4 w-4" /> Add person
              </Button>
              <span className="text-xs text-zinc-500">
                Tip: paste a list (one “Name, email” per line) into an email
                box.
              </span>
            </div>
          </div>
          <Field
            label="Personal note (optional)"
            hint="Shown as a quote from you under the intro."
          >
            <Textarea
              rows={3}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={1000}
              placeholder="Would love your feedback on this!"
            />
          </Field>
          <Button
            variant="primary"
            loading={sending}
            disabled={!ready.length || !emailEnabled}
            onClick={() => void send(ready)}
          >
            <Send className="h-4 w-4" />{" "}
            {ready.length > 1 ? `Send ${ready.length} invites` : "Send invite"}
          </Button>

          {data && data.items.length > 0 && (
            <div className="pt-2">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                Sent invites
              </div>
              <div className="max-h-72 divide-y divide-zinc-100 overflow-auto rounded-xl ring-1 ring-zinc-200/80">
                {data.items.map((inv) => (
                  <div
                    key={inv.id}
                    className="flex items-center gap-3 px-3 py-2 text-sm"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-medium text-zinc-900">
                        {inv.first_name || inv.email}
                      </div>
                      <div className="truncate text-xs text-zinc-500">
                        {inv.first_name ? `${inv.email} · ` : ""}sent{" "}
                        {day(inv.sent_at)}
                        {inv.send_count > 1 ? ` (${inv.send_count}×)` : ""}
                      </div>
                    </div>
                    {inv.joined_at ? (
                      <span className="inline-flex shrink-0 items-center gap-1 text-xs text-emerald-700">
                        <Check className="h-3.5 w-3.5" /> Joined{" "}
                        {day(inv.joined_at)}
                      </span>
                    ) : (
                      <button
                        type="button"
                        disabled={sending || !emailEnabled}
                        onClick={() =>
                          void send(
                            [{ first_name: inv.first_name, email: inv.email }],
                            true,
                          )
                        }
                        className="shrink-0 text-xs font-medium text-brand-700 hover:underline disabled:opacity-50"
                      >
                        Resend
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        <div className="overflow-hidden rounded-xl ring-1 ring-zinc-200/80 xl:self-start">
          <div className="border-b border-zinc-100 px-4 py-2.5">
            <div className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
              Preview
            </div>
            <div className="mt-0.5 truncate text-sm font-semibold text-zinc-900">
              {preview?.subject ?? "…"}
            </div>
          </div>
          {preview ? (
            <iframe
              title="Invite preview"
              srcDoc={preview.html}
              sandbox=""
              className="h-[560px] w-full bg-[#f4f1ed]"
            />
          ) : (
            <div className="flex h-[560px] items-center justify-center">
              <Spinner />
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
