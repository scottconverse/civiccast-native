// SPDX-License-Identifier: Apache-2.0
// Copyright (c) The CivicCast Authors
import { useId, useMemo } from 'react'

/**
 * S14 §5 panels 2 + 3 — a dependency-free SVG bar/line chart.
 *
 * The repo carries no charting library anywhere in `portal-operator`
 * (confirmed: no recharts/chart.js/visx/d3 in package.json, and every other
 * "analytics-shaped" screen renders tables only). S14's spec explicitly
 * allows "a small dependency-free SVG chart component" when none exists, so
 * this is that component rather than a new bundle dependency.
 */

export interface ChartDatum {
  label: string
  value: number
}

const CHART_HEIGHT = 220
const CHART_PADDING = { top: 12, right: 12, bottom: 36, left: 48 }

function formatAxisValue(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)
}

export function RollupChart({
  data,
  chartType,
  valueLabel,
  emptyMessage = 'No data for this period.',
}: {
  data: ChartDatum[]
  chartType: 'bar' | 'line'
  valueLabel: string
  emptyMessage?: string
}) {
  const titleId = useId()
  const width = 640
  const innerWidth = width - CHART_PADDING.left - CHART_PADDING.right
  const innerHeight = CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom

  const maxValue = useMemo(() => Math.max(1, ...data.map((d) => d.value)), [data])

  if (data.length === 0) {
    return (
      <div
        className="flex items-center justify-center rounded-md text-sm"
        style={{
          height: CHART_HEIGHT,
          border: '1px dashed var(--cc-line)',
          color: 'var(--cc-ink-3)',
        }}
        role="img"
        aria-label={emptyMessage}
      >
        {emptyMessage}
      </div>
    )
  }

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((fraction) => Math.round(maxValue * fraction))

  return (
    <svg
      viewBox={`0 0 ${width} ${CHART_HEIGHT}`}
      role="img"
      aria-labelledby={titleId}
      className="w-full"
      style={{ maxHeight: CHART_HEIGHT }}
    >
      <title id={titleId}>{`${valueLabel} by ${chartType === 'bar' ? 'item' : 'time'}`}</title>

      {/* gridlines + y-axis labels */}
      {ticks.map((tick, tickIndex) => {
        const y =
          CHART_PADDING.top + innerHeight - (tick / maxValue) * innerHeight
        return (
          <g key={tickIndex}>
            <line
              x1={CHART_PADDING.left}
              x2={width - CHART_PADDING.right}
              y1={y}
              y2={y}
              stroke="var(--cc-line)"
              strokeWidth={1}
            />
            <text
              x={CHART_PADDING.left - 8}
              y={y + 4}
              textAnchor="end"
              fontSize={10}
              fill="var(--cc-ink-3)"
            >
              {formatAxisValue(tick)}
            </text>
          </g>
        )
      })}

      {chartType === 'bar' ? (
        <BarSeries data={data} maxValue={maxValue} innerWidth={innerWidth} innerHeight={innerHeight} />
      ) : (
        <LineSeries data={data} maxValue={maxValue} innerWidth={innerWidth} innerHeight={innerHeight} />
      )}
    </svg>
  )
}

function BarSeries({
  data,
  maxValue,
  innerWidth,
  innerHeight,
}: {
  data: ChartDatum[]
  maxValue: number
  innerWidth: number
  innerHeight: number
}) {
  const gap = 6
  const barWidth = Math.max(4, innerWidth / data.length - gap)

  return (
    <g>
      {data.map((datum, i) => {
        const barHeight = (datum.value / maxValue) * innerHeight
        const x = CHART_PADDING.left + i * (barWidth + gap)
        const y = CHART_PADDING.top + innerHeight - barHeight
        return (
          <g key={`${datum.label}-${i}`}>
            <rect
              x={x}
              y={y}
              width={barWidth}
              height={Math.max(0, barHeight)}
              fill="var(--cc-brand-2, #2563eb)"
              rx={2}
            >
              <title>{`${datum.label}: ${formatAxisValue(datum.value)}`}</title>
            </rect>
            <text
              x={x + barWidth / 2}
              y={CHART_PADDING.top + innerHeight + 14}
              textAnchor="middle"
              fontSize={9}
              fill="var(--cc-ink-3)"
            >
              {datum.label.length > 10 ? `${datum.label.slice(0, 9)}…` : datum.label}
            </text>
          </g>
        )
      })}
    </g>
  )
}

function LineSeries({
  data,
  maxValue,
  innerWidth,
  innerHeight,
}: {
  data: ChartDatum[]
  maxValue: number
  innerWidth: number
  innerHeight: number
}) {
  const stepX = data.length > 1 ? innerWidth / (data.length - 1) : 0
  const points = data.map((datum, i) => {
    const x = CHART_PADDING.left + i * stepX
    const y = CHART_PADDING.top + innerHeight - (datum.value / maxValue) * innerHeight
    return { x, y, datum }
  })
  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
  const labelStride = Math.max(1, Math.ceil(points.length / 8))

  return (
    <g>
      <path d={path} fill="none" stroke="var(--cc-brand-2, #2563eb)" strokeWidth={2} />
      {points.map((p, i) => (
        <circle key={i} cx={p.x} cy={p.y} r={2.5} fill="var(--cc-brand-2, #2563eb)">
          <title>{`${p.datum.label}: ${formatAxisValue(p.datum.value)}`}</title>
        </circle>
      ))}
      {points
        .filter((_, i) => i % labelStride === 0)
        .map((p, i) => (
          <text
            key={i}
            x={p.x}
            y={CHART_PADDING.top + innerHeight + 14}
            textAnchor="middle"
            fontSize={9}
            fill="var(--cc-ink-3)"
          >
            {p.datum.label}
          </text>
        ))}
    </g>
  )
}
