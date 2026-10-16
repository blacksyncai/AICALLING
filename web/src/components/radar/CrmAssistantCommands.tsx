"use client";
import { useEffect, useRef, useState } from "react";
import { CheckCircle2, Database, Play, ShieldCheck } from "lucide-react";
import { Button, Card, Notice, Badge, Modal } from "@/components/ui";
import { post } from "@/lib/api";

export interface CrmCommand {
  id: string;
  provider: string;
  provider_name?: string;
  account_label?: string;
  spec: { action: string; [key: string]: unknown };
  writes: boolean;
  status: string;
  result: Record<string, unknown>;
  error: string;
  created_at: string;
}
export const TOOL_NAMES: Record<string, string> = {
  list_contacts: "Browse contacts",
  find_contact: "Find a contact by phone or email",
  create_contact: "Find or create a contact",
  list_pipelines: "List pipelines and stages",
  create_pipeline: "Create a pipeline",
  add_stages: "Add pipeline stages",
  move_stage: "Move an existing record to a stage",
  field_catalog: "List available contact fields",
  contact_fields: "Read a contact’s fields",
  add_note: "Add a note",
  mark_dnc: "Mark a contact do not call",
  create_task: "Create a follow-up task",
  create_pond: "Create a Follow Up Boss pond",
  create_stage: "Create a Follow Up Boss person stage",
};
const LABELS: Record<string, string> = {
  name: "Name / title",
  phone: "Phone",
  email: "Email",
  company: "Company",
  external_id: "CRM contact / lead ID",
  pipeline_id: "Pipeline ID",
  stage_id: "Stage",
  stages: "Stages",
  query: "Filter this page",
  limit: "Page limit",
  text: "Note text",
  due_date: "Due date",
};
function Result({ result }: { result: Record<string, unknown> }) {
  const rows = result.contacts as Record<string, unknown>[] | undefined;
  if (rows)
    return (
      <div className="mt-4 overflow-x-auto rounded-lg border border-zinc-200">
        <table className="w-full text-left text-xs">
          <thead>
            <tr>
              {["Name", "Phone", "Email", "CRM ID"].map((x) => (
                <th key={x} className="p-3">
                  {x}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((c, i) => (
              <tr key={i} className="border-t border-zinc-100">
                {["name", "phone", "email", "id"].map((k) => (
                  <td key={k} className="p-3">
                    {String(c[k] ?? "")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length && <p className="p-3">No matches in this page.</p>}
        <p className="p-3 text-xs text-zinc-500">
          {String(result.scope ?? "")}
        </p>
      </div>
    );
  const pipes = (
    Array.isArray(result.pipelines)
      ? result.pipelines
      : result.pipeline
        ? [result.pipeline]
        : null
  ) as
    | {
        id: string;
        name: string;
        stages: { id: string; label: string; kind: string }[];
      }[]
    | null;
  if (pipes)
    return (
      <div className="mt-4 space-y-3">
        {pipes.map((pipe) => (
          <div key={pipe.id} className="rounded-xl border border-zinc-200 p-4">
            <strong className="text-sm">{pipe.name}</strong>
            <p className="mt-1 text-xs text-zinc-500">CRM ID: {pipe.id}</p>
            <ul className="mt-3 space-y-2 text-xs">
              {pipe.stages?.map((stage) => (
                <li key={stage.id}>
                  {stage.label} · {stage.kind} · {stage.id}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    );
  const fields = result.fields;
  const entries =
    fields && typeof fields === "object" && !Array.isArray(fields)
      ? Object.entries(fields)
      : Object.entries(result);
  return (
    <dl className="mt-4 max-h-80 space-y-3 overflow-auto rounded-xl bg-zinc-50 p-4 text-xs leading-6">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt className="text-zinc-500">{key.replaceAll("_", " ")}</dt>
          <dd className="whitespace-pre-wrap break-words">
            {typeof value === "object" ? JSON.stringify(value) : String(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}
function CommandDetails({ row }: { row: CrmCommand }) {
  return (
    <dl className="my-4 space-y-3">
      {Object.entries(row.spec)
        .filter(([key]) => key !== "action")
        .map(([key, value]) => (
          <div key={key} className="min-w-0">
            <dt className="text-xs text-zinc-500">{LABELS[key] ?? key}</dt>
            <dd className="mt-1 break-words whitespace-pre-wrap text-sm">
              {key === "stages" && Array.isArray(value)
                ? value
                    .map(
                      (s: { label: string; kind: string }) =>
                        `${s.label} (${s.kind})`,
                    )
                    .join(" → ")
                : String(value)}
            </dd>
          </div>
        ))}
    </dl>
  );
}

export function CrmCommandCard({
  command,
  onUpdated,
  reviewRequest = 0,
  onReviewOpened,
}: {
  command: CrmCommand;
  onUpdated?: (next: CrmCommand) => void;
  reviewRequest?: number;
  onReviewOpened?: () => void;
}) {
  const [row, setRow] = useState(command);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState(false);
  const dialogBody = useRef<HTMLDivElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);
  const executing = useRef(false);
  useEffect(() => setRow(command), [command]);
  useEffect(() => {
    if (reviewRequest > 0 && command.writes && command.status === "draft") {
      setConfirm(true);
      onReviewOpened?.();
    }
  }, [reviewRequest, command.writes, command.status, onReviewOpened]);
  useEffect(() => {
    if (!confirm) return;
    const dialog = dialogBody.current?.closest<HTMLElement>('[role="dialog"]');
    if (!dialog) return;
    dialog.setAttribute("aria-label", "Confirm CRM change");
    const previous = document.activeElement as HTMLElement | null;
    const oldOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    cancelButton.current?.focus();
    const trap = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const elements = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href], [tabindex="0"]',
        ),
      ).filter((el) => el.offsetParent !== null);
      const first = elements[0],
        last = elements.at(-1);
      if (!first) {
        event.preventDefault();
        return;
      }
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    dialog.addEventListener("keydown", trap);
    return () => {
      dialog.removeEventListener("keydown", trap);
      document.body.style.overflow = oldOverflow;
      previous?.focus();
    };
  }, [confirm]);
  const execute = async () => {
    if (executing.current) return;
    executing.current = true;
    setBusy(true);
    setError("");
    try {
      const next = await post<CrmCommand>(
        `/api/radar/automations/commands/${row.id}/execute`,
        { confirmed: true },
      );
      setRow(next);
      onUpdated?.(next);
      setConfirm(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't run this action.");
    } finally {
      executing.current = false;
      setBusy(false);
    }
  };
  return (
    <Card className="min-w-0 p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h3 className="flex items-center gap-2 text-base font-semibold">
          <Database size={17} />
          {TOOL_NAMES[row.spec.action] ?? row.spec.action}
        </h3>
        <Badge tone={row.status === "succeeded" ? "green" : "gray"}>
          {row.status}
        </Badge>
      </div>
      <p className="mt-2 text-xs leading-6 text-zinc-500">
        {row.writes
          ? "Proposed CRM change. Review the exact account and details before applying."
          : "Read-only CRM query. It does not change records."}{" "}
        · {row.provider_name ?? row.provider}
        {row.account_label ? ` · ${row.account_label}` : ""}
      </p>
      <CommandDetails row={row} />
      {row.spec.action === "move_stage" && (
        <p className="mb-4 text-xs text-zinc-500">
          Existing records only. Forward-only and closed-stage protections still
          apply.
        </p>
      )}
      {row.status === "draft" && !confirm && (
        <Button
          loading={busy}
          onClick={() => (row.writes ? setConfirm(true) : void execute())}
        >
          <Play size={14} />
          {row.writes ? "Review change" : "Run read-only query"}
        </Button>
      )}
      <Modal
        open={confirm}
        onClose={() => {
          if (!busy) setConfirm(false);
        }}
        title="Confirm CRM change"
      >
        <div ref={dialogBody}>
          <p className="text-sm leading-6 text-zinc-600">
            Review this action for{" "}
            <strong>
              {row.provider_name ?? row.provider}
              {row.account_label ? ` · ${row.account_label}` : ""}
            </strong>
            .
          </p>
          <h3 className="mt-4 text-base font-semibold">
            {TOOL_NAMES[row.spec.action] ?? row.spec.action}
          </h3>
          <CommandDetails row={row} />
          {row.provider === "followupboss" &&
            row.spec.action === "create_pipeline" && (
              <p className="mb-4 text-xs leading-5 text-zinc-500">
                This creates a deal pipeline or reuses the same name and adds
                missing stages. Person stages and ponds are separate. Existing
                stages are kept. Follow Up Boss stores won/lost selections as
                closed stages.
              </p>
            )}
          <p className="text-xs text-zinc-500">
            No phone calls or messages will be sent.
          </p>
          {error && (
            <div className="mt-3">
              <Notice tone="red">{error}</Notice>
            </div>
          )}
          <div className="mt-5 flex flex-wrap justify-end gap-2">
            <button
              ref={cancelButton}
              type="button"
              disabled={busy}
              onClick={() => setConfirm(false)}
              className="min-h-10 rounded-lg border border-zinc-200 px-4 text-sm font-medium disabled:opacity-50"
            >
              Cancel
            </button>
            <Button
              variant="primary"
              loading={busy}
              onClick={() => void execute()}
            >
              <ShieldCheck size={14} />
              Confirm and continue
            </Button>
          </div>
        </div>
      </Modal>
      {row.status === "succeeded" && (
        <>
          <p className="flex items-center gap-2 text-xs text-emerald-700">
            <CheckCircle2 size={14} />
            Completed
          </p>
          <Result result={row.result} />
        </>
      )}
      {(row.status === "uncertain" || row.status === "running") && (
        <Notice tone="amber">
          The result may be incomplete. Check the CRM before preparing another
          write; this command will not run twice.
        </Notice>
      )}
      {(error || row.error) && (
        <div className="mt-3">
          <Notice tone="red">{error || row.error}</Notice>
        </div>
      )}
    </Card>
  );
}
