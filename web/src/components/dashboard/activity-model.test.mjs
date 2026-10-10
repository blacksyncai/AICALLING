// Run: node --experimental-strip-types src/components/dashboard/activity-model.test.mjs
import assert from "node:assert/strict"
import { test } from "node:test"
import { dayHref, formatDay, metricInfo, rangeInfo, timeZoneLabel } from "./activity-model.ts"

test("clicking a day opens that day's phone calls, with the agent", () => {
  assert.equal(dayHref("2026-10-03", "calls"), "/calls?date=2026-10-03&call_type=outbound")
  assert.equal(dayHref("2026-10-03", "connected", "a1"), "/calls?date=2026-10-03&agent_id=a1&call_type=outbound")
  assert.equal(dayHref("2026-10-03", "credits", ""), "/calls?date=2026-10-03&call_type=outbound")
})

test("appointments and transfers add the matching outcome filter", () => {
  assert.equal(dayHref("2026-10-03", "appointments", "a1"), "/calls?date=2026-10-03&agent_id=a1&outcome=meeting_booked&call_type=outbound")
  assert.equal(dayHref("2026-10-03", "transfers"), "/calls?date=2026-10-03&outcome=transferred&call_type=outbound")
})

test("labels", () => {
  assert.equal(metricInfo("appointments").unitPlural, "appointments")
  assert.equal(rangeInfo("30d").label, "last 30 days")
  assert.equal(formatDay("2026-10-03"), "Oct 3, 2026")
  assert.equal(formatDay("2026-01-01", { month: "short", day: "numeric" }), "Jan 1")
  assert.equal(timeZoneLabel("America/New_York"), "Eastern Time")
  assert.equal(timeZoneLabel("Not/AZone"), "Not/AZone")
})
