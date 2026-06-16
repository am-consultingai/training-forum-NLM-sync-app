// Persistent "what's happening right now" bar, shown under the header on every
// tab while a sync is running. Driven by the /sync/live-progress snapshot so it
// stays correct across tab switches and reloads (independent of the SSE stream).
// Hovering it reveals the full pipeline, the current step, and the step's goal.

import { useState } from 'react';

export interface LiveProgress {
  total: number;
  stage: string | null;
  stage_message: string | null;
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

// The real pipeline, in order. `key` matches the backend stage_change `stage`.
export const PHASES: { key: string; label: string; desc: string }[] = [
  { key: 'connecting',   label: 'Connect',       desc: 'Connecting to Google Drive.' },
  { key: 'discover',     label: 'Discover',      desc: 'Listing the source folder and the extracted-text mirror to find new, changed, and deleted files.' },
  { key: 'hydrate',      label: 'Restore',       desc: 'Restoring already-processed text and chunks from the Drive mirror so work done on other machines is reused, not repeated.' },
  { key: 'download',     label: 'Download',      desc: 'Downloading new or changed source files from Drive.' },
  { key: 'process',      label: 'Process',       desc: 'Extracting text from documents and transcribing audio/video.' },
  { key: 'extract_sync', label: 'Mirror upload', desc: 'Uploading extracted text to the shared Drive mirror so other machines can reuse it without re-processing.' },
  { key: 'chunk',        label: 'Chunk',         desc: 'Aggregating extracted text into NotebookLM-sized chunk files.' },
  { key: 'upload',       label: 'Upload to Drive', desc: 'Uploading chunk files to the Drive folder NotebookLM syncs from, and removing obsolete chunks.' },
];

export interface PhaseInfo {
  idx: number;
  label: string;
  verb: string;
  count: number;
  total: number;
  file: string | null;
}

// Derive the active phase's counters/current-file from the live snapshot.
export function activePhase(live: LiveProgress): PhaseInfo {
  const stage = live.stage || '';
  const idx = PHASES.findIndex((p) => p.key === stage);
  const label = idx >= 0 ? PHASES[idx].label : (stage || 'Working');
  switch (stage) {
    case 'download':
      return { idx, label, verb: 'Downloading', count: live.dl_done, total: live.total, file: live.downloading_file };
    case 'process':
      return {
        idx, label, verb: 'Processing', count: live.proc_done, total: live.total,
        file: live.transcribing_file ? `${live.transcribing_file} (${live.transcribing_pct}%)` : null,
      };
    case 'extract_sync':
      return { idx, label, verb: 'Uploading extracted text', count: live.mirror_uploaded, total: live.mirror_total, file: live.mirror_file };
    case 'chunk':
      return { idx, label, verb: 'Building chunks', count: live.chunked, total: live.total, file: null };
    case 'upload':
      return { idx, label, verb: 'Uploading to NotebookLM', count: live.chunks_uploaded, total: live.chunks_total, file: null };
    default:
      return { idx, label, verb: label, count: 0, total: 0, file: null };
  }
}

export function ActivityBar({ live }: { live: LiveProgress | null }) {
  const [hovered, setHovered] = useState(false);

  if (!live || !live.stage) return null;

  const info = activePhase(live);
  const pct = info.total > 0 ? Math.min(100, Math.round((info.count / info.total) * 100)) : null;
  const phaseNum = info.idx >= 0 ? info.idx + 1 : 0;

  return (
    <div
      style={{ position: 'relative', background: '#0b1220', borderBottom: '1px solid #1e293b', flexShrink: 0, cursor: 'help' }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '10px 20px' }}>
        {/* spinner */}
        <span style={{
          width: 14, height: 14, borderRadius: '50%', border: '2px solid #1e3a8a',
          borderTopColor: '#3b82f6', display: 'inline-block', animation: 'spin 0.9s linear infinite', flexShrink: 0,
        }} />

        {/* phase label + step */}
        <div style={{ display: 'flex', flexDirection: 'column', minWidth: 150, flexShrink: 0 }}>
          <span style={{ fontSize: '0.9rem', fontWeight: 700, color: '#e2e8f0' }}>{info.label}</span>
          <span style={{ fontSize: '0.68rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            {phaseNum > 0 ? `Phase ${phaseNum} of ${PHASES.length}` : 'Working'} · hover for details
          </span>
        </div>

        {/* current file / message */}
        <div style={{
          flex: 1, minWidth: 0, fontSize: '0.8rem', color: '#93c5fd',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {info.file
            ? `${info.verb}:  ${info.file}`
            : (live.stage_message || `${info.verb}…`)}
        </div>

        {/* count + mini bar */}
        {info.total > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
            <span style={{ fontSize: '0.82rem', fontWeight: 600, color: '#e2e8f0', fontVariantNumeric: 'tabular-nums' }}>
              {info.count} / {info.total}
            </span>
            <div style={{ width: 140, height: 6, background: '#1e293b', borderRadius: 3, overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: '#3b82f6', transition: 'width 0.4s ease' }} />
            </div>
            <span style={{ fontSize: '0.72rem', color: '#94a3b8', width: 34, textAlign: 'right' }}>{pct}%</span>
          </div>
        )}
      </div>

      {/* full-width indeterminate sweep when no count is available (discover/connect) */}
      {info.total === 0 && (
        <div style={{ height: 3, background: '#0b1220', overflow: 'hidden' }}>
          <div style={{ height: '100%', width: '30%', background: '#3b82f6', animation: 'sweep 1.4s ease-in-out infinite' }} />
        </div>
      )}

      {/* Hover popover — explains the pipeline and where we are in it */}
      {hovered && <PipelinePopover info={info} pct={pct} />}
    </div>
  );
}

function PipelinePopover({ info, pct }: { info: PhaseInfo; pct: number | null }) {
  const current = info.idx;
  const desc = current >= 0 ? PHASES[current].desc : '';
  return (
    <div style={{
      position: 'absolute', top: '100%', left: 20, zIndex: 50, marginTop: 6,
      width: 460, maxWidth: 'calc(100vw - 40px)',
      background: '#0f172a', border: '1px solid #334155', borderRadius: 10,
      boxShadow: '0 12px 32px rgba(0,0,0,0.5)', padding: '14px 16px',
    }}>
      <div style={{ fontSize: '0.72rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>
        Sync pipeline
      </div>
      <div style={{ fontSize: '0.82rem', color: '#cbd5e1', lineHeight: 1.5, marginBottom: 12 }}>
        {desc}
        {info.total > 0 && (
          <span style={{ color: '#93c5fd' }}>{` — ${info.count} of ${info.total} (${pct}%).`}</span>
        )}
        {info.file && (
          <div style={{ marginTop: 4, color: '#7dd3fc', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {`${info.verb}: ${info.file}`}
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {PHASES.map((p, i) => {
          const done = current >= 0 && i < current;
          const active = i === current;
          return (
            <div key={p.key} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
              <span style={{
                width: 16, textAlign: 'center', fontSize: '0.8rem', flexShrink: 0,
                color: done ? '#22c55e' : active ? '#3b82f6' : '#94a3b8',
              }}>
                {done ? '✓' : active ? '▶' : '○'}
              </span>
              <span style={{
                fontSize: '0.8rem', fontWeight: active ? 700 : 400,
                color: done ? '#86efac' : active ? '#e2e8f0' : '#94a3b8',
              }}>
                {i + 1}. {p.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
