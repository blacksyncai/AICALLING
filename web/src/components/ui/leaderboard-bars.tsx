/**
 * LeaderboardBars — benchmark ranking bars with spread and economy columns.
 *
 * Answers "who clears the bar, with what spread, and at what cost?" in 2
 * seconds: a shared 0..max scale carries the score bars and ±std whiskers,
 * secondary metrics stay aligned at the right, and reference configurations
 * outside the competition sit below a hard rule. Wide-figure genre: the board
 * keeps a 620px minimum width and scrolls inside its own container on narrow
 * screens. Plain div rendering with serializable props; no client runtime.
 *
 * Props:
 * - rows: score rows with optional spread, display label, color, metrics, and
 *   out-of-competition treatment.
 * - columns?: right-aligned metric headers corresponding to row.metrics.
 * - barLabel? / rowLabel?: headers over the score and label columns.
 * - max?: axis ceiling (default 100).
 * - unit?: suffix on the final axis tick (default "%").
 * - ticks?: axis/grid values (default 0, 20, 40, 60, 80, 100).
 */

const MONO = 'ui-monospace, SFMono-Regular, monospace'
const METRIC_WIDTHS = [72, 56, 48]
// Color follows the entity: pass per-row `color` (vendor identity); the
// default is a neutral track tone, never an index rainbow.
const BAR_DEFAULT = 'var(--vz-axis,#d9d9d9)'

export type LeaderboardBarRow = {
  /** primary row label: "Opus 4.8" */
  label: string
  /** muted line under the label: "Claude Code" */
  sub?: string
  /** bar length on the 0..max axis */
  value: number
  /** whisker half-width; omitted means no whisker */
  std?: number
  /** formatted score; defaults to value with ±std when present */
  valueLabel?: string
  /** bar fill — pass the entity's identity color; defaults to a neutral track tone */
  color?: string
  /** cells aligned with columns; missing values render as em dashes */
  metrics?: (string | null | undefined)[]
  /** reference row rendered after the competition below a hard rule */
  offside?: boolean
  /** uppercase warning under the label: "OFF THE BOARD" */
  offsideTag?: string
}

function GridLines({ ticks, max }: { ticks: number[]; max: number }) {
  return (
    <div aria-hidden className="absolute inset-0">
      {ticks
        .filter((tick) => tick > 0 && tick < max)
        .map((tick) => (
          <span
            key={tick}
            className="absolute inset-y-0 border-l border-[var(--vz-grid,#e3e3e3)]"
            style={{ left: `${(tick / max) * 100}%` }}
          />
        ))}
    </div>
  )
}

export function LeaderboardBars({
  rows,
  columns = [],
  barLabel,
  rowLabel,
  max = 100,
  unit = '%',
  ticks = [0, 20, 40, 60, 80, 100],
}: {
  rows: LeaderboardBarRow[]
  columns?: string[]
  barLabel?: string
  rowLabel?: string
  max?: number
  unit?: string
  ticks?: number[]
}) {
  const axisMax = max > 0 ? max : 100
  const competition = rows.filter((row) => !row.offside)
  const offside = rows.filter((row) => row.offside)
  const metricWidths = columns.map((_, index) => METRIC_WIDTHS[index] ?? 64)
  const gridTemplateColumns = [
    '130px',
    'minmax(200px,1fr)',
    ...metricWidths.map((width) => `${width}px`),
  ].join(' ')
  const minWidth = Math.max(
    620,
    130 + 200 + metricWidths.reduce((sum, width) => sum + width, 0) + 12 * (columns.length + 1),
  )
  const pct = (value: number) => Math.max(0, Math.min(100, (value / axisMax) * 100))

  const renderRow = (row: LeaderboardBarRow, index: number, isOffside: boolean) => {
    const valueLabel =
      row.valueLabel ??
      (row.std == null ? String(row.value) : `${row.value.toFixed(1)} ±${row.std.toFixed(1)}`)
    const whiskerStart = row.std == null ? 0 : pct(row.value - row.std)
    const whiskerEnd = row.std == null ? 0 : pct(row.value + row.std)

    return (
      <div
        key={`${row.label}-${index}`}
        className={`grid items-center gap-x-3 ${isOffside && index === 0 ? 'border-t border-[var(--vz-ink,#111111)] pt-4' : ''}`}
        style={{ gridTemplateColumns }}
      >
        <div>
          <p className="text-[12px] font-semibold">{row.label}</p>
          {row.sub ? (
            <p className="mt-0.5 text-[9px] text-[var(--vz-text3,#5c5c5c)]">{row.sub}</p>
          ) : null}
          {isOffside && row.offsideTag ? (
            <p
              className="mt-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-[var(--vz-bad,#c41e1e)]"
              style={{ fontFamily: MONO }}
            >
              {row.offsideTag}
            </p>
          ) : null}
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)_64px] items-center gap-3">
          <div
            className="relative h-5 border-y border-[var(--vz-track,#f0f0f0)]"
            title={`${row.label} · ${valueLabel}`}
          >
            <GridLines ticks={ticks} max={axisMax} />
            <div
              className="absolute inset-y-[5px] left-0"
              style={{
                width: `${pct(row.value)}%`,
                backgroundColor: isOffside ? 'var(--vz-ink,#111111)' : (row.color ?? BAR_DEFAULT),
              }}
            />
            {!isOffside && row.std != null ? (
              <div
                className="absolute top-1/2 h-px -translate-y-1/2 bg-[var(--vz-ink,#111111)]"
                style={{ left: `${whiskerStart}%`, width: `${whiskerEnd - whiskerStart}%` }}
              >
                <span className="absolute -left-px -top-[3px] h-[7px] border-l border-[var(--vz-ink,#111111)]" />
                <span className="absolute -right-px -top-[3px] h-[7px] border-r border-[var(--vz-ink,#111111)]" />
              </div>
            ) : null}
          </div>
          <p className="text-right text-[11px] font-semibold" style={{ fontFamily: MONO }}>
            {valueLabel}
          </p>
        </div>
        {columns.map((column, metricIndex) => {
          const metric = row.metrics?.[metricIndex]
          const missing = metric == null
          return (
            <p
              key={column}
              className={`text-right text-[11px] ${missing ? 'text-[var(--vz-muted,#8a8a8a)]' : ''}`}
            >
              {missing ? '—' : metric}
            </p>
          )
        })}
      </div>
    )
  }

  return (
    <div tabIndex={0} role="region" aria-label="Number performance comparison, scroll horizontally" className="overflow-x-auto outline-none focus-visible:ring-2 focus-visible:ring-orange-500 border-y border-[var(--vz-ink,#111111)] py-5 text-[var(--vz-ink,#111111)] [font-variant-numeric:tabular-nums]">
      <div style={{ minWidth }}>
        <div
          className="grid gap-x-3 border-b border-[var(--vz-grid,#e3e3e3)] pb-2 text-[9px] uppercase tracking-[0.1em] text-[var(--vz-muted,#8a8a8a)]"
          style={{ gridTemplateColumns, fontFamily: MONO }}
        >
          <span>{rowLabel}</span>
          <span>{barLabel}</span>
          {columns.map((column) => (
            <span key={column} className="text-right">
              {column}
            </span>
          ))}
        </div>
        <div className="mt-4 space-y-5">
          {competition.map((row, index) => renderRow(row, index, false))}
          {offside.map((row, index) => renderRow(row, index, true))}
        </div>
        <div
          className="mt-5 grid gap-x-3 text-[9px] text-[var(--vz-muted,#8a8a8a)]"
          style={{ gridTemplateColumns, fontFamily: MONO }}
        >
          <span />
          <div className="flex justify-between pr-[76px]">
            {ticks.map((tick, index) => (
              <span key={`${tick}-${index}`}>
                {tick}
                {index === ticks.length - 1 ? unit : ''}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
