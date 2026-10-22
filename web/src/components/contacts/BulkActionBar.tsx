"use client";

import { Ban, FolderPlus, Tag, Trash2, X, CircleDot } from "lucide-react";
import { useState } from "react";
import useSWR from "swr";
import { useToast } from "@/components/toast";
import { Button, Field, Input, Modal, Select } from "@/components/ui";
import { fetcher, post } from "@/lib/api";
import type { Agent, Campaign } from "@/lib/types";
import { humanize, outcomeLabel } from "@/lib/utils";
import { type BulkAction, CONTACT_STATUSES } from "./shared";

type PickerAction = "add_to_campaign" | "set_status" | "add_tag" | "dnc";

const NEW = "__new__";

const TITLES: Record<PickerAction, string> = {
  add_to_campaign: "Add to campaign",
  set_status: "Set status",
  add_tag: "Add tag",
  dnc: "Do-Not-Call",
};

export function BulkActionBar({
  ids,
  campaigns,
  onClear,
  onDone,
}: {
  ids: string[];
  campaigns: Campaign[];
  onClear: () => void;
  onDone: () => void;
}) {
  const toast = useToast();
  const [picker, setPicker] = useState<PickerAction | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [newName, setNewName] = useState("");
  const [newAgent, setNewAgent] = useState("");
  const n = ids.length;
  // Agents a new campaign can use (not the welcome demo).
  const { data: agentList } = useSWR<Agent[]>(picker === "add_to_campaign" ? "/api/agents/" : null, fetcher);
  const agents = (agentList ?? []).filter((a) => a.template !== "welcome_demo");
  const creating = picker === "add_to_campaign" && value === NEW;

  function open(a: PickerAction) {
    setPicker(a);
    setValue(a === "add_to_campaign" ? (campaigns[0]?.id ?? NEW) : a === "set_status" ? "interested" : a === "dnc" ? "dnc_on" : "");
    setNewName("");
    setNewAgent("");
  }

  async function run(action: BulkAction, extra: Record<string, string> = {}) {
    setBusy(true);
    try {
      const res = await post<{ updated: number }>("/api/contacts/bulk", { ids, action, ...extra });
      const verb = action === "delete" ? "Deleted" : "Updated";
      toast(`${verb} ${res.updated} contact${res.updated === 1 ? "" : "s"}`);
      setPicker(null);
      onClear();
      onDone();
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function createAndAdd() {
    setBusy(true);
    try {
      const c = await post<{ id: string; name: string }>("/api/campaigns/", {
        name: newName.trim(),
        agent_id: newAgent || agents[0]?.id || null,
      });
      const res = await post<{ updated: number }>("/api/contacts/bulk", { ids, action: "add_to_campaign", campaign_id: c.id });
      toast(`Created “${c.name}” with ${res.updated} contact${res.updated === 1 ? "" : "s"}. Start it from Campaigns when you're ready.`);
      setPicker(null);
      onClear();
      onDone();
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  }

  function submitPicker(e: React.FormEvent) {
    e.preventDefault();
    if (creating) {
      if (newName.trim()) void createAndAdd();
      return;
    }
    if (!picker || !value.trim()) return;
    if (picker === "dnc") return run(value as BulkAction);
    const key = picker === "add_to_campaign" ? "campaign_id" : picker === "set_status" ? "status" : "tag";
    run(picker, { [key]: value.trim() });
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-brand-200 bg-brand-50 px-3 py-2">
        <span className="mr-1 text-xs font-semibold text-brand-800">{n} selected</span>
        <Button size="sm" onClick={() => open("add_to_campaign")} disabled={busy}>
          <FolderPlus className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Add to campaign</span>
          <span className="sm:hidden">Campaign</span>
        </Button>
        <Button size="sm" onClick={() => open("set_status")} disabled={busy}>
          <CircleDot className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Set status</span>
          <span className="sm:hidden">Status</span>
        </Button>
        <Button size="sm" onClick={() => open("add_tag")} disabled={busy}>
          <Tag className="h-3.5 w-3.5" /> <span className="hidden sm:inline">Add tag</span>
          <span className="sm:hidden">Tag</span>
        </Button>
        <Button size="sm" onClick={() => open("dnc")} disabled={busy}>
          <Ban className="h-3.5 w-3.5" /> Do-Not-Call
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="text-red-600 hover:bg-red-50 hover:text-red-700"
          loading={busy && !picker}
          onClick={() => {
            if (confirm(`Delete ${n} contact${n === 1 ? "" : "s"}? Their call history is kept.`)) run("delete");
          }}
        >
          <Trash2 className="h-3.5 w-3.5" /> Delete
        </Button>
        <button onClick={onClear} className="ml-auto rounded-md p-1 text-brand-700 hover:bg-brand-100" aria-label="Clear selection">
          <X className="h-4 w-4" />
        </button>
      </div>

      <Modal open={!!picker} onClose={() => setPicker(null)} title={picker ? `${TITLES[picker]} · ${n} contact${n === 1 ? "" : "s"}` : ""}>
        <form onSubmit={submitPicker} className="space-y-4">
          {picker === "add_to_campaign" && (
            <Field label="Campaign">
              <Select value={value} onChange={(e) => setValue(e.target.value)}>
                <option value={NEW}>+ New campaign…</option>
                {campaigns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {creating && (
            <>
              <Field label="Campaign name">
                <Input value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Mortgage partners – October" autoFocus />
              </Field>
              <Field label="Agent" hint="The campaign is saved as a draft, so nobody is called until you start it.">
                <Select value={newAgent || agents[0]?.id || ""} onChange={(e) => setNewAgent(e.target.value)}>
                  {agents.length === 0 && <option value="">No agents yet: pick one later</option>}
                  {agents.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}
                    </option>
                  ))}
                </Select>
              </Field>
            </>
          )}
          {picker === "set_status" && (
            <Field label="Status">
              <Select value={value} onChange={(e) => setValue(e.target.value)}>
                {CONTACT_STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {outcomeLabel(s)}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          {picker === "dnc" && (
            <Field label="Action" hint="Contacts on the Do-Not-Call list are skipped by every campaign and can't be called directly.">
              <Select value={value} onChange={(e) => setValue(e.target.value)}>
                <option value="dnc_on">Add to Do-Not-Call</option>
                <option value="dnc_off">Remove from Do-Not-Call</option>
              </Select>
            </Field>
          )}
          {picker === "add_tag" && (
            <Field label="Tag">
              <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="e.g. vip" autoFocus />
            </Field>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" onClick={() => setPicker(null)}>
              Cancel
            </Button>
            <Button variant="primary" loading={busy} disabled={creating ? !newName.trim() : !value.trim()}>
              {creating ? "Create & add" : "Apply"}
            </Button>
          </div>
        </form>
      </Modal>
    </>
  );
}
