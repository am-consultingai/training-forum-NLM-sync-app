import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '../api/client';

interface LogEntry {
  id: string;
  ts: string;
  type: string;
  run_id?: number;
  text: string;
  color: string;
}

function formatEvent(e: any): { text: string; color: string } {
  if (e.type === 'stage_change') {
    const stage = (e.stage || '').toUpperCase();
    const msg = e.message || '';
    return { text: `[${stage}] ${msg}`, color: '#93c5fd' };
  }
  if (e.type === 'file_status') {
    const name = e.name || e.file_id || '';
    const status = e.status || '';
    const stage = e.stage || '';
    const progress = e.progress !== undefined ? ` (${Math.round(e.progress * 100)}%)` : '';
    const err = e.error ? ` — ${e.error}` : '';
    const color =
      status === 'done' ? '#86efac' :
      status === 'failed' ? '#fca5a5' :
      status === 'downloading' ? '#93c5fd' :
      status === 'transcribing' ? '#c4b5fd' :
      status === 'extracting' ? '#fdba74' :
      '#94a3b8';
    return { text: `${name}  ${stage ? `[${stage}] ` : ''}${status}${progress}${err}`, color };
  }
  if (e.type === 'run_complete') {
    const ok = e.status === 'done';
    const msg = ok
      ? `Run complete — ${e.files_processed ?? 0} processed, ${e.chunks_uploaded ?? 0} chunks uploaded`
      : `Run failed — ${e.error || 'unknown error'}`;
    return { text: msg, color: ok ? '#86efac' : '#fca5a5' };
  }
  return { text: JSON.stringify(e), color: '#94a3b8' };
}

function toEntry(e: any): LogEntry {
  const { text, color } = formatEvent(e);
  return {
    id: e.id ? String(e.id) : `live-${Date.now()}-${Math.random()}`,
    ts: e.created_at ? e.created_at.split('T').join(' ').slice(0, 19) : new Date().toLocaleTimeString(),
    type: e.type,
    run_id: e.run_id,
    text,
    color,
  };
}

interface Props {
  liveEvent: any | null;
}

export function LogsPanel({ liveEvent }: Props) {
  const [entries, setEntries] = useState<LogEntry[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [filter, setFilter] = useState<'all' | 'stage' | 'done' | 'failed'>('all');
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const seenIds = useRef(new Set<string>());

  // Load history on mount
  useEffect(() => {
    api.getRecentEvents(200).then((events) => {
      const loaded = events.map(toEntry);
      loaded.forEach(e => seenIds.current.add(e.id));
      setEntries(loaded);
    }).catch(() => {});
  }, []);

  // Append live events
  useEffect(() => {
    if (!liveEvent) return;
    const entry = toEntry(liveEvent);
    if (seenIds.current.has(entry.id)) return;
    seenIds.current.add(entry.id);
    setEntries(prev => [...prev.slice(-999), entry]);
  }, [liveEvent]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [entries, autoScroll]);

  const onScroll = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(atBottom);
  }, []);

  const visible = entries.filter(e => {
    if (filter === 'stage') return e.type === 'stage_change' || e.type === 'run_complete';
    if (filter === 'done') return e.type === 'run_complete' || (e.type === 'file_status' && e.text.includes(' done'));
    if (filter === 'failed') return e.text.includes('failed') || e.type === 'run_complete';
    return true;
  });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px', borderBottom: '1px solid #1e293b', flexShrink: 0 }}>
        {(['all', 'stage', 'done', 'failed'] as const).map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              padding: '3px 10px', borderRadius: 4, fontSize: '0.75rem', cursor: 'pointer', border: 'none',
              background: filter === f ? '#3b82f6' : '#1e293b',
              color: filter === f ? '#fff' : '#94a3b8',
              fontWeight: filter === f ? 600 : 400,
            }}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: '0.72rem', color: '#94a3b8' }}>
          {visible.length} entries
          {!autoScroll && (
            <button
              onClick={() => { setAutoScroll(true); bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }}
              style={{ marginLeft: 8, padding: '2px 8px', background: '#1e293b', border: 'none', borderRadius: 4, color: '#93c5fd', cursor: 'pointer', fontSize: '0.72rem' }}
            >
              ↓ scroll to bottom
            </button>
          )}
        </span>
        <button
          onClick={() => { setEntries([]); seenIds.current.clear(); }}
          style={{ padding: '3px 10px', background: '#1e293b', border: 'none', borderRadius: 4, color: '#94a3b8', cursor: 'pointer', fontSize: '0.75rem' }}
        >
          Clear
        </button>
      </div>

      {/* Log lines */}
      <div
        ref={containerRef}
        onScroll={onScroll}
        style={{ flex: 1, overflowY: 'auto', padding: '8px 0', fontFamily: 'monospace', fontSize: '0.78rem' }}
      >
        {visible.length === 0 && (
          <div style={{ color: '#94a3b8', padding: '20px 16px' }}>No log entries yet. Start a sync to see activity.</div>
        )}
        {visible.map((e) => (
          <div
            key={e.id}
            style={{ display: 'flex', gap: 10, padding: '2px 16px', lineHeight: 1.5, borderBottom: '1px solid #0f172a' }}
          >
            <span style={{ color: '#94a3b8', flexShrink: 0, fontSize: '0.72rem', paddingTop: 1 }}>{e.ts}</span>
            {e.run_id != null && (
              <span style={{ color: '#94a3b8', flexShrink: 0, fontSize: '0.72rem', paddingTop: 1 }}>#{e.run_id}</span>
            )}
            <span style={{ color: e.color, wordBreak: 'break-word' }}>{e.text}</span>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
