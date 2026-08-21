import {
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router'
import { lazy, Suspense, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Layout, MAIN_CONTENT_ID } from './components/shell/Layout'
import type { RoleName } from './components/shell/Sidebar'
import { SampleSeedNotice } from './components/SampleSeedNotice'
import { ApiError, getStaffIdentity } from './api/client'
import type { StaffIdentityResponse } from './types/api.generated'
import { ToastProvider } from './components/Toast'
import { isTrimEditorRoute, routeForPath, routePath } from './routes'
import { SetupScreen } from './screens/SetupScreen'
import { TrimEditorScreen } from './screens/TrimEditorScreen'

const AgendasScreen = lazy(() => import('./screens/AgendasScreen').then((module) => ({ default: module.AgendasScreen })))
const AssetsScreen = lazy(() => import('./screens/AssetsScreen').then((module) => ({ default: module.AssetsScreen })))
const AssetDetailScreen = lazy(() => import('./screens/AssetDetailScreen').then((module) => ({ default: module.AssetDetailScreen })))
const ActivityPubScreen = lazy(() => import('./screens/ActivityPubScreen').then((module) => ({ default: module.ActivityPubScreen })))
const AiModelsScreen = lazy(() => import('./screens/AiModelsScreen').then((module) => ({ default: module.AiModelsScreen })))
const AlertsScreen = lazy(() => import('./screens/AlertsScreen').then((module) => ({ default: module.AlertsScreen })))
const AnalyticsScreen = lazy(() => import('./screens/AnalyticsScreen').then((module) => ({ default: module.AnalyticsScreen })))
const AppAdminScreen = lazy(() => import('./screens/AppAdminScreen').then((module) => ({ default: module.AppAdminScreen })))
const AutoScheduleScreen = lazy(() => import('./screens/AutoScheduleScreen').then((module) => ({ default: module.AutoScheduleScreen })))
const CgBoardScreen = lazy(() => import('./screens/CgBoardScreen').then((module) => ({ default: module.CgBoardScreen })))
const CgBoardDesignerScreen = lazy(() => import('./screens/CgBoardDesignerScreen').then((module) => ({ default: module.CgBoardDesignerScreen })))
const ChannelOpsScreen = lazy(() => import('./screens/ChannelOpsScreen').then((module) => ({ default: module.ChannelOpsScreen })))
const ContributeScreen = lazy(() => import('./screens/ContributeScreen').then((module) => ({ default: module.ContributeScreen })))
const ControlRoomScreen = lazy(() => import('./screens/ControlRoomScreen').then((module) => ({ default: module.ControlRoomScreen })))
const ControlRoomSetupScreen = lazy(() => import('./screens/ControlRoomSetupScreen').then((module) => ({ default: module.ControlRoomSetupScreen })))
const CustomFieldsScreen = lazy(() => import('./screens/CustomFieldsScreen').then((module) => ({ default: module.CustomFieldsScreen })))
const EasScreen = lazy(() => import('./screens/EasScreen').then((module) => ({ default: module.EasScreen })))
const EpgExportScreen = lazy(() => import('./screens/EpgExportScreen').then((module) => ({ default: module.EpgExportScreen })))
const FacilityRouterScreen = lazy(() => import('./screens/FacilityRouterScreen').then((module) => ({ default: module.FacilityRouterScreen })))
const RemoteContributionScreen = lazy(() => import('./screens/RemoteContributionScreen').then((module) => ({ default: module.RemoteContributionScreen })))
const LiveRoomScreen = lazy(() => import('./screens/LiveRoomScreen').then((module) => ({ default: module.LiveRoomScreen })))
const ProgramGuideScreen = lazy(() => import('./screens/ProgramGuideScreen').then((module) => ({ default: module.ProgramGuideScreen })))
const PublishDashboardScreen = lazy(() => import('./screens/PublishDashboardScreen').then((module) => ({ default: module.PublishDashboardScreen })))
const PlaybackPolicyScreen = lazy(() => import('./screens/PlaybackPolicyScreen').then((module) => ({ default: module.PlaybackPolicyScreen })))
const ReportsScreen = lazy(() => import('./screens/ReportsScreen').then((module) => ({ default: module.ReportsScreen })))
const PaywallScreen = lazy(() => import('./screens/PaywallScreen').then((module) => ({ default: module.PaywallScreen })))
const RecordingScreen = lazy(() => import('./screens/RecordingScreen').then((module) => ({ default: module.RecordingScreen })))
const UnderwritingScreen = lazy(() => import('./screens/UnderwritingScreen').then((module) => ({ default: module.UnderwritingScreen })))
const ReviewQueueScreen = lazy(() => import('./screens/ReviewQueueScreen').then((module) => ({ default: module.ReviewQueueScreen })))
const ScheduleScreen = lazy(() => import('./screens/ScheduleScreen').then((module) => ({ default: module.ScheduleScreen })))
const SummaryReviewScreen = lazy(() => import('./screens/SummaryReviewScreen').then((module) => ({ default: module.SummaryReviewScreen })))
const SystemHealthScreen = lazy(() => import('./screens/SystemHealthScreen').then((module) => ({ default: module.SystemHealthScreen })))
const StationProfileScreen = lazy(() => import('./screens/StationProfileScreen').then((module) => ({ default: module.StationProfileScreen })))
const CommissioningWizardScreen = lazy(() => import('./screens/CommissioningWizardScreen').then((module) => ({ default: module.CommissioningWizardScreen })))

function AssetsRoute() {
  const navigate = useNavigate()
  return (
    <AssetsScreen
      onEditTrim={(id) => navigate(`/assets/${encodeURIComponent(id)}/trim`)}
      onOpenAsset={(id) => navigate(`/assets/${encodeURIComponent(id)}`)}
    />
  )
}

function AssetDetailRoute() {
  const navigate = useNavigate()
  const { assetId = '' } = useParams()
  return (
    <AssetDetailScreen
      assetId={assetId}
      onClose={() => navigate('/assets')}
      onEditTrim={(id) => navigate(`/assets/${encodeURIComponent(id)}/trim`)}
    />
  )
}

function AssetTrimRoute() {
  const navigate = useNavigate()
  const { assetId = '' } = useParams()
  return (
    <TrimEditorScreen
      assetId={assetId}
      onClose={() => navigate('/assets')}
    />
  )
}

function NotFoundRoute() {
  const navigate = useNavigate()
  return (
    <div className="grid gap-4 px-6 py-10">
      <div>
        <h1 className="m-0 text-2xl font-semibold tracking-tight">Page not found</h1>
        <p className="m-0 mt-1 max-w-2xl text-sm" style={{ color: 'var(--cc-ink-2)' }}>
          This operator route does not exist in this build.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        {[
          ['First Setup', '/setup'],
          ['Recording', '/recording'],
          ['Reports', '/reports'],
          ['Readiness', '/health'],
        ].map(([label, path]) => (
          <button
            key={path}
            type="button"
            onClick={() => navigate(path)}
            className="rounded-md px-3 py-2 text-sm font-semibold"
            style={{
              background: 'var(--cc-surface)',
              border: '1px solid var(--cc-line)',
              color: 'var(--cc-ink)',
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  )
}

function SetupRoute() {
  const navigate = useNavigate()
  const location = useLocation()
  const returnTo = (location.state as { returnTo?: unknown } | null)?.returnTo
  const authenticatedDestination =
    typeof returnTo === 'string' && returnTo.startsWith('/') && returnTo !== '/setup'
      ? returnTo
      : '/health'
  return <SetupScreen onAuthenticated={() => navigate(authenticatedDestination, { replace: true })} />
}

function AppContent() {
  const navigate = useNavigate()
  const location = useLocation()
  const route = routeForPath(location.pathname)
  const trimEditorRoute = isTrimEditorRoute(location.pathname)
  // Identity fetched at the shell so the Sidebar can hide nav entries the
  // current operator can't enter (UX-1, S26 gauntletgate). When the query
  // is still loading or has errored, `roles` stays undefined and role-gated
  // entries are hidden (fail-closed). Cached across the session by react-
  // query under the shared 'staff-identity' key (same key PaywallScreen
  // uses), so we don't double-fetch.
  const identityQuery = useQuery<StaffIdentityResponse>({
    queryKey: ['staff-identity'],
    queryFn: getStaffIdentity,
    enabled: !trimEditorRoute && location.pathname !== '/setup',
    retry: false,
  })
  const roles: readonly RoleName[] | undefined = identityQuery.data?.roles

  // Move focus to the main landmark on route change so keyboard and
  // screen-reader users land on the new screen's content instead of stale
  // focus left on a control from the previous screen (UX-MAJOR-2). Mirrors
  // the public portal's existing route-change focus pattern
  // (apps/portal-public/src/App.tsx): move focus on a path change, but never
  // on the render that first establishes the page. The public portal's
  // target is a per-screen `h2[tabindex="-1"]` heading; the operator console
  // has no equivalent per-screen heading convention across its ~35 routed
  // screens, so this targets the shell's own
  // `<main id="main-content" tabIndex={-1}>` landmark (components/shell/
  // Layout.tsx) instead -- same tabIndex={-1} + effect-keyed-on-route
  // technique, applied to the one focus target every operator route already
  // renders into.
  //
  // "Skip the first render" isn't sufficient here the way it is for the
  // public portal: this shell's own route table unconditionally redirects
  // `/` -> `/setup` (and bounces a missing staff session to `/setup` too),
  // so `location.pathname` changes at least once purely from routing
  // settling in, before the operator has touched anything -- confirmed by
  // instrumenting `focusin`: without this guard, focus silently jumped to
  // `#main-content` ~200ms after load with no keyboard or pointer input at
  // all, which would have made the skip link (W-3, above) untabbable on a
  // fresh load, since focus already left `<body>` before the operator's
  // first Tab press. Gating on a real keydown/pointerdown having happened
  // at least once distinguishes "the router is still resolving where the
  // operator actually landed" from "the operator did something that
  // changed the route" -- only the latter should move focus.
  const hasInteractedRef = useRef(false)
  useEffect(() => {
    const markInteracted = () => {
      hasInteractedRef.current = true
    }
    window.addEventListener('pointerdown', markInteracted, { capture: true })
    window.addEventListener('keydown', markInteracted, { capture: true })
    return () => {
      window.removeEventListener('pointerdown', markInteracted, true)
      window.removeEventListener('keydown', markInteracted, true)
    }
  }, [])

  const lastFocusedPathRef = useRef<string | null>(null)
  useEffect(() => {
    const isFirstObservedPath = lastFocusedPathRef.current === null
    if (lastFocusedPathRef.current === location.pathname) return
    lastFocusedPathRef.current = location.pathname
    if (isFirstObservedPath || !hasInteractedRef.current) return
    document.getElementById(MAIN_CONTENT_ID)?.focus({ preventScroll: false })
  }, [location.pathname])

  if (trimEditorRoute) {
    return (
      <Routes>
        <Route path="/assets/:assetId/trim" element={<AssetTrimRoute />} />
      </Routes>
    )
  }

  const missingStaffSession =
    identityQuery.error instanceof ApiError && identityQuery.error.status === 401
  if (missingStaffSession && !['/setup', '/login', '/sign-in'].includes(location.pathname)) {
    return <Navigate to="/setup" replace state={{ returnTo: location.pathname }} />
  }

  return (
    <Layout route={route} onNavigate={(id) => navigate(routePath(id))} roles={roles}>
      <SampleSeedNotice enabled={location.pathname !== '/setup'} />
      <Suspense
        fallback={(
          <div role="status" className="px-6 py-10 text-sm" style={{ color: 'var(--cc-ink-2)' }}>
            Loading this CivicCast screen...
          </div>
        )}
      >
        <Routes>
        <Route path="/" element={<Navigate to="/setup" replace />} />
        <Route path="/setup" element={<SetupRoute />} />
        {/* First Setup hosts the returning-operator Admin sign-in card, so a
            guessed /login (or /sign-in) lands there instead of Page not found. */}
        <Route path="/login" element={<Navigate to="/setup" replace />} />
        <Route path="/sign-in" element={<Navigate to="/setup" replace />} />
        <Route path="/live" element={<LiveRoomScreen />} />
        <Route path="/facility" element={<FacilityRouterScreen />} />
        <Route path="/control-room" element={<ControlRoomScreen />} />
        <Route path="/control-room-setup" element={<ControlRoomSetupScreen />} />
        <Route path="/remote-contribution" element={<RemoteContributionScreen />} />
        <Route path="/channels" element={<ChannelOpsScreen />} />
        <Route path="/cg" element={<CgBoardScreen />} />
        <Route path="/cg-board" element={<CgBoardDesignerScreen />} />
        <Route path="/cg-designer" element={<Navigate to="/cg-board" replace />} />
        <Route path="/schedule" element={<ScheduleScreen />} />
        <Route path="/auto-schedule" element={<AutoScheduleScreen />} />
        <Route path="/guide" element={<ProgramGuideScreen />} />
        <Route path="/program-guide" element={<Navigate to="/guide" replace />} />
        <Route path="/assets" element={<AssetsRoute />} />
        <Route path="/assets/:assetId" element={<AssetDetailRoute />} />
        <Route path="/assets/:assetId/trim" element={<AssetTrimRoute />} />
        <Route path="/contribute" element={<ContributeScreen />} />
        <Route path="/contributors" element={<Navigate to="/contribute" replace />} />
        <Route path="/review" element={<ReviewQueueScreen />} />
        <Route path="/review-queue" element={<Navigate to="/review" replace />} />
        <Route path="/summary" element={<SummaryReviewScreen />} />
        <Route path="/summary-review" element={<Navigate to="/summary" replace />} />
        <Route path="/publish" element={<PublishDashboardScreen />} />
        <Route path="/playback-policy" element={<PlaybackPolicyScreen />} />
        <Route path="/analytics" element={<AnalyticsScreen />} />
        <Route path="/app-admin" element={<AppAdminScreen />} />
        <Route path="/health" element={<SystemHealthScreen />} />
        <Route path="/alerts" element={<AlertsScreen />} />
        <Route path="/emergency-alerts" element={<EasScreen />} />
        <Route path="/activitypub" element={<ActivityPubScreen />} />
        <Route path="/today" element={<Navigate to="/schedule" replace />} />
        <Route path="/archive" element={<Navigate to="/assets" replace />} />
        <Route path="/subscribers" element={<Navigate to="/paywall" replace />} />
        <Route path="/ai-models" element={<AiModelsScreen />} />
        <Route path="/station-profile" element={<StationProfileScreen />} />
        <Route path="/commissioning" element={<CommissioningWizardScreen />} />
        <Route path="/custom-fields" element={<CustomFieldsScreen />} />
        <Route path="/reports" element={<ReportsScreen />} />
        <Route path="/epg" element={<EpgExportScreen />} />
        <Route path="/epg-export" element={<Navigate to="/epg" replace />} />
        <Route path="/underwriting" element={<UnderwritingScreen />} />
        <Route path="/agendas" element={<AgendasScreen />} />
        <Route path="/paywall" element={<PaywallScreen />} />
        <Route path="/recording" element={<RecordingScreen />} />
        <Route path="/readiness" element={<Navigate to="/health" replace />} />
        <Route path="*" element={<NotFoundRoute />} />
        </Routes>
      </Suspense>
    </Layout>
  )
}

function App() {
  return (
    <ToastProvider>
      <AppContent />
    </ToastProvider>
  )
}

export default App
