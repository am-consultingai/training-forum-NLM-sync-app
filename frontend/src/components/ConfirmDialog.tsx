// Reusable dark-theme confirmation modal. Used to warn before applying
// folder-location changes (which trigger reconciliation work on the next sync).

interface Props {
  open: boolean;
  title: string;
  message: React.ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open, title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', onConfirm, onCancel,
}: Props) {
  if (!open) return null;
  return (
    <div
      onClick={onCancel}
      style={{
        position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(2,6,23,0.7)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 480, maxWidth: '100%', background: '#0f172a', border: '1px solid #334155',
          borderRadius: 12, boxShadow: '0 20px 50px rgba(0,0,0,0.6)', padding: '20px 22px',
        }}
      >
        <h3 style={{ margin: '0 0 10px', fontSize: '1rem', fontWeight: 700, color: '#f1f5f9' }}>
          {title}
        </h3>
        <div style={{ fontSize: '0.85rem', color: '#cbd5e1', lineHeight: 1.55 }}>
          {message}
        </div>
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 20 }}>
          <button
            onClick={onCancel}
            style={{
              padding: '7px 16px', background: 'transparent', border: '1px solid #334155',
              borderRadius: 7, color: '#cbd5e1', fontSize: '0.82rem', fontWeight: 600, cursor: 'pointer',
            }}
          >
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            style={{
              padding: '7px 16px', background: '#2563eb', border: 'none',
              borderRadius: 7, color: '#fff', fontSize: '0.82rem', fontWeight: 600, cursor: 'pointer',
            }}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
