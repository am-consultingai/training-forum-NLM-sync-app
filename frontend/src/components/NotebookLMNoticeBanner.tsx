// Surfaces chunk files CREATED or DELETED on Drive during a sync. Each created
// chunk is a NotebookLM source the user must ADD; each deleted one is a source they
// must REMOVE. Without acting, NotebookLM's knowledge base drifts from Drive — so
// this is shown prominently (severity on par with a deletion) until acknowledged.

import { useEffect, useState } from 'react';
import { api } from '../api/client';

interface Props {
  count: number;
  onResolved: () => void; // refresh summary after the user acknowledges
}

export function NotebookLMNoticeBanner({ count, onResolved }: Props) {
  const [created, setCreated] = useState<string[]>([]);
  const [deleted, setDeleted] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (count > 0) {
      api
        .getNotices()
        .then((r) => {
          setCreated(r.created.map((c) => c.chunk_filename));
          setDeleted(r.deleted.map((d) => d.chunk_filename));
        })
        .catch(() => {
          setCreated([]);
          setDeleted([]);
        });
    }
  }, [count]);

  if (count <= 0) return null;

  const acknowledge = async () => {
    setBusy(true);
    try {
      await api.dismissNotices();
    } finally {
      setBusy(false);
      onResolved();
    }
  };

  const list = (names: string[]) => (
    <div style={{ marginTop: 4, color: '#94a3b8', fontSize: '0.78rem', maxHeight: 110, overflowY: 'auto' }}>
      {names.slice(0, 12).map((n) => (
        <div key={n}>• {n}</div>
      ))}
      {names.length > 12 && <div>…and {names.length - 12} more</div>}
    </div>
  );

  return (
    <div
      style={{
        background: '#0b3b2e', border: '1px solid #10b981', borderRadius: 10,
        padding: '12px 16px', marginBottom: 12, color: '#a7f3d0', fontSize: '0.85rem',
      }}
    >
      <div style={{ fontWeight: 700, marginBottom: 4 }}>
        📓 NotebookLM action needed — output sources changed
      </div>
      <div style={{ color: '#cbd5e1', lineHeight: 1.5 }}>
        These output chunk files changed on Drive. NotebookLM won’t reflect them until you
        update its sources to match.
        {created.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <strong style={{ color: '#6ee7b7' }}>Add {created.length} new source{created.length !== 1 ? 's' : ''} to NotebookLM:</strong>
            {list(created)}
          </div>
        )}
        {deleted.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <strong style={{ color: '#fca5a5' }}>Remove {deleted.length} source{deleted.length !== 1 ? 's' : ''} from NotebookLM:</strong>
            {list(deleted)}
          </div>
        )}
      </div>
      <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
        <button
          disabled={busy}
          onClick={acknowledge}
          style={{
            padding: '6px 14px', background: '#047857', border: 'none', borderRadius: 7,
            color: '#fff', fontSize: '0.8rem', fontWeight: 600, cursor: busy ? 'default' : 'pointer',
          }}
        >
          {busy ? 'Saving…' : 'Done — updated NotebookLM'}
        </button>
      </div>
    </div>
  );
}
