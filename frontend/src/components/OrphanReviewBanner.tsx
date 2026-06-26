// Non-blocking review prompt for mirror extracts whose source file no longer
// exists. The sync NEVER deletes these — it only flags them. The user explicitly
// approves removal here (which trashes them on Drive, recoverable) or keeps them.

import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { ConfirmDialog } from './ConfirmDialog';

interface Props {
  count: number;
  onResolved: () => void; // refresh summary after the user decides
}

export function OrphanReviewBanner({ count, onResolved }: Props) {
  const [names, setNames] = useState<string[]>([]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (count > 0) {
      api.getOrphans().then((r) => setNames(r.orphans.map((o) => o.name))).catch(() => setNames([]));
    }
  }, [count]);

  if (count <= 0) return null;

  const doDelete = async () => {
    setBusy(true);
    try {
      await api.deleteOrphans();
    } finally {
      setBusy(false);
      setConfirming(false);
      onResolved();
    }
  };

  const doKeep = async () => {
    setBusy(true);
    try {
      await api.dismissOrphans();
    } finally {
      setBusy(false);
      onResolved();
    }
  };

  return (
    <>
      <div
        style={{
          background: '#1f2937', border: '1px solid #f59e0b', borderRadius: 10,
          padding: '12px 16px', marginBottom: 12, color: '#fde68a', fontSize: '0.85rem',
        }}
      >
        <div style={{ fontWeight: 700, marginBottom: 4 }}>
          ⚠ Found {count} extract{count !== 1 ? 's' : ''} without a matching source
        </div>
        <div style={{ color: '#cbd5e1', lineHeight: 1.5 }}>
          These transcripts/extracts have no source file in Drive anymore. Nothing was deleted.
          Delete them (moved to Drive trash, recoverable), or keep them?
          {names.length > 0 && (
            <div style={{ marginTop: 6, color: '#94a3b8', fontSize: '0.78rem', maxHeight: 88, overflowY: 'auto' }}>
              {names.slice(0, 8).map((n) => (<div key={n}>• {n}</div>))}
              {names.length > 8 && <div>…and {names.length - 8} more</div>}
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 10, marginTop: 12 }}>
          <button
            disabled={busy}
            onClick={() => setConfirming(true)}
            style={{
              padding: '6px 14px', background: '#b91c1c', border: 'none', borderRadius: 7,
              color: '#fff', fontSize: '0.8rem', fontWeight: 600, cursor: busy ? 'default' : 'pointer',
            }}
          >
            Delete {count}
          </button>
          <button
            disabled={busy}
            onClick={doKeep}
            style={{
              padding: '6px 14px', background: 'transparent', border: '1px solid #334155',
              borderRadius: 7, color: '#cbd5e1', fontSize: '0.8rem', fontWeight: 600,
              cursor: busy ? 'default' : 'pointer',
            }}
          >
            Keep
          </button>
        </div>
      </div>

      <ConfirmDialog
        open={confirming}
        title={`Delete ${count} orphaned extract${count !== 1 ? 's' : ''}?`}
        message={
          <>
            They’ll be moved to <strong>Drive trash</strong> (recoverable for ~30 days), not permanently
            deleted. Their source files no longer exist in your source folder.
          </>
        }
        confirmLabel={busy ? 'Deleting…' : 'Delete'}
        cancelLabel="Cancel"
        onConfirm={doDelete}
        onCancel={() => setConfirming(false)}
      />
    </>
  );
}
