"use client";
import { useState } from "react";
import { Columns3, Users, Tags, ArrowRight } from "lucide-react";
import { Button, Card, Field, Input, Textarea, Notice } from "@/components/ui";

export function FollowUpBossTools({
  onPrepare,
}: {
  onPrepare: (spec: Record<string, unknown>) => Promise<void>;
}) {
  const [action, setAction] = useState("");
  const [name, setName] = useState("");
  const [stages, setStages] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = async (spec: Record<string, unknown>) => {
    setBusy(true);
    setError("");
    try {
      await onPrepare(spec);
      setAction("");
      setName("");
      setStages("");
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Could not prepare this action.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="mb-5 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-brand-600">
            FOLLOW UP BOSS
          </p>
          <h3 className="mt-2 text-lg font-semibold">
            Choose what you want to manage
          </h3>
        </div>
        <Button
          loading={busy}
          onClick={() => void run({ action: "list_pipelines" })}
        >
          View deal boards <ArrowRight size={14} />
        </Button>
      </div>
      <div className="mt-3">
        <Button
          type="button"
          loading={busy}
          onClick={() => void run({ action: "list_sources" })}
        >
          View lead sources
        </Button>
        <p className="mt-2 text-xs text-zinc-500">
          A lead source identifies origin. Radar can assign a source label to a
          selected contact with no existing source, after review. This preserves
          original attribution and does not configure Lead Flow.
        </p>
      </div>
      <p className="mt-2 text-xs leading-6 text-zinc-500">
        The API calls a deal board a “pipeline.” You’ll find it under Deals /
        Deal Tracking in Follow Up Boss. A new board starts empty; routing
        contacts into deals is a separate workflow.
      </p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {[
          {
            key: "create_pipeline",
            title: "Deal board",
            icon: Columns3,
            copy: "Track opportunities across deal stages. This appears in Deals.",
          },
          {
            key: "create_pond",
            title: "Pond",
            icon: Users,
            copy: "Group contacts for a shared team queue. Useful as an automation destination.",
          },
          {
            key: "create_stage",
            title: "Person stage",
            icon: Tags,
            copy: "Describe where a contact is in their lifecycle, separately from deal stages.",
          },
        ].map((item) => (
          <button
            key={item.key}
            type="button"
            aria-pressed={action === item.key}
            disabled={busy}
            onClick={() => {
              setAction(item.key);
              setError("");
            }}
            className={`rounded-xl border p-4 text-left transition-colors ${action === item.key ? "border-brand-400 bg-brand-50" : "border-zinc-200 hover:bg-zinc-50"}`}
          >
            <item.icon size={18} className="text-brand-600" />
            <span className="mt-3 block text-sm font-semibold">
              Create {item.title.toLowerCase()}
            </span>
            <span className="mt-2 block text-xs leading-5 text-zinc-500">
              {item.copy}
            </span>
          </button>
        ))}
      </div>
      {action && (
        <form
          className="mt-5 space-y-4 border-t border-zinc-100 pt-5"
          onSubmit={(e) => {
            e.preventDefault();
            void run({
              action,
              name,
              ...(action === "create_pipeline"
                ? {
                    stages: stages
                      .split("\n")
                      .map((x) => x.trim())
                      .filter(Boolean)
                      .map((label) => ({ label, kind: "active" })),
                  }
                : {}),
            });
          }}
        >
          <Field
            label={
              action === "create_pipeline"
                ? "Deal board name"
                : action === "create_pond"
                  ? "Pond name"
                  : "Person stage name"
            }
          >
            <Input
              aria-label="Follow Up Boss resource name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              required
              autoFocus
            />
          </Field>
          {action === "create_pipeline" && (
            <Field label="Deal stages (one per line)">
              <Textarea
                aria-label="Follow Up Boss deal stages"
                value={stages}
                onChange={(e) => setStages(e.target.value)}
                rows={3}
                required
                placeholder={
                  "Verified by voicemail\nName confirmed by AI\nContact attempted by human"
                }
              />
              <p className="mt-1 text-xs text-zinc-500">
                These are open stages. Continue opens a preview; it does not
                create anything yet.
              </p>
            </Field>
          )}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={busy}>
              Continue
            </Button>
            <Button type="button" disabled={busy} onClick={() => setAction("")}>
              Cancel
            </Button>
          </div>
        </form>
      )}
      {error && (
        <div className="mt-4">
          <Notice tone="red">{error}</Notice>
        </div>
      )}
      <details className="mt-4 border-t border-zinc-100 pt-4 text-xs leading-6 text-zinc-600">
        <summary className="cursor-pointer font-semibold">
          How are Lead Flow and Smart Lists different?
        </summary>
        <dl className="mt-3 grid gap-3 md:grid-cols-2">
          <div>
            <dt className="font-semibold">Lead Flow</dt>
            <dd>
              Assigns incoming leads to people, teams or ponds. It is configured
              separately in Follow Up Boss; Radar does not create native Lead
              Flow rules yet.
            </dd>
          </div>
          <div>
            <dt className="font-semibold">Smart Lists</dt>
            <dd>
              Saved contact views based on filters. For contact verification,
              tags or a pond can identify the matching people; native Smart List
              setup remains in Follow Up Boss.
            </dd>
          </div>
        </dl>
      </details>
    </Card>
  );
}
