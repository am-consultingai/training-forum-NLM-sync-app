import { useState, useCallback, useEffect, useRef } from 'react';
import { FileTree } from './components/FileTree/FileTree';
import { SyncPanel } from './components/SyncPanel/SyncPanel';
import { FirstRunWizard } from './components/FirstRunWizard';
import { StatusSummary } from './components/StatusSummary';
import { AuthBanner } from './components/AuthBanner';
import { OrphanReviewBanner } from './components/OrphanReviewBanner';
import { LogsPanel } from './components/LogsPanel';
import { SettingsPanel } from './components/SettingsPanel';
import { ActivityBar, type LiveProgress } from './components/ActivityBar';
import { useFileTree } from './hooks/useFileTree';
import { useSSE } from './hooks/useSSE';
import { api } from './api/client';
import type { ProgressEvent } from './types';
import amLogo from './assets/am-logo.png';
import cloudLogo from './assets/cloud-logo.png';
import './App.css';

export default function App() {
  const { tree, loading, refresh, handleEvent } = useFileTree();
  const [isRunning, setIsRunning] = useState(false);
  // Timestamp of the last manual trigger. Used to grace-guard the status
  // reconciler so it doesn't flip isRunning back off in the brief window
  // before the backend inserts the 'running' sync_runs row.
  const lastTriggerRef = useRef(0);
  const [lastEvent, setLastEvent] = useState<ProgressEvent | null>(null);
  const [live, setLive] = useState<LiveProgress | null>(null);

  const [setupComplete, setSetupComplete] = useState(false);
  const [dataFolder, setDataFolder] = useState<string | null>(null);
  const [authorized, setAuthorized] = useState<boolean | null>(null);
  const [redirectUri, setRedirectUri] = useState('http://localhost:8000/api/auth/callback');
  const [summary, setSummary] = useState<any>(null);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const [showSummary, setShowSummary] = useState(true);
  const [activeTab, setActiveTab] = useState<'sync' | 'logs' | 'settings'>('sync');

  const refreshAuth = useCallback(async () => {
    try {
      const auth = await api.getAuthStatus();
      setAuthorized(auth.authorized);
      setRedirectUri(auth.redirect_uri);
    } catch {}
  }, []);

  const init = useCallback(async () => {
    try {
      const [cfg, sum, syncStatus] = await Promise.all([
        api.getConfig(),
        api.getStatusSummary(),
        api.getSyncStatus(),
      ]);
      setDataFolder((cfg.data_folder as string) || null);
      setSummary(sum);
      // Detect in-flight sync started outside the UI (e.g. scheduled or API)
      if (syncStatus.active) {
        setIsRunning(true);
        refresh();
      }
    } catch {}
    finally { setSummaryLoading(false); }
    refreshAuth();
  }, [refreshAuth, refresh]);

  useEffect(() => { init(); }, [init]);

  useEffect(() => {
    const onFocus = () => refreshAuth();
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  }, [refreshAuth]);

  // Always-on reconciliation against the authoritative sync status. isRunning is
  // turned ON by SSE stage_change / manual trigger / init, but was previously only
  // turned OFF by the SSE run_complete event — so a single missed run_complete
  // (reconnect gap, backgrounded tab, run finishing during a disconnect) left the
  // UI stuck on "Running…" with the button disabled and no way to resync. This
  // poll heals that by following the backend's active flag in both directions.
  useEffect(() => {
    let cancelled = false;
    const reconcile = async () => {
      try {
        const { active } = await api.getSyncStatus();
        if (cancelled) return;
        if (active) {
          setIsRunning(true);
        } else {
          // Don't flip off within the grace window right after a manual trigger,
          // when the 'running' row may not be inserted yet.
          if (Date.now() - lastTriggerRef.current > 10000) setIsRunning(false);
        }
      } catch { /* transient network/server error — keep current state */ }
    };
    reconcile();
    const id = window.setInterval(reconcile, isRunning ? 3000 : 8000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [isRunning]);

  // Keep the status summary numbers live at all times — not just while a run is
  // flagged "running". The processing worker can keep completing files after the
  // run is marked "done" (its queue drains in the background), so the boxes must
  // keep refreshing even when isRunning is false, and they must never go stale
  // while the page is open. Poll faster during an active run, slower when idle.
  useEffect(() => {
    const tick = () => api.getStatusSummary().then(setSummary).catch(() => {});
    tick();
    const id = window.setInterval(tick, isRunning ? 3000 : 8000);
    return () => window.clearInterval(id);
  }, [isRunning]);

  // Live pipeline snapshot for the always-visible activity bar (all tabs).
  useEffect(() => {
    if (!isRunning) { setLive(null); return; }
    const tick = () => api.getLiveProgress().then(setLive).catch(() => {});
    tick();
    const id = window.setInterval(tick, 2000);
    return () => window.clearInterval(id);
  }, [isRunning]);

  // Re-fetch the whole file tree periodically while a sync runs, so newly
  // discovered files appear without a page reload. (Per-file SSE events only
  // update existing nodes — they can't add nodes the initial fetch missed, e.g.
  // on a fresh/relocated data folder.)
  useEffect(() => {
    if (!isRunning) return;
    const id = window.setInterval(() => refresh(), 8000);
    return () => window.clearInterval(id);
  }, [isRunning, refresh]);

  // SSE is always-on — no longer gated on isRunning
  const onEvent = useCallback((event: ProgressEvent) => {
    setLastEvent(event);
    handleEvent(event);
    if (event.type === 'stage_change') {
      // Any stage event means a sync is running
      setIsRunning(true);
    }
    if (event.type === 'run_complete') {
      setIsRunning(false);
      api.getStatusSummary().then(setSummary).catch(() => {});
      refresh();  // final full refetch so the tree reflects the completed run
    }
  }, [handleEvent, refresh]);

  useSSE(onEvent);

  function handleSyncStarted() {
    lastTriggerRef.current = Date.now();
    setIsRunning(true);
    setShowSummary(true);  // keep summary visible so its numbers update live during the run
    refresh();
  }

  // First-run wizard: model download → Google client → sign-in → data folder.
  // Renders nothing once every step is already satisfied.
  if (!setupComplete) {
    return <FirstRunWizard onComplete={() => { setSetupComplete(true); init(); }} />;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#0f172a', color: '#e2e8f0', fontFamily: 'system-ui, sans-serif' }}>
      <header style={{ padding: '12px 20px', borderBottom: '1px solid #1e293b', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0 }}>
        <img src={cloudLogo} alt="sHaRe sync" style={{ height: 28, width: 28, display: 'block' }} />
        <h1 style={{ margin: 0, fontSize: '1rem', fontWeight: 700, color: '#f8fafc' }}>sHaRe sync</h1>
        {dataFolder && (
          <span
            style={{ fontSize: '0.75rem', color: '#94a3b8', fontFamily: 'monospace', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 300, cursor: 'pointer' }}
            title={`Data folder: ${dataFolder} — change in Settings`}
            onClick={() => setActiveTab('settings')}
          >
            📁 {dataFolder}
          </span>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
          {authorized !== null && (
            <span style={{ fontSize: '0.75rem', color: authorized ? '#22c55e' : '#f59e0b', display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 7, height: 7, borderRadius: '50%', background: authorized ? '#22c55e' : '#f59e0b', display: 'inline-block' }} />
              {authorized ? 'Drive connected' : 'Drive not connected'}
            </span>
          )}
          {!isRunning && (
            <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>Idle</span>
          )}
          <a
            href="https://notebooklm.google.com/notebook/a3c2cfc6-3d98-4c7a-9b21-08846b9f60c3"
            target="_blank"
            rel="noopener noreferrer"
            title="Open this project's NotebookLM notebook"
            style={{
              display: 'flex', alignItems: 'center', gap: 7, textDecoration: 'none',
              padding: '5px 11px', borderRadius: 8, border: '1px solid #334155',
              background: '#111c33', color: '#e2e8f0', cursor: 'pointer',
            }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true">
              <defs>
                <linearGradient id="nlmSpark" x1="0" y1="0" x2="24" y2="24" gradientUnits="userSpaceOnUse">
                  <stop offset="0" stopColor="#4285F4" />
                  <stop offset="1" stopColor="#9B72CB" />
                </linearGradient>
              </defs>
              <path
                fill="url(#nlmSpark)"
                d="M19 9l1.25-2.75L23 5l-2.75-1.25L19 1l-1.25 2.75L15 5l2.75 1.25L19 9zm-7.5.5L9 4 6.5 9.5 1 12l5.5 2.5L9 20l2.5-5.5L17 12l-5.5-2.5zM19 15l-1.25 2.75L15 19l2.75 1.25L19 23l1.25-2.75L23 19l-2.75-1.25L19 15z"
              />
            </svg>
            <span style={{ fontSize: '0.8rem', fontWeight: 600 }}>NotebookLM</span>
          </a>
        </div>
      </header>

      <ActivityBar live={live} />

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        <aside style={{ width: 320, borderRight: '1px solid #1e293b', display: 'flex', flexDirection: 'column', overflow: 'hidden', flexShrink: 0 }}>
          <div style={{ padding: '10px 16px', borderBottom: '1px solid #1e293b', fontSize: '0.75rem', fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Files
          </div>
          <FileTree nodes={tree} loading={loading} />
        </aside>

        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Tab bar */}
          <div style={{ display: 'flex', borderBottom: '1px solid #1e293b', flexShrink: 0 }}>
            {([['sync', 'Sync Control'], ['logs', '📋 Logs'], ['settings', '⚙ Settings']] as const).map(([tab, label]) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                style={{
                  padding: '10px 20px', background: 'none', border: 'none', cursor: 'pointer',
                  fontSize: '0.75rem', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em',
                  color: activeTab === tab ? '#e2e8f0' : '#94a3b8',
                  borderBottom: activeTab === tab ? '2px solid #3b82f6' : '2px solid transparent',
                  marginBottom: -1,
                }}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          {activeTab === 'sync' && (
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
              {authorized === false && <AuthBanner redirectUri={redirectUri} />}
              <OrphanReviewBanner
                count={summary?.pending_orphans ?? 0}
                onResolved={() => api.getStatusSummary().then(setSummary).catch(() => {})}
              />
              <SyncPanel onSyncStarted={handleSyncStarted} lastEvent={lastEvent} isRunning={isRunning} authorized={authorized === true} />
              {showSummary && <StatusSummary summary={summary} loading={summaryLoading} onDismiss={() => setShowSummary(false)} isRunning={isRunning} />}
              {!showSummary && summary && (summary.counts?.needs_download > 0 || summary.counts?.needs_processing > 0 || summary.counts?.failed > 0) && (
                <button onClick={() => setShowSummary(true)} style={{ margin: '0 16px', background: 'transparent', border: '1px solid #334155', borderRadius: 6, color: '#fbbf24', fontSize: '0.8rem', padding: '6px 12px', cursor: 'pointer', textAlign: 'left', width: 'fit-content' }}>
                  ⚠ {summary.needs_update_total} file{summary.needs_update_total !== 1 ? 's' : ''} need attention — show details
                </button>
              )}
            </div>
          )}

          {activeTab === 'logs' && (
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              <LogsPanel liveEvent={lastEvent} />
            </div>
          )}

          {activeTab === 'settings' && (
            <div style={{ flex: 1, overflowY: 'auto' }}>
              <SettingsPanel />
            </div>
          )}
        </main>
      </div>

      <footer style={{
        flexShrink: 0, borderTop: '1px solid #1e293b', background: '#0b0f19',
        display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 12,
        padding: '12px 16px',
      }}>
        <a
          href="https://www.amconsultingai.com"
          target="_blank"
          rel="noopener noreferrer"
          title="AM Consulting — amconsultingai.com"
          style={{
            display: 'flex', alignItems: 'center', gap: 12, textDecoration: 'none',
            color: '#cbd5e1', fontSize: '0.95rem', fontWeight: 500,
          }}
        >
          <span>Powered by</span>
          <span style={{
            display: 'inline-flex', alignItems: 'center',
            background: '#ffffff', borderRadius: 8,
            padding: '6px 12px',
            boxShadow: '0 1px 6px rgba(0, 0, 0, 0.4)',
          }}>
            <img src={amLogo} alt="AM Consulting" style={{ height: 30, display: 'block' }} />
          </span>
        </a>
      </footer>
    </div>
  );
}
