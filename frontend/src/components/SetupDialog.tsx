import { useState } from 'react';
import { api } from '../api/client';

interface Props {
  onConfigured: (path: string) => void;
}

export function SetupDialog({ onConfigured }: Props) {
  const [path, setPath] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [browsing, setBrowsing] = useState(false);

  async function handleBrowse() {
    setBrowsing(true);
    setError(null);
    try {
      const res = await fetch('/api/config/browse-folder');
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || 'Could not open folder picker.');
      }
      const data = await res.json();
      if (data.path) setPath(data.path);
    } catch (err: any) {
      setError(err.message || 'Could not open folder picker.');
    } finally {
      setBrowsing(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!path.trim()) return;
    setSaving(true);
    setError(null);
    try {
      const res = await api.setDataFolder(path.trim());
      onConfigured(res.data_folder);
    } catch (err: any) {
      setError(err.message || 'Could not save path.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: 1000,
    }}>
      <div style={{
        background: '#1e293b', border: '1px solid #334155',
        borderRadius: 12, padding: 32, width: 500, maxWidth: '90vw',
      }}>
        <h2 style={{ margin: '0 0 8px', fontSize: '1.1rem', color: '#f8fafc' }}>
          Choose a local data folder
        </h2>
        <p style={{ margin: '0 0 20px', fontSize: '0.85rem', color: '#94a3b8', lineHeight: 1.5 }}>
          All local data — downloads, the extracted-text mirror, chunks, and the
          database — is stored under this single folder. Pick one with enough space
          for your media files.
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* Path input + browse button row */}
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              value={path}
              onChange={e => setPath(e.target.value)}
              placeholder="/home/user/drive-content"
              autoFocus
              style={{
                flex: 1,
                background: '#0f172a', border: '1px solid #475569',
                borderRadius: 6, padding: '8px 12px',
                color: '#e2e8f0', fontSize: '0.88rem',
                fontFamily: 'monospace',
              }}
            />
            <button
              type="button"
              onClick={handleBrowse}
              disabled={browsing}
              title="Open folder picker"
              style={{
                background: '#334155',
                color: '#e2e8f0',
                border: '1px solid #475569',
                borderRadius: 6,
                padding: '8px 14px',
                fontSize: '0.88rem',
                cursor: browsing ? 'wait' : 'pointer',
                whiteSpace: 'nowrap',
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                flexShrink: 0,
              }}
            >
              {browsing ? (
                <>
                  <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid #64748b', borderTopColor: '#94a3b8', borderRadius: '50%', animation: 'spin 0.7s linear infinite' }} />
                  Opening…
                </>
              ) : (
                <>
                  <FolderIcon />
                  Browse…
                </>
              )}
            </button>
          </div>

          {error && (
            <div style={{ color: '#f87171', fontSize: '0.82rem' }}>{error}</div>
          )}

          <button
            type="submit"
            disabled={saving || !path.trim()}
            style={{
              background: saving || !path.trim() ? '#334155' : '#3b82f6',
              color: '#fff', border: 'none', borderRadius: 8,
              padding: '9px 20px', fontWeight: 600, fontSize: '0.9rem',
              cursor: saving || !path.trim() ? 'not-allowed' : 'pointer',
              alignSelf: 'flex-start',
            }}
          >
            {saving ? 'Saving…' : 'Confirm'}
          </button>
        </form>
      </div>

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

function FolderIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 20 20" fill="currentColor">
      <path d="M2 6a2 2 0 012-2h4l2 2h6a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
    </svg>
  );
}
