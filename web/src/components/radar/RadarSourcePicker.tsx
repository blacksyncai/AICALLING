"use client";
import { useEffect, useRef, useState } from "react";
import { Search, Bot, Check } from "lucide-react";
import { Button, Field, Input, Modal, Select } from "@/components/ui";
import type { Overview, Resources, Spec } from "./automation-types";
export type RadarSource = Spec["source"];
export function RadarSourcePicker({
  open,
  onClose,
  onSelect,
  overview,
  resources,
  selected,
  continueDrafting = false,
}: {
  open: boolean;
  onClose: () => void;
  onSelect: (source: RadarSource) => void;
  overview: Overview;
  resources?: Resources;
  selected?: RadarSource;
  continueDrafting?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<RadarSource>({
    agent_id: null,
    campaign_id: null,
    pond_id: "",
    blacksync_pond_id: null,
  });
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    setSearch("");
    setSource(
      selected || {
        agent_id: null,
        campaign_id: null,
        pond_id: "",
        blacksync_pond_id: null,
      },
    );
    const prior = document.activeElement as HTMLElement | null,
      overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const dialog = panel.current?.closest(
      '[role="dialog"]',
    ) as HTMLElement | null;
    dialog?.setAttribute("aria-label", "Choose call source");
    const timer = window.setTimeout(
      () =>
        panel.current
          ?.querySelector<HTMLInputElement>('input[type="search"]')
          ?.focus(),
      0,
    );
    const trap = (e: KeyboardEvent) => {
      if (e.key !== "Tab" || !dialog) return;
      const nodes = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not(:disabled), select:not(:disabled), [tabindex="0"]',
        ),
      ).filter((n) => n.offsetParent !== null);
      const first = nodes[0],
        last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last?.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", trap);
    return () => {
      window.clearTimeout(timer);
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", trap);
      prior?.focus();
    };
  }, [open]); // Keep the in-progress selection stable while catalogs refresh.
  const agents = overview.agents.filter((a) =>
    a.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );
  const valid = !!(
    source.agent_id ||
    source.campaign_id ||
    source.blacksync_pond_id ||
    source.pond_id ||
    source.lead_source
  );
  return (
    <Modal open={open} onClose={onClose} title="Choose call source">
      <div ref={panel}>
        <p className="mb-4 text-sm leading-6 text-zinc-500">
          Choose an existing agent. Campaign and pond filters are optional;
          selected filters apply together.
        </p>
        <div className="relative">
          <Search
            size={16}
            className="pointer-events-none absolute left-3 top-3 text-zinc-400"
          />
          <Input
            type="search"
            aria-label="Search existing agents"
            placeholder="Search your agents…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <div
          className="mt-3 max-h-56 space-y-2 overflow-y-auto"
          role="radiogroup"
          aria-label="Existing agents"
        >
          <button
            type="button"
            role="radio"
            aria-checked={!source.agent_id}
            onClick={() => setSource((s) => ({ ...s, agent_id: null }))}
            className="w-full rounded-xl border border-zinc-200 px-3 py-3 text-left text-sm"
          >
            Any agent{" "}
            <span className="text-xs text-zinc-500">
              — choose a campaign or pond below
            </span>
          </button>
          {agents.map((a) => (
            <button
              key={a.id}
              type="button"
              role="radio"
              aria-checked={source.agent_id === a.id}
              onClick={() => setSource((s) => ({ ...s, agent_id: a.id }))}
              className={`flex w-full items-center gap-3 rounded-xl border p-3 text-left text-sm ${source.agent_id === a.id ? "border-brand-400 bg-brand-50" : "border-zinc-200 hover:bg-zinc-50"}`}
            >
              <Bot size={17} className="shrink-0 text-brand-600" />
              <span className="min-w-0 flex-1 break-words">{a.name}</span>
              {source.agent_id === a.id && (
                <Check size={16} className="shrink-0 text-brand-600" />
              )}
            </button>
          ))}
          {!agents.length && (
            <p className="p-3 text-sm text-zinc-500">
              {overview.agents.length
                ? "No agents match your search."
                : "No agents are available in this workspace. You can choose a campaign or pond below."}
            </p>
          )}
        </div>
        <div className="mt-4 space-y-3 border-t border-zinc-100 pt-4">
          <Field label="Campaign (optional)">
            <Select
              aria-label="Source picker campaign"
              value={source.campaign_id || ""}
              onChange={(e) =>
                setSource((s) => ({
                  ...s,
                  campaign_id: e.target.value || null,
                }))
              }
            >
              <option value="">Any campaign</option>
              {overview.campaigns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </Select>
          </Field>
          {!!resources?.blacksync_ponds.length && (
            <Field label="BlackSync pond (optional)">
              <Select
                aria-label="Source picker BlackSync pond"
                value={source.blacksync_pond_id || ""}
                onChange={(e) =>
                  setSource((s) => ({
                    ...s,
                    blacksync_pond_id: e.target.value || null,
                  }))
                }
              >
                <option value="">Any BlackSync pond</option>
                {resources.blacksync_ponds.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {!!resources?.capabilities.route_pond && (
            <Field label="CRM source pond (optional)">
              <Select
                aria-label="Source picker CRM pond"
                value={source.pond_id}
                onChange={(e) =>
                  setSource((s) => ({ ...s, pond_id: e.target.value }))
                }
              >
                <option value="">Any CRM pond</option>
                {resources.crm_ponds.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
        </div>
        <p className="mt-4 text-xs leading-5 text-zinc-500">
          This selects which calls a rule can evaluate. It does not place calls
          or activate a rule.
        </p>
        <div className="mt-5 flex flex-wrap justify-end gap-2">
          <Button type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={!valid}
            onClick={() => onSelect(source)}
          >
            {continueDrafting ? "Continue drafting" : "Use selected source"}
          </Button>
        </div>
      </div>
    </Modal>
  );
}
