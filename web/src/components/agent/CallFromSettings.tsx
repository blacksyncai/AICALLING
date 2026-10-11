"use client";

import Link from "next/link";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import type { Agent, MyPhoneNumbers } from "@/lib/types";
import { Field, Select, Toggle } from "../ui";

/** Agent editor: which of the account's numbers the agent calls from, and whether calls are recorded. */
export function CallFromSettings({ draft, set }: { draft: Agent; set: <K extends keyof Agent>(key: K, value: Agent[K]) => void }) {
  const { data } = useSWR<MyPhoneNumbers>("/api/phone-numbers", fetcher);
  const numbers = data?.numbers ?? [];
  const fallback = numbers.find((n) => n.is_default) ?? numbers[0];

  return (
    <div className="space-y-5">
      <Field
        label="Call from"
        hint={
          numbers.length ? (
            "The caller ID people see when this agent calls them."
          ) : (
            <>
              This account has no phone numbers yet, so calls use the platform line.{" "}
              <Link href="/phone-numbers" className="font-medium underline">
                Get a number
              </Link>
            </>
          )
        }
      >
        <Select value={draft.caller_number ?? ""} onChange={(e) => set("caller_number", e.target.value)} disabled={!numbers.length}>
          <option value="">{fallback ? `Account default (${fallback.number})` : "Platform line"}</option>
          {numbers.map((n) => (
            <option key={n.id} value={n.number}>
              {n.number}
              {n.label ? ` · ${n.label}` : ""}
            </option>
          ))}
        </Select>
      </Field>
      <Toggle
        checked={draft.record_calls ?? true}
        onChange={(v) => set("record_calls", v)}
        label="Record phone calls"
        description={
          data && !data.recordings_enabled
            ? "Recording storage isn't set up yet — calls won't be recorded until it is."
            : "Saves the audio of each answered call to its call log. Some states require telling callers the call is recorded — add it to the opening line if needed."
        }
      />
    </div>
  );
}
