import { Badge } from "./ui";
import { OUTCOME_TONE, REASON_LABELS, humanize, outcomeLabel } from "@/lib/utils";

/** A call's result. With a reason ("Already sold"), the reason is shown instead of a generic "Not interested". */
export function OutcomeBadge({ outcome, status, reason }: { outcome: string | null; status?: string; reason?: string | null }) {
  if (!outcome) {
    const live = status && ["initiated", "ringing", "connected"].includes(status);
    return <Badge tone={live ? "brand" : "gray"}>{live ? "In progress" : humanize(status)}</Badge>;
  }
  const why = reason ? REASON_LABELS[reason] : undefined;
  return (
    <Badge tone={OUTCOME_TONE[outcome] ?? "gray"}>
      <span title={why ? outcomeLabel(outcome) : undefined}>{why ?? outcomeLabel(outcome)}</span>
    </Badge>
  );
}
