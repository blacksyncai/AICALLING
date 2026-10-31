import type { ResponseAnalysis } from "@/lib/types";
import { humanize, outcomeLabel } from "@/lib/utils";
import { Badge, Card, CardHeader } from "@/components/ui";

const ACTIONS: Record<string, string> = { none_agreed: "No next step agreed", callback_requested: "Callback requested",
  send_information: "Send requested information", meeting_booked: "Meeting booked", human_review: "Human review needed" };

export function ResponseReview({ review }: { review: ResponseAnalysis | null | undefined }) {
  if (!review?.version) return null;
  return <Card>
    <CardHeader title="Response & next step" description="What the contact said, separate from what happens next." />
    <div className="grid gap-5 p-5 sm:grid-cols-2">
      <div className="space-y-2"><p className="text-xs font-medium text-zinc-400">Response</p><h3 className="text-sm font-semibold">{outcomeLabel(review.response)}</h3>
        <Badge tone={review.certainty === "clear" ? "blue" : "amber"}>{humanize(review.certainty)} evidence</Badge>
        {review.evidence_quote ? <blockquote className="border-l-2 border-brand-300 pl-3 text-sm text-zinc-600">“{review.evidence_quote}”</blockquote> : <p className="text-xs text-zinc-400">No clear decision evidenced.</p>}
        <p className="text-xs text-zinc-400">Responding to: {humanize(review.response_scope)}</p>
      </div>
      <div className="space-y-2"><p className="text-xs font-medium text-zinc-400">Agreed next step</p><h3 className="text-sm font-semibold">{ACTIONS[review.next_action] ?? humanize(review.next_action)}</h3>
        {review.channel && <p className="text-xs text-zinc-500">Via {review.channel}{review.timeline ? ` · ${review.timeline}` : ""}</p>}
        {review.next_action_quote && <blockquote className="border-l-2 border-zinc-200 pl-3 text-sm text-zinc-600">“{review.next_action_quote}”</blockquote>}
        {review.meeting_response !== "not_discussed" && <p className="text-xs text-zinc-500">Meeting: {humanize(review.meeting_response)}</p>}
      </div>
    </div>
  </Card>;
}
