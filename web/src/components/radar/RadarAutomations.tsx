"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import {
  ArrowDown,
  ArrowRight,
  Bot,
  CheckCircle2,
  Clock3,
  FolderPlus,
  Layers,
  MessageSquare,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Send,
  Settings2,
  Sparkles,
  Workflow,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Card,
  Field,
  Input,
  Modal,
  Notice,
  Select,
  Spinner,
  Textarea,
} from "@/components/ui";
import { fetcher, patch, post, put } from "@/lib/api";
import { humanize, timeAgo } from "@/lib/utils";
import {
  blankRule,
  destinations,
  OUTCOMES,
  VERIFICATION_LABELS,
  type Action,
  type Overview,
  type Preview,
  type Resources,
  type Rule,
} from "./automation-types";
import styles from "./radar-automations.module.css";
const BASE = "/api/radar/automations";
const errorText = (e: unknown) =>
  e instanceof Error ? e.message : "Something went wrong";
type ResourceRequest = { kind: string; name: string };

export function RadarAutomations() {
  const { data, error, mutate } = useSWR<Overview>(BASE, fetcher);
  const [picked, setPicked] = useState("");
  const [view, setView] = useState("build");
  const [request, setRequest] = useState("");
  const [messages, setMessages] = useState<
    { role: string; text: string; provider: string }[]
  >([]);
  const [drafts, setDrafts] = useState<(Rule & { key: string })[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [suggestions, setSuggestions] = useState<ResourceRequest[]>([]);
  const provider =
    picked ||
    data?.connections.find((c) => c.provider === "followupboss")?.provider ||
    data?.connections[0]?.provider ||
    "";
  const {
    data: resources,
    error: resourceError,
    mutate: refreshResources,
  } = useSWR<Resources>(
    provider ? `${BASE}/resources/${provider}` : null,
    fetcher,
  );
  const connection = data?.connections.find((c) => c.provider === provider);
  const edit = (r: Rule) => {
    setPicked(r.provider);
    setDrafts((old) => [
      { ...structuredClone(r), key: crypto.randomUUID(), dirty: false },
      ...old,
    ]);
    setView("build");
  };
  const ask = async () => {
    if (!request.trim() || !provider) return;
    const text = request.trim();
    setBusy(true);
    setErr("");
    setMessages((m) => [...m, { role: "user", text, provider }]);
    setRequest("");
    try {
      const result = await post<{
        message: string;
        drafts: Rule[];
        resource_requests: ResourceRequest[];
      }>(`${BASE}/draft`, {
        provider,
        message: text,
        history: messages
          .filter((m) => m.provider === provider && m.role === "user")
          .slice(-6)
          .map((m) => m.text),
      });
      setMessages((m) => [
        ...m,
        { role: "assistant", text: result.message, provider },
      ]);
      setDrafts((old) => [
        ...result.drafts.map((r) => ({
          ...r,
          key: crypto.randomUUID(),
          dirty: true,
          status: "draft" as const,
        })),
        ...old,
      ]);
      setSuggestions(result.resource_requests);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  if (error) return <Notice tone="red">{errorText(error)}</Notice>;
  if (!data)
    return (
      <div className="flex justify-center py-10">
        <Spinner />
      </div>
    );
  if (!data.connections.length)
    return (
      <Card className="p-6">
        <h2 className="text-lg font-semibold">
          Connect a CRM to build automations
        </h2>
        <p className="mt-2 text-sm text-zinc-500">
          Start with Follow Up Boss, or use your other connected CRM’s supported
          actions.
        </p>
        <Link
          className="mt-4 inline-block text-sm font-semibold text-brand-600"
          href="/integrations"
        >
          Connect a CRM →
        </Link>
      </Card>
    );
  return (
    <div className={styles.root}>
      <div className={styles.topbar}>
        <div>
          <span className={styles.eyebrow}>RADAR AUTOMATIONS</span>
          <h2>From a conversation to the next step.</h2>
          <p>Describe the workflow. Review the rule. Decide when it runs.</p>
        </div>
        <label className={styles.crmSelect}>
          Connected CRM
          <Select
            aria-label="Automation CRM"
            value={provider}
            onChange={(e) => {
              setPicked(e.target.value);
              setSuggestions([]);
              setErr("");
            }}
          >
            {data.connections.map((c) => (
              <option key={c.provider} value={c.provider}>
                {c.name}
                {c.label ? ` · ${c.label}` : ""}
              </option>
            ))}
          </Select>
        </label>
      </div>
      <nav className={styles.views} aria-label="Automation sections">
        {[
          { key: "build", label: "Build automation", icon: Sparkles },
          {
            key: "rules",
            label: `Saved rules (${data.rules.length})`,
            icon: Workflow,
          },
          { key: "resources", label: "Ponds & stages", icon: Layers },
          { key: "activity", label: "Activity", icon: Clock3 },
        ].map(({ key, label, icon: Icon }) => (
          <button
            type="button"
            key={key}
            aria-current={view === key ? "page" : undefined}
            onClick={() => setView(key)}
          >
            <Icon size={15} />
            {label}
          </button>
        ))}
      </nav>
      {resourceError && <Notice tone="red">{errorText(resourceError)}</Notice>}
      {resources?.warnings.map((w) => (
        <Notice tone="amber" key={w}>
          {w}
        </Notice>
      ))}
      {view === "build" && (
        <>
          <div className={styles.buildGrid}>
            <Card className={styles.chat}>
              <div className={styles.chatHeading}>
                <span className={styles.botIcon}>
                  <Bot size={22} />
                </span>
                <div>
                  <h3>What should Radar do?</h3>
                  <p>Build around your team’s workflow.</p>
                </div>
                <Badge tone="gray">Draft mode</Badge>
              </div>
              <div className={styles.messages} aria-live="polite">
                {!messages.some((m) => m.provider === provider) && (
                  <div className={styles.welcome}>
                    <h4>Turn a request into a rule.</h4>
                    <p>
                      “When someone confirms their name, move them to my
                      Verified Contacts pond. Put named voicemails in Needs
                      Review.”
                    </p>
                    <span>
                      Name confirmation and named voicemail stay separate.
                    </span>
                  </div>
                )}
                {messages
                  .filter((m) => m.provider === provider)
                  .map((m, i) => (
                    <div
                      className={
                        m.role === "user"
                          ? styles.userMessage
                          : styles.assistantMessage
                      }
                      key={i}
                    >
                      <span>{m.role === "user" ? "You" : "Radar"}</span>
                      <p>{m.text}</p>
                    </div>
                  ))}
                {busy && (
                  <p className="flex items-center gap-2 text-sm text-zinc-500">
                    <Spinner />
                    Drafting a workflow…
                  </p>
                )}
              </div>
              <div className="px-4 pb-3">
              <Button
                onClick={() => {
                  setDrafts((d) => [
                    { ...blankRule(provider), key: crypto.randomUUID() },
                    ...d,
                  ]);
                }}
              >
                <Plus size={14} />
                Build manually
              </Button>
              </div>
              <form
                className={styles.composer}
                onSubmit={(e) => {
                  e.preventDefault();
                  void ask();
                }}
              >
                <Textarea
                  aria-label="Describe your automation"
                  value={request}
                  onChange={(e) => setRequest(e.target.value)}
                  maxLength={4000}
                  rows={3}
                  placeholder={`Tell Radar what to do in ${connection?.name ?? "your CRM"}…`}
                />
                <div>
                  <span>Drafting does not move contacts or place calls.</span>
                  <Button
                    type="submit"
                    variant="primary"
                    loading={busy}
                    disabled={!request.trim()}
                  >
                    <Send size={14} />
                    Draft workflow
                  </Button>
                </div>
              </form>
              {err && (
                <div className="px-4 pb-4">
                  <Notice tone="red">{err}</Notice>
                </div>
              )}
            </Card>
            <aside className={styles.guide}>
              <span className={styles.eyebrow}>YOUR WORKFLOW, EXPLAINED</span>
              <div>
                <span>01</span>
                <h3>Choose the source</h3>
                <p>An agent, campaign or Follow Up Boss pond.</p>
              </div>
              <div>
                <span>02</span>
                <h3>Define the evidence</h3>
                <p>
                  A clear name confirmation, a named voicemail, an outcome or an
                  extracted answer.
                </p>
              </div>
              <div>
                <span>03</span>
                <h3>Choose the destination</h3>
                <p>
                  Use a BlackSync pond, a CRM pond or a supported stage. Add a
                  tag when available.
                </p>
              </div>

            </aside>
          </div>
          {suggestions.length > 0 && (
            <Card className="mt-4 p-4">
              <h3 className="text-sm font-semibold">Suggested resources</h3>
              <p className="mt-1 text-xs text-zinc-500">
                These haven’t been created. Open Ponds & stages to create them
                explicitly.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {suggestions.map((s, i) => (
                  <button
                    className={styles.resourceSuggestion}
                    key={i}
                    onClick={() => setView("resources")}
                    type="button"
                  >
                    <FolderPlus size={14} />
                    {s.name}
                    <ArrowRight size={13} />
                  </button>
                ))}
              </div>
            </Card>
          )}
          <div className={styles.drafts}>
            {drafts
              .filter((d) => d.provider === provider)
              .map((d) => (
                <DraftEditor
                  key={d.key}
                  draft={d}
                  resources={resources}
                  overview={data}
                  onChange={(next) =>
                    setDrafts((all) =>
                      all.map((x) =>
                        x.key === d.key ? { ...next, key: d.key } : x,
                      ),
                    )
                  }
                  onSaved={() => void mutate()}
                  onResources={() => setView("resources")}
                  onRemove={() =>
                    setDrafts((all) => all.filter((x) => x.key !== d.key))
                  }
                />
              ))}
          </div>
        </>
      )}
      {view === "rules" && (
        <div className={styles.savedRules}>
          {data.rules.length === 0 ? (
            <Card className="p-6">
              <h3 className="font-semibold">
                Your first automation starts with a request.
              </h3>
              <p className="mt-2 text-sm text-zinc-500">
                Create a draft, choose a destination and activate it when ready.
              </p>
              <Button className="mt-4" onClick={() => setView("build")}>
                Build automation
              </Button>
            </Card>
          ) : (
            data.rules.map((r) => (
              <Card key={r.id} className="p-5">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <h3 className="font-semibold">{r.name}</h3>
                    <p className="mt-1 text-xs text-zinc-500">
                      {data.connections.find((c) => c.provider === r.provider)
                        ?.name ?? r.provider}{" "}
                      · Version {r.version}
                    </p>
                  </div>
                  <Badge tone={r.status === "active" ? "green" : "gray"}>
                    {r.status}
                  </Badge>
                </div>
                <p className="mt-4 text-sm text-zinc-600">
                  {r.spec.condition.kind === "verification"
                    ? VERIFICATION_LABELS[r.spec.condition.value]
                    : humanize(r.spec.condition.value)}{" "}
                  → {r.spec.actions.length} action
                  {r.spec.actions.length === 1 ? "" : "s"}
                </p>
                <div className="mt-4 flex flex-wrap gap-2">
                  <Button onClick={() => edit(r)}>
                    <Settings2 size={14} />
                    Review / edit
                  </Button>
                  <StateButton rule={r} onUpdate={() => void mutate()} />
                </div>
              </Card>
            ))
          )}
        </div>
      )}
      {view === "resources" &&
        (resources ? (
          <ResourceManager
          key={provider}
            provider={provider}
            resources={resources}
            suggestions={suggestions}
            refresh={() => void refreshResources()}
          />
        ) : (
          !resourceError && <Spinner />
        ))}
      {view === "activity" && <AutomationActivity />}
    </div>
  );
}

function StateButton({ rule, onUpdate }: { rule: Rule; onUpdate: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <>
      <Button
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await patch(`${BASE}/${rule.id}/state`, {
              status: rule.status === "active" ? "paused" : "active",
            });
            onUpdate();
          } catch (e) {
            setError(errorText(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {rule.status === "active" ? <Pause size={14} /> : <Play size={14} />}{" "}
        {rule.status === "active" ? "Pause" : "Activate"}
      </Button>
      {error && (
        <p className="text-xs text-red-600" role="alert">
          {error}
        </p>
      )}
    </>
  );
}

function DraftEditor({
  draft,
  resources,
  overview,
  onChange,
  onSaved,
  onResources,
  onRemove,
}: {
  draft: Rule;
  resources?: Resources;
  overview: Overview;
  onChange: (r: Rule) => void;
  onSaved: () => void;
  onResources: () => void;
  onRemove: () => void;
}) {
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [notice, setNotice] = useState("");
  const options = resources ? destinations(resources) : [];
  const update = (next: Rule) => {
    onChange({ ...next, dirty: true });
    setPreview(null);
    setSelected(new Set());
    setNotice("");
  };
  const changeSource = (patch: Partial<Rule["spec"]["source"]>) =>
    update({
      ...draft,
      spec: { ...draft.spec, source: { ...draft.spec.source, ...patch } },
    });
  const changeCondition = (patch: Partial<Rule["spec"]["condition"]>) =>
    update({
      ...draft,
      spec: { ...draft.spec, condition: { ...draft.spec.condition, ...patch } },
    });
  const setActions = (actions: Action[]) =>
    update({ ...draft, spec: { ...draft.spec, actions } });
  const payload = () => ({
    name: draft.name,
    provider: draft.provider,
    request: draft.request,
    spec: draft.spec,
  });
  const doAction = async (kind: string) => {
    setBusy(kind);
    setError("");
    setNotice("");
    try {
      if (kind === "save") {
        const saved = draft.id
          ? await put<Rule>(`${BASE}/${draft.id}`, payload())
          : await post<Rule>(BASE, payload());
        onChange({ ...saved, dirty: false });
        onSaved();
        setNotice("Saved as a draft. Activate it to process new calls.");
      }
      if (kind === "preview") {
        setPreview(await post<Preview>(`${BASE}/preview`, payload()));
        setSelected(new Set());
      }
      if (kind === "run") {
        const result = await post<{ queued: number }>(
          `${BASE}/${draft.id}/run`,
          { call_ids: [...selected] },
        );
        setNotice(
          `${result.queued} matching call(s) queued for routing. No phone calls are placed.`,
        );
        setSelected(new Set());
      }
      if (kind === "state") {
        const saved = await patch<Rule>(`${BASE}/${draft.id}/state`, {
          status: draft.status === "active" ? "paused" : "active",
        });
        onChange({ ...saved, dirty: false });
        onSaved();
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  };
  const valid =
    !!draft.name.trim() &&
    draft.spec.actions.length > 0 &&
    draft.spec.actions.every((a) => !!a.target_id);
  return (
    <Card className={styles.editor}>
      <div className={styles.editorHeading}>
        <div>
          <span className={styles.eyebrow}>REVIEW YOUR AUTOMATION</span>
          <h3>{draft.id ? "Saved workflow" : "Workflow draft"}</h3>
        </div>
        <div className="flex items-center gap-2">
          <Badge
            tone={draft.status === "active" && !draft.dirty ? "green" : "gray"}
          >
            {draft.dirty ? "Unsaved draft" : (draft.status ?? "draft")}
          </Badge>
          <button
            type="button"
            aria-label="Close workflow draft"
            onClick={onRemove}
          >
            <X size={17} />
          </button>
        </div>
      </div>
      <div className={styles.editorBody}>
        <Field label="Automation name">
          <Input
            aria-label="Automation name"
            value={draft.name}
            maxLength={120}
            onChange={(e) => update({ ...draft, name: e.target.value })}
          />
        </Field>
        <div className={styles.ruleSection}>
          <span className={styles.stepNumber}>01</span>
          <div className="min-w-0 flex-1">
            <h4>When a phone call finishes</h4>
            <p>
              Only calls started after activation run automatically. Browser
              tests are excluded.
            </p>
            <div className={styles.fields}>
              <Field label="Agent">
                <Select
                  aria-label="Source agent"
                  value={draft.spec.source.agent_id ?? ""}
                  onChange={(e) =>
                    changeSource({ agent_id: e.target.value || null })
                  }
                >
                  <option value="">All agents</option>
                  {overview.agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Campaign">
                <Select
                  aria-label="Source campaign"
                  value={draft.spec.source.campaign_id ?? ""}
                  onChange={(e) =>
                    changeSource({ campaign_id: e.target.value || null })
                  }
                >
                  <option value="">All campaigns</option>
                  {overview.campaigns.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
              {resources?.capabilities.route_pond && (
                <Field label="Source CRM pond">
                  <Select
                    aria-label="Source CRM pond"
                    value={draft.spec.source.pond_id}
                    onChange={(e) => changeSource({ pond_id: e.target.value })}
                  >
                    <option value="">Any pond</option>
                    {resources.crm_ponds.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
          </div>
        </div>
        <div className={styles.ruleSection}>
          <span className={styles.stepNumber}>02</span>
          <div className="min-w-0 flex-1">
            <h4>If the evidence matches</h4>
            <div className={styles.fields}>
              <Field label="Condition type">
                <Select
                  aria-label="Condition type"
                  value={draft.spec.condition.kind}
                  onChange={(e) =>
                    changeCondition({
                      kind: e.target.value as
                        "verification" | "outcome" | "field",
                      value:
                        e.target.value === "verification"
                          ? "name_confirmed"
                          : e.target.value === "outcome"
                            ? "interested"
                            : "",
                      field: e.target.value === "field" ? "timeline" : "",
                      operator: "equals",
                    })
                  }
                >
                  <option value="verification">
                    Name / number verification
                  </option>
                  <option value="outcome">Call outcome</option>
                  <option value="field">Extracted answer</option>
                </Select>
              </Field>
              {draft.spec.condition.kind === "verification" ? (
                <Field label="Verification result">
                  <Select
                    aria-label="Verification result"
                    value={draft.spec.condition.value}
                    onChange={(e) => changeCondition({ value: e.target.value })}
                  >
                    {Object.entries(VERIFICATION_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : draft.spec.condition.kind === "outcome" ? (
                <Field label="Call outcome">
                  <Select
                    aria-label="Call outcome"
                    value={draft.spec.condition.value}
                    onChange={(e) => changeCondition({ value: e.target.value })}
                  >
                    {OUTCOMES.map((o) => (
                      <option key={o} value={o}>
                        {humanize(o)}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : (
                <>
                  <Field label="Extracted field">
                    <Input
                      aria-label="Extracted field"
                      placeholder="timeline"
                      value={draft.spec.condition.field}
                      onChange={(e) =>
                        changeCondition({ field: e.target.value })
                      }
                    />
                  </Field>
                  <Field label="Comparison">
                    <Select
                      aria-label="Field comparison"
                      value={draft.spec.condition.operator}
                      onChange={(e) =>
                        changeCondition({
                          operator: e.target.value as
                            "equals" | "contains" | "exists",
                        })
                      }
                    >
                      <option value="equals">Equals</option>
                      <option value="contains">Contains</option>
                      <option value="exists">Has a value</option>
                    </Select>
                  </Field>
                  {draft.spec.condition.operator !== "exists" && (
                    <Field label="Value">
                      <Input
                        aria-label="Condition value"
                        value={draft.spec.condition.value}
                        onChange={(e) =>
                          changeCondition({ value: e.target.value })
                        }
                      />
                    </Field>
                  )}
                </>
              )}
            </div>
            <p>
              Name confirmation requires a clear name check and reply. A named
              voicemail is a separate result; a connected call alone is not
              confirmation.
            </p>
          </div>
        </div>
        <div className={styles.ruleSection}>
          <span className={styles.stepNumber}>03</span>
          <div className="min-w-0 flex-1">
            <h4>Then take these actions</h4>
            {draft.requested_destination && !draft.spec.actions.length && (
              <p>Choose or create “{draft.requested_destination}”.</p>
            )}
            {draft.spec.actions.map((a, i) => (
              <div className={styles.actionRow} key={i}>
                {a.kind === "crm_tag" ? (
                  <Input
                    aria-label={`Tag for action ${i + 1}`}
                    value={a.target_id}
                    placeholder="Tag name"
                    onChange={(e) =>
                      setActions(
                        draft.spec.actions.map((x, j) =>
                          i === j ? { ...x, target_id: e.target.value } : x,
                        ),
                      )
                    }
                  />
                ) : (
                  <Select
                    aria-label={`Destination for action ${i + 1}`}
                    value={JSON.stringify(a)}
                    onChange={(e) =>
                      setActions(
                        draft.spec.actions.map((x, j) =>
                          i === j ? (JSON.parse(e.target.value) as Action) : x,
                        ),
                      )
                    }
                  >
                    <option value={JSON.stringify(a)} disabled>
                      {options.find(
                        (o) => JSON.stringify(o.action) === JSON.stringify(a),
                      )?.label ?? "Choose destination"}
                    </option>
                    {options.map((o) => (
                      <option
                        key={JSON.stringify(o.action)}
                        value={JSON.stringify(o.action)}
                      >
                        {o.label}
                      </option>
                    ))}
                  </Select>
                )}
                <button
                  type="button"
                  aria-label={`Remove action ${i + 1}`}
                  onClick={() =>
                    setActions(draft.spec.actions.filter((_, j) => i !== j))
                  }
                >
                  <X size={16} />
                </button>
              </div>
            ))}
            {draft.spec.actions.length < 4 && (
              <div className="mt-3 flex flex-wrap gap-2">
                <Select
                  aria-label="Add routing action"
                  value=""
                  className="min-w-0 flex-1"
                  onChange={(e) => {
                    if (e.target.value)
                      setActions([
                        ...draft.spec.actions,
                        JSON.parse(e.target.value) as Action,
                      ]);
                  }}
                >
                  <option value="">+ Choose a destination</option>
                  {options.map((o) => (
                    <option
                      key={JSON.stringify(o.action)}
                      value={JSON.stringify(o.action)}
                    >
                      {o.label}
                    </option>
                  ))}
                </Select>
                {resources?.capabilities.tag && (
                  <Button
                    onClick={() =>
                      setActions([
                        ...draft.spec.actions,
                        { kind: "crm_tag", target_id: "", pipeline_id: "" },
                      ])
                    }
                  >
                    + Add tag
                  </Button>
                )}
              </div>
            )}
            <button
              type="button"
              className="mt-3 text-xs font-semibold text-brand-600"
              onClick={onResources}
            >
              Create a pond, stage or pipeline →
            </button>
            <p>
              Do-not-call contacts are excluded. Routing never launches another
              call.
            </p>
          </div>
        </div>
        {error && <Notice tone="red">{error}</Notice>}
        {notice && <Notice tone="green">{notice}</Notice>}
        <div className={styles.editorActions}>
          <Button
            loading={busy === "preview"}
            disabled={!valid || !!busy}
            onClick={() => void doAction("preview")}
          >
            <CheckCircle2 size={15} />
            Preview matches
          </Button>
          <Button
            variant="primary"
            loading={busy === "save"}
            disabled={!valid || !!busy}
            onClick={() => void doAction("save")}
          >
            Save draft
          </Button>
          {draft.id && !draft.dirty && (
            <Button disabled={!!busy} onClick={() => void doAction("state")}>
              {draft.status === "active" ? (
                <Pause size={14} />
              ) : (
                <Play size={14} />
              )}{" "}
              {draft.status === "active" ? "Pause" : "Activate"}
            </Button>
          )}
        </div>
        {preview && (
          <div className={styles.preview}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h4>
                  {preview.matched} match{preview.matched === 1 ? "" : "es"} in{" "}
                  {preview.checked} recent calls
                </h4>
                <p>
                  Read-only preview, up to {preview.limit} calls. No changes
                  have been applied.
                </p>
              </div>
              <Button
                size="sm"
                onClick={() =>
                  setSelected(
                    new Set(
                      preview.items
                        .filter((i) => i.matches)
                        .map((i) => i.call_id),
                    ),
                  )
                }
              >
                Select matches
              </Button>
            </div>
            {!preview.items.length && (
              <p className="mt-4 text-sm text-zinc-500">
                No completed calls in this source yet.
              </p>
            )}
            <div className={styles.previewList}>
              {preview.items.map((item) => (
                <div className={styles.previewItem} key={item.call_id}>
                  <input
                    aria-label={`Select call for ${item.name}`}
                    type="checkbox"
                    disabled={!item.matches}
                    checked={selected.has(item.call_id)}
                    onChange={(e) =>
                      setSelected((old) => {
                        const next = new Set(old);
                        if (e.target.checked) next.add(item.call_id);
                        else next.delete(item.call_id);
                        return next;
                      })
                    }
                  />
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <strong>{item.name}</strong>
                      <Badge tone={item.matches ? "green" : "gray"}>
                        {VERIFICATION_LABELS[item.status] ??
                          humanize(item.status)}
                      </Badge>
                    </div>
                    <p>
                      {item.phone} · {item.reason}
                    </p>
                    {item.evidence.map((e, i) => (
                      <blockquote key={i}>
                        <span>{e.role === "user" ? "Contact" : "Agent"}</span> “
                        {e.text}”
                      </blockquote>
                    ))}
                    <Link
                      href={`/calls/${item.call_id}`}
                      className="text-xs font-semibold text-brand-600"
                    >
                      View call →
                    </Link>
                  </div>
                </div>
              ))}
            </div>
            <Button
              disabled={
                !selected.size ||
                !draft.id ||
                draft.dirty ||
                draft.status !== "active" ||
                !!busy
              }
              loading={busy === "run"}
              onClick={() => void doAction("run")}
            >
              Apply to {selected.size} selected past call
              {selected.size === 1 ? "" : "s"}
            </Button>
            <p>
              To apply past matches, save and activate this exact rule first.
              New calls run automatically after activation.
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}

function ResourceManager({
  provider,
  resources,
  suggestions,
  refresh,
}: {
  provider: string;
  resources: Resources;
  suggestions: ResourceRequest[];
  refresh: () => void;
}) {
  const [kind, setKind] = useState("blacksync_pond");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [pond, setPond] = useState("");
  const { data: members, error: memberError } = useSWR<{
    name: string;
    members: {
      lead_id: string;
      name: string;
      phone: string;
      call_id: string;
    }[];
  }>(pond ? `${BASE}/ponds/${pond}/members` : null, fetcher);
  const available = [
    { key: "blacksync_pond", label: "BlackSync pond" },
    ...(resources.capabilities.create_pond
      ? [{ key: "crm_pond", label: `${resources.provider_name} pond` }]
      : []),
    ...(resources.capabilities.create_stage
      ? [{ key: "crm_stage", label: `${resources.provider_name} lead stage` }]
      : []),
    ...(resources.capabilities.create_pipeline
      ? [
          {
            key: "crm_pipeline",
            label: `${resources.provider_name} deal pipeline`,
          },
        ]
      : []),
  ];
  return (
    <div className={styles.resourceGrid}>
      <Card className="p-5">
        <span className={styles.eyebrow}>CREATE A DESTINATION</span>
        <h3 className="mt-2 text-lg font-semibold">
          Give the next step a home.
        </h3>
        <p className="mt-2 text-sm leading-6 text-zinc-500">
          BlackSync ponds stay in this workspace. CRM resources are created in
          the connected account using its permissions.
        </p>
        <form
          className="mt-5 space-y-4"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            setNotice("");
            try {
              const result = await post<{ name: string; location: string }>(
                `${BASE}/resources/${provider}`,
                { kind, name },
              );
              setNotice(`“${result.name}” is ready in ${result.location}.`);
              setName("");
              refresh();
            } catch (err) {
              setError(errorText(err));
            } finally {
              setBusy(false);
            }
          }}
        >
          <Field label="Create in">
            <Select
              aria-label="Resource type"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            >
              {available.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Name">
            <Input
              aria-label="New resource name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={120}
              placeholder="Verified Contacts"
              required
            />
          </Field>
          {kind === "crm_pipeline" && (
            <Notice tone="amber">
              This creates a CRM deal pipeline. It is separate from lead-stage
              routing and does not move contacts into a deal.
            </Notice>
          )}
          <Button
            type="submit"
            variant="primary"
            loading={busy}
            disabled={!name.trim()}
          >
            <Plus size={15} />
            Create resource
          </Button>
        </form>
        {suggestions.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {suggestions.map((s, i) => (
              <button
                type="button"
                className={styles.resourceSuggestion}
                key={i}
                onClick={() => {
                  setName(s.name);
                  if (available.some((x) => x.key === s.kind)) setKind(s.kind);
                }}
              >
                {s.name}
              </button>
            ))}
          </div>
        )}
        {error && (
          <div className="mt-4">
            <Notice tone="red">{error}</Notice>
          </div>
        )}
        {notice && (
          <div className="mt-4">
            <Notice tone="green">{notice}</Notice>
          </div>
        )}
      </Card>
      <div className="space-y-4">
        <Card className="p-5">
          <div className="flex justify-between gap-3">
            <h3 className="font-semibold">BlackSync ponds</h3>
            <button
              aria-label="Refresh resources"
              onClick={refresh}
              type="button"
            >
              <RefreshCw size={15} />
            </button>
          </div>
          {!resources.blacksync_ponds.length && (
            <p className="mt-3 text-sm text-zinc-500">
              Create a pond to organize confirmed contacts and review queues.
            </p>
          )}
          {resources.blacksync_ponds.map((p) => (
            <button
              type="button"
              className={styles.pondRow}
              key={p.id}
              onClick={() => setPond(p.id)}
            >
              <span>
                <Layers size={16} />
                {p.name}
              </span>
              <span>
                {p.members ?? 0} contacts <ArrowRight size={14} />
              </span>
            </button>
          ))}
        </Card>
        <Card className="p-5">
          <h3 className="font-semibold">
            {resources.provider_name} destinations
          </h3>
          {resources.crm_ponds.map((p) => (
            <div className={styles.pondRow} key={p.id}>
              <span>{p.name}</span>
              <Badge tone="gray">CRM pond</Badge>
            </div>
          ))}
          {resources.pipelines.map((p) => (
            <div key={p.id} className="mt-4">
              <h4 className="text-xs font-semibold text-zinc-500">{p.name}</h4>
              <div className="mt-2 flex flex-wrap gap-2">
                {p.stages.map((s) => (
                  <Badge key={s.id} tone="gray">
                    {s.label}
                  </Badge>
                ))}
              </div>
            </div>
          ))}
          {resources.deal_pipelines.length > 0 && (
            <div className="mt-4">
              <h4 className="text-xs font-semibold text-zinc-500">
                Deal pipelines
              </h4>
              <div className="mt-2 flex flex-wrap gap-2">
                {resources.deal_pipelines.map((p) => (
                  <Badge key={p.id} tone="gray">
                    {p.name}
                  </Badge>
                ))}
              </div>
            </div>
          )}
          <p className="mt-4 text-xs leading-5 text-zinc-500">
            Only supported actions are offered. The CRM may require admin
            permissions for resource creation.
          </p>
        </Card>
      </div>
      <Modal
        open={!!pond}
        onClose={() => setPond("")}
        title={members?.name ?? "Pond contacts"}
        wide
      >
        {memberError ? (
          <Notice tone="red">{errorText(memberError)}</Notice>
        ) : !members ? (
          <Spinner />
        ) : !members.members.length ? (
          <p className="text-sm text-zinc-500">
            No contacts have been routed here yet.
          </p>
        ) : (
          members.members.map((m) => (
            <div className={styles.pondRow} key={`${m.lead_id}-${m.phone}`}>
              <span>
                {m.name} · {m.phone}
              </span>
              <Link href={`/calls/${m.call_id}`} className="text-brand-600">
                View call →
              </Link>
            </div>
          ))
        )}
      </Modal>
    </div>
  );
}

function AutomationActivity() {
  const { data, error, mutate } = useSWR<{
    items: {
      id: string;
      rule_name: string;
      call_id: string;
      status: string;
      attempts: number;
      error: string;
      result: { reason?: string; actions?: Record<string, string> };
      created_at: string;
      next_at?: string | null;
    }[];
  }>(`${BASE}/activity`, fetcher, { refreshInterval: 10000 });
  const [retryErr, setRetryErr] = useState("");
  if (error) return <Notice tone="red">{errorText(error)}</Notice>;
  if (!data) return <Spinner />;
  return (
    <Card className="p-5">
      <div className="flex flex-wrap justify-between gap-3">
        <div>
          <h3 className="font-semibold">Automation activity</h3>
          <p className="mt-1 text-xs text-zinc-500">
            Completed actions, retries and skipped contacts. Updates every 10
            seconds.
          </p>
        </div>
        <Button size="sm" onClick={() => void mutate()}>
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>
      {retryErr && (
        <div className="mt-4">
          <Notice tone="red">{retryErr}</Notice>
        </div>
      )}
      {!data.items.length && (
        <div className={styles.activityEmpty}>
          <Workflow size={30} />
          <h4>No executions yet</h4>
          <p>
            Activate a saved rule to process new calls, or preview and
            explicitly apply it to selected past calls.
          </p>
        </div>
      )}
      {data.items.map((i) => (
        <div className={styles.activityRow} key={i.id}>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <strong>{i.rule_name}</strong>
              <Badge
                tone={
                  i.status === "succeeded"
                    ? "green"
                    : i.status === "failed"
                      ? "red"
                      : "gray"
                }
              >
                {humanize(i.status)}
              </Badge>
            </div>
            <p>
              {timeAgo(i.created_at)} · {i.attempts} attempt
              {i.attempts === 1 ? "" : "s"}
            </p>
            {i.result.reason && <p>{i.result.reason}</p>}
            {Object.entries(i.result.actions ?? {}).map(([k, v]) => (
              <p key={k} className="flex items-center gap-1">
                <CheckCircle2 size={12} />
                {v}
              </p>
            ))}
            {i.error && <p className="text-red-600">{i.error}</p>}
            {i.next_at && (
              <p>Retry scheduled: {new Date(i.next_at).toLocaleString()}</p>
            )}
            <Link
              href={`/calls/${i.call_id}`}
              className="text-xs font-semibold text-brand-600"
            >
              View call →
            </Link>
          </div>
          {["retry", "failed"].includes(i.status) && (
            <Button
              size="sm"
              onClick={async () => {
                setRetryErr("");
                try {
                  await post(`${BASE}/activity/${i.id}/retry`);
                  void mutate();
                } catch (e) {
                  setRetryErr(errorText(e));
                }
              }}
            >
              Retry
            </Button>
          )}
        </div>
      ))}
    </Card>
  );
}
