import { Badge } from "./ui";
import { OUTCOME_TONE, humanize } from "@/lib/utils";

export function OutcomeBadge({ outcome, status }: { outcome: string | null; status?: string }) {
  if (!outcome) {
    const live = status && ["initiated", "ringing", "connected"].includes(status);
    return <Badge tone={live ? "brand" : "gray"}>{live ? "In progress" : humanize(status)}</Badge>;
  }
  return <Badge tone={OUTCOME_TONE[outcome] ?? "gray"}>{humanize(outcome)}</Badge>;
}
