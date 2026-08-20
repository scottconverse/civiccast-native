import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getAnalyticsReport } from '../api/client'
import type {
  AnalyticsDimensionCount,
  AnalyticsReport,
  AssetViewPoint,
  LiveConcurrentPoint,
} from '../types/api.generated'

const RANGE_OPTIONS = [7, 30, 90]

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

function Stat({
  label,
  value,
  detail,
}: {
  label: string
  value: string
  detail: string
}) {
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

function DimensionTable({
  title,
  rows,
}: {
  title: string
  rows: AnalyticsDimensionCount[]
}) {
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
              <tr><td className="px-3 py-3 text-sm" colSpan={2} style={{ color: 'var(--cc-ink-3)' }}>No data yet</td></tr>
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
              <tr><td className="px-3 py-3 text-sm" colSpan={4} style={{ color: 'var(--cc-ink-3)' }}>No playback data yet</td></tr>
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
              <tr><td className="px-3 py-3 text-sm" colSpan={5} style={{ color: 'var(--cc-ink-3)' }}>No live samples yet</td></tr>
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
  const [rangeDays, setRangeDays] = useState(30)
  const reportQuery = useQuery({
    queryKey: ['analytics-report', rangeDays],
    queryFn: () => getAnalyticsReport(rangeDays),
  })

  return (
    <div className="min-h-full px-5 py-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Analytics</h1>
          <p className="mt-1 text-sm" style={{ color: 'var(--cc-ink-3)' }}>
            Aggregate station reporting for grants, franchise updates, and operator planning.
          </p>
        </div>
        <div className="flex rounded-md" style={{ border: '1px solid var(--cc-line)' }}>
          {RANGE_OPTIONS.map((days) => (
            <button
              key={days}
              type="button"
              onClick={() => setRangeDays(days)}
              className="px-3 py-2 text-sm"
              style={{
                background: rangeDays === days ? 'var(--cc-brand-soft)' : 'transparent',
                color: rangeDays === days ? 'var(--cc-brand-2)' : 'var(--cc-ink-2)',
                borderRight: days === RANGE_OPTIONS[RANGE_OPTIONS.length - 1] ? '0' : '1px solid var(--cc-line)',
              }}
            >
              {days}d
            </button>
          ))}
        </div>
      </header>

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
      {reportQuery.data && <ReportBody report={reportQuery.data} />}
    </div>
  )
}
