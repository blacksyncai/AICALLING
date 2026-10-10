// Run: node --experimental-strip-types src/components/ui/contribution-skyline-model.test.mjs
// (Node 22.6+; no test framework or extra dependencies needed.)
import assert from "node:assert/strict"
import { test } from "node:test"
import {
  buildGrid,
  computeStats,
  dayMs,
  DAY_MS,
  levelOf,
  monthLabels,
  resolvePalette,
  toKey,
  weekdayLabels,
} from "./contribution-skyline-model.ts"

const END = dayMs("2026-10-10") // a Saturday

test("a 30-day range shows exactly those 30 days, aligned to week columns", () => {
  const start = END - 29 * DAY_MS // 2026-09-11, a Friday
  const g = buildGrid([], END, 0, start)
  assert.equal(g.cells.length, 30)
  assert.equal(g.cells[0].date, "2026-09-11")
  assert.equal(g.cells.at(-1).date, "2026-10-10")
  assert.equal(g.cells[0].week, 0)
  assert.equal(g.cells[0].day, 5) // Friday row when weeks start on Sunday
  assert.equal(g.cells[2].day, 0) // Sunday starts week 1
  assert.equal(g.cells[2].week, 1)
  assert.equal(g.weeks, 5)
  assert.equal(g.max, 0)
  assert.ok(g.cells.every((c) => c.level === 0 && c.count === 0))
  // contiguous: index ±7 is the same weekday a week apart (keyboard navigation relies on it)
  for (let i = 7; i < g.cells.length; i++) {
    assert.equal(g.cells[i].day, g.cells[i - 7].day)
    assert.equal(g.cells[i].week, g.cells[i - 7].week + 1)
  }
})

test("Monday-first weeks shift the rows", () => {
  const g = buildGrid([], END, 1, END - 29 * DAY_MS)
  assert.equal(g.cells[0].day, 4) // Friday is row 4 when Monday is row 0
  assert.deepEqual(weekdayLabels(1).map((r) => r.day), [0, 2, 4])
  assert.deepEqual(weekdayLabels(0).map((r) => [r.day, r.label]), [[1, "Mon"], [3, "Wed"], [5, "Fri"]])
})

test("default range is a year; oversized ranges are clamped", () => {
  assert.equal(buildGrid([], END).cells.length, 365)
  assert.equal(buildGrid([], END, 0, END - 5000 * DAY_MS).cells.length, 371)
  assert.equal(buildGrid([], END, 0, END + 3 * DAY_MS).cells.length, 1)
})

test("counts land on their day, repeated dates add up, out-of-range and junk are ignored", () => {
  const data = [
    { date: "2026-10-01", count: 3 },
    { date: "2026-10-01", count: 2 },
    { date: "2026-10-09", count: 10 },
    { date: "2026-08-01", count: 99 }, // before the range
    { date: "2026-10-11", count: 99 }, // after the range
    { date: "2026-10-02", count: -4 },
    { date: "nope", count: 5 },
  ]
  const g = buildGrid(data, END, 0, END - 29 * DAY_MS)
  const by = Object.fromEntries(g.cells.map((c) => [c.date, c]))
  assert.equal(by["2026-10-01"].count, 5)
  assert.equal(by["2026-10-09"].count, 10)
  assert.equal(by["2026-10-02"].count, 0)
  assert.equal(g.max, 10)
  const s = computeStats(g.cells)
  assert.equal(s.total, 15)
  assert.deepEqual(s.busiest, { count: 10, date: "2026-10-09" })
  assert.equal(s.longest.days, 1)
  assert.equal(s.first, "2026-09-11")
  assert.equal(s.last, "2026-10-10")
})

test("levels use the 95th percentile so one huge day doesn't flatten the rest", () => {
  const data = []
  for (let i = 0; i < 40; i++) data.push({ date: toKey(END - i * DAY_MS), count: 4 })
  data.push({ date: toKey(END - 50 * DAY_MS), count: 400 })
  const g = buildGrid(data, END, 0, END - 89 * DAY_MS)
  assert.equal(g.busy, 4)
  const by = Object.fromEntries(g.cells.map((c) => [c.date, c]))
  assert.equal(by[toKey(END)].level, 4)
  assert.equal(by[toKey(END - 50 * DAY_MS)].level, 4)
  assert.equal(levelOf(0, 4), 0)
  assert.equal(levelOf(1, 4), 2)
  assert.equal(levelOf(1, 8), 1)
  assert.equal(levelOf(5, 0), 4)
})

test("streaks", () => {
  const days = ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-06", "2026-10-09"].map((d) => ({ date: d, count: 1 }))
  const s = computeStats(buildGrid(days, END, 0, END - 29 * DAY_MS).cells)
  assert.deepEqual(s.longest, { days: 3, start: "2026-10-01", end: "2026-10-03" })
  // today (10-10) is empty, so the current run is the one ending yesterday
  assert.deepEqual(s.current, { days: 1, start: "2026-10-09", end: "2026-10-09" })
})

test("month labels follow the first shown day of each week", () => {
  const g = buildGrid([], END, 0, END - 89 * DAY_MS) // 2026-07-13 → 2026-10-10
  const labels = monthLabels(g.cells, g.weeks)
  assert.deepEqual(labels.map((l) => l.label), ["Jul", "Aug", "Sep", "Oct"])
  assert.equal(labels[0].week, 0)
})

test("BlackSync palette is the default, with distinct light and dark sets", () => {
  const light = resolvePalette(undefined, false)
  const dark = resolvePalette(undefined, true)
  assert.equal(light.length, 4)
  assert.equal(light[2], "#dc4a1e")
  assert.notDeepEqual(light, dark)
  assert.deepEqual(resolvePalette(["#000"], false), ["#000", "#000", "#000", "#000"])
})

test("no sample-data generator is exported", async () => {
  const mod = await import("./contribution-skyline-model.ts")
  assert.equal(mod.generateContributions, undefined)
  assert.equal(mod.rng, undefined)
})
