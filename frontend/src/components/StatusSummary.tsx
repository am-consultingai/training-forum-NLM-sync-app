import { useState, useEffect, useCallback, Fragment } from 'react';
import { api } from '../api/client';

interface Counts {
  total: number; synced: number; needs_processing: number;
  needs_download: number; failed: number; skipped: number;
}

interface Summary {
  ever_synced: boolean;
  downloads_dir_configured: boolean;
  downloads_dir: string | null;
  total_files: number;
  needs_update: any[];
  needs_update_total: number;
  counts: Counts;
}

interface Props {
  summary: Summary | null;
  loading: boolean;
  onDismiss: () => void;
}

type Category = 'total' | 'synced' | 'failed' | 'not_downloaded' | 'needs_processing' | 'skipped';

const CAT_META: Record<Category, { label: string; color: string; action?: string }> = {
  total:            { label: 'Total',            color: '#94a3b8' },
  synced:           { label: 'Synced',           color: '#22c55e' },
  failed:           { label: 'Failed',           color: '#f87171', action: 'Reset & Retry' },
  not_downloaded:   { label: 'Needs download',   color: '#94a3b8', action: 'Run Sync' },
  needs_processing: { label: 'Needs processing', color: '#fbbf24', action: 'Run Sync' },
  skipped:          { label: 'Skipped',          color: '#94a3b8' },
};

const STATUS_COLOR: Record<string, string> = {
  done: '#22c55e', failed: '#f87171', pending: '#94a3b8',
  downloading: '#3b82f6', extracting: '#3b82f6', transcribing: '#a78bfa',
  skipped: '#94a3b8',
};

export function StatusSummary({ summary, loading, onDismiss }: Props) {
  const [activeCategory, setActiveCategory] = useState<Category | null>(null);

  if (loading) return (
    <div style={panelStyle}>
      <span style={{ color: '#94a3b8', fontSize: '0.85rem' }}>Checking status…</span>
    </div>
  );
  if (!summary) return null;

  const { counts } = summary;

  function handleStatClick(cat: Category) {
    setActiveCategory(prev => prev === cat ? null : cat);
  }

  return (
    <div style={panelStyle}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: '0.9rem', color: '#f8fafc', fontWeight: 600 }}>
          {summary.ever_synced ? 'Status Summary' : 'No sync data yet'}
        </h3>
        <div style={{ display: 'flex', gap: 6 }}>
          {activeCategory && (
            <button onClick={() => setActiveCategory(null)} style={{ ...dismissBtn, color: '#94a3b8', fontSize: '0.75rem' }}>
              ← back
            </button>
          )}
          <button onClick={onDismiss} style={dismissBtn}>✕</button>
        </div>
      </div>

      {!summary.ever_synced ? (
        <p style={{ margin: 0, fontSize: '0.82rem', color: '#94a3b8' }}>
          Run a sync to discover and process your Drive files.
        </p>
      ) : (
        <>
          {/* Status bar — always visible; the active square stays highlighted */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <StatBlock label="Total"            value={counts.total}            color="#94a3b8" onClick={() => handleStatClick('total')} active={activeCategory === 'total'} />
            <StatBlock label="Synced"           value={counts.synced}           color="#22c55e" onClick={() => handleStatClick('synced')}                                                  active={activeCategory === 'synced'} />
            <StatBlock label="Needs download"   value={counts.needs_download}   color="#94a3b8" onClick={counts.needs_download   > 0 ? () => handleStatClick('not_downloaded')   : null} active={activeCategory === 'not_downloaded'} />
            <StatBlock label="Needs processing" value={counts.needs_processing} color="#fbbf24" onClick={counts.needs_processing > 0 ? () => handleStatClick('needs_processing') : null} active={activeCategory === 'needs_processing'} />
            <StatBlock label="Failed"           value={counts.failed}           color="#f87171" onClick={counts.failed           > 0 ? () => handleStatClick('failed')           : null} active={activeCategory === 'failed'} />
            <StatBlock label="Skipped"          value={counts.skipped}          color="#94a3b8" onClick={counts.skipped          > 0 ? () => handleStatClick('skipped')          : null} active={activeCategory === 'skipped'} />
          </div>

          {/* Detail appears BELOW the bar, leaving the squares in place */}
          {activeCategory ? (
            <div style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid #334155' }}>
              {activeCategory === 'total'
                ? <PipelineSummary />
                : <DetailPanel category={activeCategory} />}
            </div>
          ) : summary.needs_update_total === 0 ? (
            <div style={{ marginTop: 12, fontSize: '0.82rem', color: '#86efac' }}>✓ All files are up to date.</div>
          ) : (
            <div style={{ marginTop: 12, fontSize: '0.78rem', color: '#94a3b8' }}>
              Click a stat to see the file list and available actions.
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Stat block ───────────────────────────────────────────────────────────────

function StatBlock({ label, value, color, onClick, active }: {
  label: string; value: number; color: string; onClick: (() => void) | null; active: boolean;
}) {
  const clickable = onClick !== null;
  const baseBg = active ? color + '22' : '#0f172a';
  return (
    <div
      onClick={clickable ? onClick! : undefined}
      title={clickable ? `Click to ${active ? 'hide' : 'view'} ${label.toLowerCase()}` : undefined}
      style={{
        background: baseBg,
        border: `1px solid ${active ? color : clickable && value > 0 ? color + '55' : '#1e293b'}`,
        boxShadow: active ? `0 0 0 1px ${color}` : 'none',
        borderRadius: 8, padding: '6px 12px', textAlign: 'center', minWidth: 72,
        cursor: clickable ? 'pointer' : 'default',
        transition: 'border-color 0.15s, background 0.15s',
        userSelect: 'none',
      }}
      onMouseEnter={e => { if (clickable && !active) (e.currentTarget as HTMLElement).style.background = '#1e293b'; }}
      onMouseLeave={e => { if (clickable && !active) (e.currentTarget as HTMLElement).style.background = baseBg; }}
    >
      <div style={{ fontSize: '1.15rem', fontWeight: 700, color }}>{value}</div>
      <div style={{ fontSize: '0.67rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.04em', marginTop: 1 }}>
        {label}
      </div>
      {clickable && value > 0 && (
        <div style={{ fontSize: '0.6rem', color: color + 'aa', marginTop: 2 }}>
          {active ? 'showing ↓' : 'click to view ↗'}
        </div>
      )}
    </div>
  );
}

// ── Detail panel (paginated file list + actions) ──────────────────────────────

interface FileItem {
  id: string; name: string; drive_path: string; mime_type: string;
  relevance: string; category: string; download_status: string;
  processing_status: string; processing_type: string | null; error: string | null;
}

function DetailPanel({ category }: { category: Category }) {
  const meta = CAT_META[category];
  const [page, setPage]       = useState(0);
  const [data, setData]       = useState<{ items: FileItem[]; total: number; total_pages: number } | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [actioning, setActioning] = useState(false);
  const [flagging, setFlagging] = useState<string | null>(null);

  const PER_PAGE = 50;

  async function toggleRelevance(f: FileItem) {
    if (flagging) return;
    const next = f.relevance === 'not_relevant' ? 'relevant' : 'not_relevant';
    setFlagging(f.id);
    try {
      await api.setFileFlag(f.id, next);
      setData(prev => prev ? {
        ...prev,
        items: prev.items.map(it => it.id === f.id ? { ...it, relevance: next } : it),
      } : prev);
    } catch {}
    finally { setFlagging(null); }
  }

  const load = useCallback(async (p: number) => {
    setLoading(true);
    try {
      const res = await fetch(`/api/status/files?category=${category}&page=${p}&per_page=${PER_PAGE}`);
      const json = await res.json();
      setData(json);
      setPage(p);
    } catch {}
    finally { setLoading(false); }
  }, [category]);

  useEffect(() => { load(0); }, [load]);

  async function handleAction() {
    setActioning(true);
    setActionMsg(null);
    try {
      if (meta.action === 'Reset & Retry') {
        const res = await fetch('/api/status/reset-failed', { method: 'POST' });
        const json = await res.json();
        setActionMsg(`Reset ${json.reset} failed file${json.reset !== 1 ? 's' : ''} — run a sync to retry.`);
        load(page);
      } else if (meta.action === 'Run Sync') {
        await fetch('/api/sync/trigger', { method: 'POST' });
        setActionMsg('Sync started — files will be processed shortly.');
      }
    } catch (e: any) {
      setActionMsg(`Error: ${e.message}`);
    }
    setActioning(false);
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 10, height: 10, borderRadius: '50%', background: meta.color, display: 'inline-block' }} />
          <span style={{ fontSize: '0.88rem', fontWeight: 600, color: meta.color }}>{meta.label}</span>
          {data && <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>({data.total} files)</span>}
        </div>
        {meta.action && (
          <button
            onClick={handleAction}
            disabled={actioning}
            style={{
              background: actioning ? '#334155' : meta.color + '22',
              border: `1px solid ${meta.color}55`,
              borderRadius: 6, color: meta.color,
              cursor: actioning ? 'not-allowed' : 'pointer',
              fontSize: '0.78rem', fontWeight: 600, padding: '4px 12px',
            }}
          >
            {actioning ? 'Working…' : meta.action}
          </button>
        )}
      </div>

      {actionMsg && (
        <div style={{ fontSize: '0.78rem', color: '#94a3b8', background: '#0f172a', borderRadius: 6, padding: '6px 10px' }}>
          {actionMsg}
        </div>
      )}

      {/* File list */}
      {loading ? (
        <div style={{ color: '#94a3b8', fontSize: '0.82rem', padding: '8px 0' }}>Loading…</div>
      ) : data && data.items.length === 0 ? (
        <div style={{ color: '#94a3b8', fontSize: '0.82rem' }}>No files in this category.</div>
      ) : data ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {data.items.map(f => {
            const ignored = f.relevance === 'not_relevant';
            return (
            <div key={f.id} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '4px 6px', borderRadius: 4, background: '#0f172a',
              fontSize: '0.78rem', opacity: ignored ? 0.5 : 1,
            }}>
              <span style={{
                width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                background: STATUS_COLOR[f.processing_status] || '#94a3b8',
              }} />
              <a
                href={`https://drive.google.com/file/d/${f.id}/view`}
                target="_blank"
                rel="noopener noreferrer"
                style={{ color: '#7dd3fc', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', textDecoration: ignored ? 'line-through' : 'none' }}
                title={`${f.drive_path} — open in Drive`}
                onMouseEnter={e => { (e.currentTarget as HTMLElement).style.textDecoration = 'underline'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLElement).style.textDecoration = ignored ? 'line-through' : 'none'; }}
              >
                {f.drive_path}
              </a>
              {f.error && (
                <span style={{ color: '#f87171', fontSize: '0.7rem', flexShrink: 0, maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={f.error}>
                  ⚠ {f.error.slice(0, 40)}
                </span>
              )}
              <button
                onClick={() => toggleRelevance(f)}
                disabled={flagging === f.id}
                title={ignored ? 'Mark as relevant' : 'Mark as not relevant (exclude from NotebookLM)'}
                style={{
                  flexShrink: 0, padding: '1px 6px', fontSize: '0.65rem', borderRadius: 3,
                  border: `1px solid ${ignored ? '#f59e0b' : '#334155'}`,
                  background: ignored ? '#451a03' : 'transparent',
                  color: ignored ? '#f59e0b' : '#94a3b8',
                  cursor: flagging === f.id ? 'wait' : 'pointer', whiteSpace: 'nowrap',
                }}
              >
                {ignored ? '✗ ignored' : 'ignore'}
              </button>
            </div>
            );
          })}
        </div>
      ) : null}

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
          <button onClick={() => load(page - 1)} disabled={page === 0} style={pageBtn}>‹ Prev</button>
          <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>
            Page {page + 1} / {data.total_pages}
          </span>
          <button onClick={() => load(page + 1)} disabled={page >= data.total_pages - 1} style={pageBtn}>Next ›</button>
        </div>
      )}
    </div>
  );
}

// ── Pipeline summary (graphical, sequential flow of the whole sync) ───────────

interface Step {
  label: string; color: string; value: number | null; unit: string; desc: string; bad?: number;
}

function PipelineSummary() {
  const [run, setRun] = useState<any>(null);
  const [live, setLive] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    Promise.all([
      fetch('/api/sync/status').then(r => r.json()).catch(() => null),
      fetch('/api/sync/live-progress').then(r => r.json()).catch(() => null),
    ]).then(([s, l]) => {
      if (!alive) return;
      setRun(s?.run || null);
      setLive(l || null);
      setLoading(false);
    });
    return () => { alive = false; };
  }, []);

  if (loading) {
    return <div style={{ color: '#94a3b8', fontSize: '0.82rem', padding: '4px 0' }}>Loading pipeline…</div>;
  }

  // Stage values reflect the cumulative state of the whole corpus through the
  // pipeline (a funnel), so the graphic stays meaningful regardless of whether the
  // last run did heavy work or was an incremental no-op.
  const steps: Step[] = [
    { label: 'Connect',  color: '#94a3b8', value: null,                       unit: 'Google Drive',      desc: 'Authorize & connect.' },
    { label: 'Discover', color: '#38bdf8', value: run?.files_discovered ?? 0, unit: 'items found',       desc: 'List source + mirror; find new / changed / deleted.' },
    { label: 'Download', color: '#22c55e', value: live?.dl_done ?? 0,         unit: 'downloaded',        desc: 'Fetch new / changed source files.' },
    { label: 'Process',  color: '#a78bfa', value: live?.proc_done ?? 0,       unit: 'text extracted',    desc: 'Extract text / transcribe media.', bad: live?.proc_failed ?? 0 },
    { label: 'Mirror',   color: '#f59e0b', value: live?.mirror_uploaded ?? 0, unit: 'extracts on Drive', desc: 'Upload extracted text to the shared mirror.' },
    { label: 'Chunk',    color: '#818cf8', value: live?.chunks_total ?? 0,    unit: 'chunk files',       desc: 'Aggregate text into NotebookLM-sized chunks.' },
    { label: 'Upload',   color: '#3b82f6', value: live?.chunks_uploaded ?? 0, unit: 'to NotebookLM',     desc: 'Upload chunks; remove obsolete ones.' },
  ];

  const statusColor = run?.status === 'done' ? '#22c55e'
    : run?.status === 'failed' ? '#f87171'
    : run?.status === 'running' ? '#3b82f6' : '#94a3b8';

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontSize: '0.85rem', fontWeight: 600, color: '#e2e8f0' }}>Sync pipeline · current state</span>
        {run && (
          <span style={{ fontSize: '0.72rem', color: '#94a3b8' }}>
            last run:&nbsp;<span style={{ color: statusColor, fontWeight: 600 }}>{run.status}</span>
            {run.finished_at ? ` · ${new Date(run.finished_at).toLocaleString()}` : ' · in progress'}
          </span>
        )}
      </div>

      {/* Sequential flow: numbered stages connected by arrows */}
      <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'stretch', gap: 6 }}>
        {steps.map((s, i) => (
          <Fragment key={s.label}>
            <div style={{
              flex: '1 1 120px', minWidth: 112, maxWidth: 210,
              background: '#0f172a', border: `1px solid ${s.color}44`, borderTop: `3px solid ${s.color}`,
              borderRadius: 8, padding: '8px 10px', display: 'flex', flexDirection: 'column', gap: 2,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{
                  width: 16, height: 16, borderRadius: '50%', background: s.color, color: '#0b1220',
                  fontSize: '0.62rem', fontWeight: 700, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                }}>{i + 1}</span>
                <span style={{ fontSize: '0.78rem', fontWeight: 700, color: '#e2e8f0' }}>{s.label}</span>
              </div>
              <div style={{ fontSize: '1.1rem', fontWeight: 700, color: s.color, lineHeight: 1.1 }}>
                {s.value === null ? '✓' : s.value.toLocaleString()}
                {typeof s.bad === 'number' && s.bad > 0 && (
                  <span style={{ fontSize: '0.68rem', color: '#f87171', fontWeight: 600 }}>&nbsp;· {s.bad} failed</span>
                )}
              </div>
              <div style={{ fontSize: '0.62rem', color: '#94a3b8', textTransform: 'uppercase', letterSpacing: '0.03em' }}>{s.unit}</div>
              <div style={{ fontSize: '0.66rem', color: '#94a3b8', lineHeight: 1.35, marginTop: 2 }}>{s.desc}</div>
            </div>
            {i < steps.length - 1 && (
              <div style={{ display: 'flex', alignItems: 'center', color: '#94a3b8', fontSize: '1.2rem', flexShrink: 0 }}>→</div>
            )}
          </Fragment>
        ))}
      </div>

      <div style={{ marginTop: 10, fontSize: '0.72rem', color: '#94a3b8' }}>
        Each stage runs in order and feeds the next — source files become extracted text, which is mirrored to Drive, aggregated into chunks, and uploaded for NotebookLM.
      </div>
    </div>
  );
}

// ── Styles ────────────────────────────────────────────────────────────────────

const panelStyle: React.CSSProperties = {
  background: '#1e293b', border: '1px solid #334155',
  borderRadius: 10, padding: '14px 16px', margin: 16,
};

const dismissBtn: React.CSSProperties = {
  background: 'transparent', border: 'none', color: '#94a3b8',
  cursor: 'pointer', fontSize: '0.9rem', padding: '0 4px', lineHeight: 1,
};

const pageBtn: React.CSSProperties = {
  background: '#1e293b', border: '1px solid #334155', borderRadius: 4,
  color: '#94a3b8', cursor: 'pointer', fontSize: '0.75rem', padding: '3px 10px',
};
