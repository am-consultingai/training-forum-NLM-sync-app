import { useState, useEffect, useRef } from 'react';
import { api } from '../../api/client';
import type { SyncRun, ProgressEvent } from '../../types';

const STAGES = [
  { key: 'discover',     label: 'Discover' },
  { key: 'hydrate',      label: 'Restore' },
  { key: 'download',     label: 'Download' },
  { key: 'process',      label: 'Process' },
  { key: 'extract_sync', label: 'Mirror upload' },
  { key: 'chunk',        label: 'Chunk' },
  { key: 'upload',       label: 'Upload to Drive' },
];

interface Props {
  onSyncStarted: () => void;
  lastEvent: ProgressEvent | null;
  authorized: boolean;
  isRunning: boolean;
}

interface LiveProgress {
  total: number;
  dl_done: number;
  downloading_file: string | null;
  proc_done: number;
  proc_failed: number;
  chunked: number;
  mirror_total: number;
  mirror_uploaded: number;
  mirror_file: string | null;
  chunks_total: number;
  chunks_uploaded: number;
  transcribing_file: string | null;
  transcribing_pct: number;
}

function Bar({ pct, color }: { pct: number; color: string }) {
  return (
    <div style={{ background: '#1a202c', borderRadius: 4, height: 7, overflow: 'hidden' }}>
      <div style={{ background: color, height: '100%', width: `${pct}%`, transition: 'width 0.4s ease' }} />
    </div>
  );
}

export function SyncPanel({ onSyncStarted, lastEvent, isRunning, authorized }: Props) {
  const [run, setRun]               = useState<SyncRun | null>(null);
  const [currentStage, setCurrentStage] = useState<string | null>(null);
  const [stageMessage, setStageMessage] = useState('');
  const [live, setLive]             = useState<LiveProgress | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [error, setError]           = useState<string | null>(null);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    api.getSyncStatus().then(({ run }) => setRun(run));
  }, [isRunning]);

  // Poll the authoritative live-progress snapshot while a run is active.
  useEffect(() => {
    function poll() {
      api.getLiveProgress().then(setLive).catch(() => {});
    }
    if (isRunning) {
      poll();
      pollRef.current = window.setInterval(poll, 2000);
      return () => { if (pollRef.current) window.clearInterval(pollRef.current); };
    } else {
      setLive(null);
      if (pollRef.current) window.clearInterval(pollRef.current);
    }
  }, [isRunning]);

  // Stage strip + smooth transcription % come from SSE events between polls.
  useEffect(() => {
    if (!lastEvent) return;
    if (lastEvent.type === 'stage_change') {
      setCurrentStage(lastEvent.stage || null);
      setStageMessage(lastEvent.message || '');
    }
    if (lastEvent.type === 'file_status' && lastEvent.status === 'transcribing') {
      setLive(prev => prev ? {
        ...prev,
        transcribing_file: lastEvent.name || prev.transcribing_file,
        transcribing_pct: Math.round((lastEvent.progress || 0) * 100),
      } : prev);
    }
    if (lastEvent.type === 'run_complete') {
      setCurrentStage(null);
      setStageMessage('');
    }
  }, [lastEvent]);

  async function handleTrigger() {
    setTriggering(true);
    setError(null);
    try {
      await api.triggerSync();
      onSyncStarted();
    } catch (e: any) {
      setError(e.message?.includes('409') ? 'Sync already running.' : String(e.message));
    } finally {
      setTriggering(false);
    }
  }

  const stageIdx = STAGES.findIndex(s => s.key === currentStage);

  const dlPct = live && live.total > 0 ? Math.round((live.dl_done / live.total) * 100) : 0;
  const procPct = live && live.total > 0 ? Math.round((live.proc_done / live.total) * 100) : 0;
  const mirrorPct = live && live.mirror_total > 0 ? Math.round((live.mirror_uploaded / live.mirror_total) * 100) : 0;
  const uplPct = live && live.chunks_total > 0 ? Math.round((live.chunks_uploaded / live.chunks_total) * 100) : 0;

  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <button
          onClick={handleTrigger}
          disabled={isRunning || triggering || !authorized}
          title={!authorized ? 'Connect Google Drive first' : undefined}
          style={{
            background: isRunning || triggering || !authorized ? '#4a5568' : '#3b82f6',
            color: '#fff', border: 'none', borderRadius: 8,
            padding: '8px 20px', fontWeight: 600, fontSize: '0.9rem',
            cursor: isRunning || triggering || !authorized ? 'not-allowed' : 'pointer',
            opacity: !authorized ? 0.6 : 1,
          }}
        >
          {triggering ? 'Starting...' : isRunning ? 'Running...' : 'Run Sync Now'}
        </button>
        {run && (
          <span style={{ fontSize: '0.8rem', color: '#94a3b8' }}>
            Last run: {run.status} · {run.finished_at ? new Date(run.finished_at).toLocaleString() : 'in progress'}
          </span>
        )}
      </div>

      {error && <div style={{ color: '#ef4444', fontSize: '0.85rem' }}>{error}</div>}

      {isRunning && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* Stage strip */}
          <div style={{ display: 'flex', gap: 4 }}>
            {STAGES.map((s, i) => (
              <div key={s.key} style={{
                flex: 1, textAlign: 'center', padding: '4px 2px', borderRadius: 4,
                fontSize: '0.75rem', fontWeight: i === stageIdx ? 700 : 400,
                background: i < stageIdx ? '#22c55e22' : i === stageIdx ? '#3b82f622' : '#1a202c',
                color: i < stageIdx ? '#22c55e' : i === stageIdx ? '#3b82f6' : '#4a5568',
                border: `1px solid ${i === stageIdx ? '#3b82f6' : 'transparent'}`,
              }}>{s.label}</div>
            ))}
          </div>

          {stageMessage && (
            <div style={{ fontSize: '0.78rem', color: '#94a3b8' }}>{stageMessage}</div>
          )}

          {live && live.total > 0 && (
            <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>
              {/* ── Download / Sync ── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8' }}>
                  <span>📥 Downloading</span>
                  <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{live.dl_done} / {live.total}</span>
                </div>
                {/* Currently downloading filename — above the bar */}
                <div style={{
                  fontSize: '0.72rem', color: live.downloading_file ? '#86efac' : '#94a3b8',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', height: 16,
                }}>
                  {live.downloading_file
                    ? `↓ ${live.downloading_file}`
                    : live.dl_done >= live.total
                      ? '✓ all files downloaded'
                      : 'waiting for files…'}
                </div>
                <Bar pct={dlPct} color="#22c55e" />
                <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{dlPct}% downloaded</div>
              </div>

              {/* ── Transcription / Processing ── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8' }}>
                  <span>🎧 Processing</span>
                  <span style={{ color: '#e2e8f0', fontWeight: 600 }}>
                    {live.proc_done} / {live.total}{live.proc_failed > 0 && <span style={{ color: '#fca5a5' }}> · {live.proc_failed} failed</span>}
                  </span>
                </div>
                {/* Currently transcribing filename — above the bar */}
                <div style={{
                  fontSize: '0.72rem', color: live.transcribing_file ? '#c4b5fd' : '#94a3b8',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', height: 16,
                }}>
                  {live.transcribing_file
                    ? `🎙 ${live.transcribing_file} (${live.transcribing_pct}%)`
                    : (live.proc_done + live.proc_failed) >= live.total
                      ? '✓ all files processed'
                      : 'extracting documents…'}
                </div>
                <Bar pct={procPct} color="#a78bfa" />
                <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{procPct}% processed</div>
              </div>

              {/* ── Mirror upload (extracted text → Drive) ── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8' }}>
                  <span>🪞 Mirror</span>
                  <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{live.mirror_uploaded} / {live.mirror_total}</span>
                </div>
                <div style={{
                  fontSize: '0.72rem', color: live.mirror_file ? '#fcd34d' : '#94a3b8',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', height: 16,
                }}>
                  {live.mirror_total > 0 && live.mirror_uploaded >= live.mirror_total
                    ? '✓ extracted text synced'
                    : live.mirror_file ? `⤴ ${live.mirror_file}` : 'preparing…'}
                </div>
                <Bar pct={mirrorPct} color="#f59e0b" />
                <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{mirrorPct}% to Drive</div>
              </div>

              {/* ── Upload to NotebookLM (chunks) ── */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', color: '#94a3b8' }}>
                  <span>📤 To NotebookLM</span>
                  <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{live.chunks_uploaded} / {live.chunks_total}</span>
                </div>
                <div style={{
                  fontSize: '0.72rem', color: '#94a3b8',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', height: 16,
                }}>
                  {live.chunks_total > 0 && live.chunks_uploaded >= live.chunks_total
                    ? '✓ all chunks uploaded'
                    : `${live.chunked} files chunked`}
                </div>
                <Bar pct={uplPct} color="#38bdf8" />
                <div style={{ fontSize: '0.7rem', color: '#94a3b8' }}>{uplPct}% uploaded</div>
              </div>
            </div>
          )}
        </div>
      )}

      {!isRunning && run?.status === 'done' && (
        <div style={{
          background: '#22c55e11', border: '1px solid #22c55e33',
          borderRadius: 8, padding: '10px 14px', fontSize: '0.82rem', color: '#86efac',
        }}>
          Last sync complete · {run.files_processed} files processed · {run.chunks_uploaded} chunks uploaded to Drive
          <br />
          <span style={{ color: '#94a3b8' }}>
            Remember to click <strong>Sync</strong> in NotebookLM to pull in the latest files.
          </span>
        </div>
      )}

      {run?.status === 'failed' && (
        <div style={{
          background: '#ef444411', border: '1px solid #ef444433',
          borderRadius: 8, padding: '10px 14px', fontSize: '0.82rem', color: '#fca5a5',
        }}>
          Last sync failed: {run.error_message || 'Unknown error'}
        </div>
      )}
    </div>
  );
}
