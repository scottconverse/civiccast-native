import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  downloadAnalyticsRollupsCsv,
  generateAnalyticsBoardPdf,
  getAnalyticsReport,
  getAnalyticsRollups,
} from '../api/client'
import type {
  AnalyticsDimensionCount,
  AnalyticsReport,
  AssetViewPoint,
  BoardPdfInclude,
  LiveConcurrentPoint,
  RollupsResponse,
  ViewershipRollupPoint,
} from '../types/api.generated'
import { RollupChart, type ChartDatum } from '../components/analytics/RollupChart'

type RangePreset = 7 | 30 | 90 | 365
type StreamTypeFilter = 'vod' | 'live' | 'all'
type ChartType = 'bar' | 'line'
type Metric = 'viewer_count' | 'time_viewed' | 'peak_concurrent'

const RANGE_PRESETS: { value: RangePreset; label: string }[] = [
  { value: 7, label: '7d' },
  { value: 30, label: '30d' },
  { value: 90, label: 'Quarter' },
  { value: 365, label: 'Year' },
]

const METRIC_LABELS: Record<Metric, string> = {
  viewer_count: 'Viewer Count',
  time_viewed: 'Time Viewed',
  peak_concurrent: 'Peak Concurrent',
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function numberFormat(value: number): string {
  return new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)
}

function totalAssetViews(points: AssetViewPoint[]): number {
  return points.reduce((sum, point) => sum + point.views, 0)
}

function totalViewHours(points: AssetViewPoint[]): number {
  const seconds = points.reduce((sum, point) => sum + point.view_seconds, 0)
  return seconds / 3600
}

function peakConcurrent(points: LiveConcurrentPoint[]): number {
  return points.reduce((peak, point) => Math.max(peak, point.peak_concurrent_viewers), 0)
}

function metricValue(point: ViewershipRollupPoint, metric: Metric): number {
  if (metric === 'viewer_count') return point.viewer_count
  if (metric === 'time_viewed') return Math.round((point.time_viewed_seconds / 3600) * 100) / 100
  return point.peak_concurrent ?? 0
}

function bucketLabel(iso: string, bucketKind: string): string {
  const date = new Date(iso)
  if (bucketKind === 'day') {
    return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
  }
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

function toBarData(rollups: ViewershipRollupPoint[], metric: Metric): ChartDatum[] {
  const totals = new Map<string, number>()
  for (const point of rollups) {
    totals.set(point.subject_id, (totals.get(point.subject_id) ?? 0) + metricValue(point, metric))
  }
  return Array.from(totals.entries())
    .map(([label, value]) => ({ label, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 10)
}

function toTimeSeriesData(rollups: ViewershipRollupPoint[], metric: Metric): ChartDatum[] {
  const totals = new Map<string, number>()
  const bucketKind = rollups[0]?.bucket_kind ?? 'day'
  for (const point of rollups) {
    const key = point.bucket_start
    totals.set(key, (totals.get(key) ?? 0) + metricValue(point, metric))
  }
  return Array.from(totals.entries())
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([iso, value]) => ({ label: bucketLabel(iso, bucketKind), value }))
}

function Stat({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div
      className="rounded-md px-4 py-3"
      style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
    >
      <div className="text-xs font-medium" style={{ color: 'var(--cc-ink-3)' }}>{label}</div>
      <div className="cc-tabular mt-1 text-2xl font-semibold">{value}</div>
      <div className="mt-1 text-xs" style={{ color: 'var(--cc-ink-3)' }}>{detail}</div>
    </div>
  )
}

function DimensionTable({ title, rows }: { title: string; rows: AnalyticsDimensionCount[] }) {
  return (
    <section className="min-w-0">
      <h2 className="text-sm font-semibold">{title}</h2>
      <div className="mt-2 overflow-hidden rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
        <table className="w-full text-left text-sm">
          <thead style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
            <tr>
              <th className="px-3 py-2 font-medium">Segment</th>
              <th className="px-3 py-2 text-right font-medium">Count</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td className="px-3 py-3 text-sm" colSpan={2} style={{ color: 'var(--cc-ink-3)' }}>No viewer data yet — rows appear once residents start watching this station.</td></tr>
            ) : rows.map((row) => (
              <tr key={`${row.dimension}:${row.key}`} style={{ borderTop: '1px solid var(--cc-line)' }}>
                <td className="px-3 py-2">{row.key}</td>
                <td className="cc-tabular px-3 py-2 text-right">{row.count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function AssetTable({ rows }: { rows: AssetViewPoint[] }) {
  return (
    <section>
      <h2 className="text-sm font-semibold">Asset Time Series</h2>
      <div className="mt-2 overflow-hidden rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
        <table className="w-full text-left text-sm">
          <thead style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
            <tr>
              <th className="px-3 py-2 font-medium">Asset</th>
              <th className="px-3 py-2 font-medium">Day</th>
              <th className="px-3 py-2 text-right font-medium">Views</th>
              <th className="px-3 py-2 text-right font-medium">Hours</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td className="px-3 py-3 text-sm" colSpan={4} style={{ color: 'var(--cc-ink-3)' }}>No playback data yet — rows appear once published recordings get their first views.</td></tr>
            ) : rows.map((row) => (
              <tr key={`${row.content_id}:${row.day}`} style={{ borderTop: '1px solid var(--cc-line)' }}>
                <td className="px-3 py-2">{row.content_id}</td>
                <td className="cc-tabular px-3 py-2">{row.day}</td>
                <td className="cc-tabular px-3 py-2 text-right">{row.views}</td>
                <td className="cc-tabular px-3 py-2 text-right">{numberFormat(row.view_seconds / 3600)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function LiveTable({ rows }: { rows: LiveConcurrentPoint[] }) {
  return (
    <section>
      <h2 className="text-sm font-semibold">Live Concurrent Viewers</h2>
      <div className="mt-2 overflow-hidden rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
        <table className="w-full text-left text-sm">
          <thead style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
            <tr>
              <th className="px-3 py-2 font-medium">Channel</th>
              <th className="px-3 py-2 font-medium">Day</th>
              <th className="px-3 py-2 text-right font-medium">Peak</th>
              <th className="px-3 py-2 text-right font-medium">Average</th>
              <th className="px-3 py-2 text-right font-medium">Samples</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr><td className="px-3 py-3 text-sm" colSpan={5} style={{ color: 'var(--cc-ink-3)' }}>No live samples yet — rows appear after this station's first live stream.</td></tr>
            ) : rows.map((row) => (
              <tr key={`${row.channel_id}:${row.day}`} style={{ borderTop: '1px solid var(--cc-line)' }}>
                <td className="px-3 py-2">{row.channel_id}</td>
                <td className="cc-tabular px-3 py-2">{row.day}</td>
                <td className="cc-tabular px-3 py-2 text-right">{row.peak_concurrent_viewers}</td>
                <td className="cc-tabular px-3 py-2 text-right">{numberFormat(row.average_concurrent_viewers)}</td>
                <td className="cc-tabular px-3 py-2 text-right">{row.samples}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function TelemetryOffBanner() {
  return (
    <div
      role="status"
      className="rounded-md px-4 py-3 text-sm"
      style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}
    >
      <div className="font-medium">Audience telemetry is off</div>
      <div className="mt-1" style={{ color: 'var(--cc-ink-3)' }}>
        Turn it on in Setup to collect Viewer Count and Time Viewed. The Reports tab (as-run /
        proof-of-performance) still works — it reads the program log, not the beacon.
      </div>
    </div>
  )
}

function RollupPanel({
  title,
  data,
  chartType,
  metric,
  streamType,
  stats,
  isLoading,
}: {
  title: string
  data: RollupsResponse | undefined
  chartType: ChartType
  metric: Metric
  streamType: 'vod' | 'live'
  stats: RollupsResponse['stats'] | undefined
  isLoading: boolean
}) {
  const rollups = useMemo(() => data?.rollups ?? [], [data])
  const barData = useMemo(() => toBarData(rollups, metric), [rollups, metric])
  const seriesData = useMemo(() => toTimeSeriesData(rollups, metric), [rollups, metric])
  const metricUnavailable = streamType === 'vod' && metric === 'peak_concurrent'

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        {stats && (
          <div className="cc-tabular text-xs" style={{ color: 'var(--cc-ink-3)' }}>
            {numberFormat(stats.total_viewer_count)} views &middot;{' '}
            {numberFormat(stats.total_time_viewed_seconds / 3600)}h watched
            {stats.peak_concurrent != null ? ` · peak ${stats.peak_concurrent}` : ''}
          </div>
        )}
      </div>
      {metricUnavailable ? (
        <div
          className="rounded-md px-4 py-3 text-sm"
          style={{ border: '1px dashed var(--cc-line)', color: 'var(--cc-ink-3)' }}
        >
          Peak Concurrent applies to live streams only.
        </div>
      ) : isLoading ? (
        <div className="rounded-md px-4 py-3 text-sm" style={{ border: '1px solid var(--cc-line)' }}>
          Loading…
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <div className="mb-1 text-xs font-medium" style={{ color: 'var(--cc-ink-3)' }}>
              Top by {METRIC_LABELS[metric]}
            </div>
            <RollupChart data={barData} chartType="bar" valueLabel={METRIC_LABELS[metric]} />
          </div>
          <div>
            <div className="mb-1 text-xs font-medium" style={{ color: 'var(--cc-ink-3)' }}>
              {METRIC_LABELS[metric]} over time
            </div>
            <RollupChart
              data={seriesData}
              chartType={chartType}
              valueLabel={METRIC_LABELS[metric]}
            />
          </div>
        </div>
      )}
    </div>
  )
}

function RollupTable({ rollups }: { rollups: ViewershipRollupPoint[] }) {
  return (
    <div className="mt-2 overflow-hidden rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
      <table className="w-full text-left text-sm">
        <thead style={{ background: 'var(--cc-surface-2)', color: 'var(--cc-ink-3)' }}>
          <tr>
            <th className="px-3 py-2 font-medium">Stream</th>
            <th className="px-3 py-2 font-medium">Bucket</th>
            <th className="px-3 py-2 font-medium">Subject</th>
            <th className="px-3 py-2 text-right font-medium">Viewer Count</th>
            <th className="px-3 py-2 text-right font-medium">Time Viewed (h)</th>
            <th className="px-3 py-2 text-right font-medium">Peak Concurrent</th>
          </tr>
        </thead>
        <tbody>
          {rollups.length === 0 ? (
            <tr><td className="px-3 py-3 text-sm" colSpan={6} style={{ color: 'var(--cc-ink-3)' }}>No rollup rows for this range — pick a wider range, or check back after the station has aired content.</td></tr>
          ) : rollups.map((row, i) => (
            <tr key={`${row.stream_type}:${row.bucket_kind}:${row.subject_id}:${row.bucket_start}:${i}`} style={{ borderTop: '1px solid var(--cc-line)' }}>
              <td className="px-3 py-2">{row.stream_type}</td>
              <td className="cc-tabular px-3 py-2">{new Date(row.bucket_start).toLocaleString()}</td>
              <td className="px-3 py-2">{row.subject_id}</td>
              <td className="cc-tabular px-3 py-2 text-right">{row.viewer_count}</td>
              <td className="cc-tabular px-3 py-2 text-right">{numberFormat(row.time_viewed_seconds / 3600)}</td>
              <td className="cc-tabular px-3 py-2 text-right">{row.peak_concurrent ?? '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const DEFAULT_PDF_INCLUDE: Required<BoardPdfInclude> = {
  totals: true,
  top_content: true,
  yoy: true,
  live_peaks: true,
}

function BoardPdfControls({ rangeDays }: { rangeDays: RangePreset }) {
  const [open, setOpen] = useState(false)
  const [include, setInclude] = useState<Required<BoardPdfInclude>>(DEFAULT_PDF_INCLUDE)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleGenerate() {
    setBusy(true)
    setError(null)
    try {
      const now = new Date()
      const rangeStart = new Date(now.getTime() - rangeDays * 24 * 60 * 60 * 1000)
      const blob = await generateAnalyticsBoardPdf({
        range_start: rangeStart.toISOString(),
        range_end: now.toISOString(),
        include,
        station_label: 'CivicCast station',
      })
      saveBlob(blob, `audience-report-${now.toISOString().slice(0, 10)}.pdf`)
      setOpen(false)
    } catch {
      setError('Could not generate the board PDF. Try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="rounded-md px-3 py-2 text-sm font-medium"
        style={{ background: 'var(--cc-brand-soft)', color: 'var(--cc-brand-2)' }}
        aria-expanded={open}
      >
        Generate Board PDF
      </button>
      {open && (
        <div
          className="absolute right-0 z-10 mt-2 w-64 rounded-md p-3 text-sm"
          style={{ background: 'var(--cc-surface-1, #fff)', border: '1px solid var(--cc-line)' }}
        >
          <div className="mb-2 font-medium">Include sections</div>
          {(
            [
              ['totals', 'Totals'],
              ['top_content', 'Top content'],
              ['yoy', 'Year-over-year'],
              ['live_peaks', 'Live-event peaks'],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="mb-1 flex items-center gap-2">
              <input
                type="checkbox"
                checked={include[key]}
                onChange={(e) => setInclude((prev) => ({ ...prev, [key]: e.target.checked }))}
              />
              {label}
            </label>
          ))}
          {error && <div className="mt-1 text-xs" style={{ color: 'var(--cc-danger, #b42318)' }}>{error}</div>}
          <button
            type="button"
            onClick={handleGenerate}
            disabled={busy}
            className="mt-2 w-full rounded-md px-3 py-2 text-sm font-medium"
            style={{ background: 'var(--cc-brand-2, #2563eb)', color: '#fff' }}
          >
            {busy ? 'Generating…' : 'Download PDF'}
          </button>
        </div>
      )}
    </div>
  )
}

function ReportBody({ report }: { report: AnalyticsReport }) {
  const assetViews = report.asset_views ?? []
  const liveConcurrent = report.live_concurrent_viewers ?? []
  const podcastDownloads = report.podcast_downloads ?? []
  const generatedAt = useMemo(
    () => new Date(report.generated_at).toLocaleString(),
    [report.generated_at],
  )

  return (
    <div className="space-y-5">
      <div className="grid gap-3 md:grid-cols-4">
        <Stat label="Asset views" value={String(totalAssetViews(assetViews))} detail={`${report.range_days} day window`} />
        <Stat label="View hours" value={numberFormat(totalViewHours(assetViews))} detail="Aggregate playback time" />
        <Stat label="Live peak" value={String(peakConcurrent(liveConcurrent))} detail="Highest reported sample" />
        <Stat label="Podcast downloads" value={String(podcastDownloads.reduce((sum, row) => sum + row.count, 0))} detail="Aggregate episode count" />
      </div>

      <div className="rounded-md px-4 py-3 text-sm" style={{ background: 'var(--cc-surface-2)', border: '1px solid var(--cc-line)' }}>
        <div className="font-medium">Privacy boundary</div>
        <div className="mt-1" style={{ color: 'var(--cc-ink-3)' }}>{report.privacy_boundary}</div>
        <div className="mt-2 text-xs" style={{ color: 'var(--cc-ink-3)' }}>Generated {generatedAt}</div>
      </div>

      <AssetTable rows={assetViews} />
      <LiveTable rows={liveConcurrent} />

      <div className="grid gap-5 lg:grid-cols-2">
        <DimensionTable title="Geography" rows={report.geography ?? []} />
        <DimensionTable title="Device" rows={report.device_breakdown ?? []} />
        <DimensionTable title="Platform" rows={report.platform_breakdown ?? []} />
        <DimensionTable title="Caption Usage" rows={report.caption_usage ?? []} />
        <DimensionTable title="Audio Usage" rows={report.audio_usage ?? []} />
        <DimensionTable title="Subscription Growth" rows={report.subscription_growth ?? []} />
      </div>
    </div>
  )
}

export function AnalyticsScreen() {
  const [rangeDays, setRangeDays] = useState<RangePreset>(30)
  const [streamType, setStreamType] = useState<StreamTypeFilter>('all')
  const [chartType, setChartType] = useState<ChartType>('bar')
  const [metric, setMetric] = useState<Metric>('viewer_count')
  const [tableExpanded, setTableExpanded] = useState(false)

  const reportQuery = useQuery({
    queryKey: ['analytics-report', rangeDays, streamType],
    queryFn: () => getAnalyticsReport(rangeDays, streamType),
  })

  const showVod = streamType === 'vod' || streamType === 'all'
  const showLive = streamType === 'live' || streamType === 'all'

  const vodRollupsQuery = useQuery({
    queryKey: ['analytics-rollups', 'vod', rangeDays],
    queryFn: () => getAnalyticsRollups({ streamType: 'vod', bucket: 'day', rangeDays, topN: 10 }),
    enabled: showVod,
  })
  const liveRollupsQuery = useQuery({
    queryKey: ['analytics-rollups', 'live', rangeDays],
    queryFn: () =>
      getAnalyticsRollups({ streamType: 'live', bucket: 'halfhour', rangeDays, topN: 10 }),
    enabled: showLive,
  })

  const allRollups = useMemo(
    () => [...(vodRollupsQuery.data?.rollups ?? []), ...(liveRollupsQuery.data?.rollups ?? [])],
    [vodRollupsQuery.data, liveRollupsQuery.data],
  )

  async function handleExportCsv() {
    const streamForExport = streamType === 'all' ? 'vod' : streamType
    const blob = await downloadAnalyticsRollupsCsv({
      streamType: streamForExport,
      bucket: streamForExport === 'vod' ? 'day' : 'halfhour',
      rangeDays,
    })
    saveBlob(blob, `analytics-rollups-${streamForExport}-${rangeDays}d.csv`)
  }

  return (
    <div className="min-h-full px-5 py-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Analytics</h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
            Aggregate station reporting for grants, franchise updates, and operator planning.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={handleExportCsv}
            className="rounded-md px-3 py-2 text-sm font-medium"
            style={{ border: '1px solid var(--cc-line)' }}
          >
            Export CSV
          </button>
          <BoardPdfControls rangeDays={rangeDays} />
        </div>
      </header>

      {/* Toolbar (S14 §5 panel 1) */}
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <div className="flex rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
          {(['bar', 'line'] as ChartType[]).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => setChartType(type)}
              className="px-3 py-2 text-sm capitalize"
              style={{
                background: chartType === type ? 'var(--cc-brand-soft)' : 'transparent',
                color: chartType === type ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
              }}
            >
              {type}
            </button>
          ))}
        </div>

        <select
          aria-label="Metric"
          value={metric}
          onChange={(e) => setMetric(e.target.value as Metric)}
          className="rounded-md px-3 py-2 text-sm"
          style={{ border: '1px solid var(--cc-line)', background: 'transparent' }}
        >
          {(Object.keys(METRIC_LABELS) as Metric[]).map((key) => (
            <option key={key} value={key}>{METRIC_LABELS[key]}</option>
          ))}
        </select>

        <div className="flex rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
          {RANGE_PRESETS.map(({ value, label }) => (
            <button
              key={value}
              type="button"
              onClick={() => setRangeDays(value)}
              className="px-3 py-2 text-sm"
              style={{
                background: rangeDays === value ? 'var(--cc-brand-soft)' : 'transparent',
                color: rangeDays === value ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
              }}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="flex rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
          {(['vod', 'live', 'all'] as StreamTypeFilter[]).map((type) => (
            <button
              key={type}
              type="button"
              onClick={() => setStreamType(type)}
              className="px-3 py-2 text-sm uppercase"
              style={{
                background: streamType === type ? 'var(--cc-brand-soft)' : 'transparent',
                color: streamType === type ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
              }}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {reportQuery.isLoading && (
        <div className="rounded-md px-4 py-3 text-sm" style={{ border: '1px solid var(--cc-line)' }}>
          Loading report...
        </div>
      )}
      {reportQuery.isError && (
        <div className="rounded-md px-4 py-3 text-sm" style={{ border: '1px solid var(--cc-danger, #b42318)' }}>
          Report unavailable.
        </div>
      )}

      {reportQuery.data && !reportQuery.data.ingest_configured && (
        <div className="mb-5"><TelemetryOffBanner /></div>
      )}

      {reportQuery.data && (
        <div className="space-y-6">
          {showVod && (
            <RollupPanel
              title="VOD"
              data={vodRollupsQuery.data}
              chartType={chartType}
              metric={metric}
              streamType="vod"
              stats={vodRollupsQuery.data?.stats}
              isLoading={vodRollupsQuery.isLoading}
            />
          )}
          {showLive && (
            <RollupPanel
              title="Live"
              data={liveRollupsQuery.data}
              chartType={chartType}
              metric={metric}
              streamType="live"
              stats={liveRollupsQuery.data?.stats}
              isLoading={liveRollupsQuery.isLoading}
            />
          )}

          {/* Panel 4: stats summary + expandable data table */}
          <div>
            <button
              type="button"
              onClick={() => setTableExpanded((v) => !v)}
              className="text-sm font-medium"
              style={{ color: 'var(--cc-brand-2)' }}
              aria-expanded={tableExpanded}
            >
              {tableExpanded ? 'Hide' : 'Show'} rollup data table ({allRollups.length} rows)
            </button>
            {tableExpanded && <RollupTable rollups={allRollups} />}
          </div>

          <ReportBody report={reportQuery.data} />
        </div>
      )}
    </div>
  )
}
