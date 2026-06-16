import { useState, useEffect, useRef } from 'react';
import { api } from '../api/client';
import { ConfirmDialog } from './ConfirmDialog';

type ConfirmRequest = { title: string; message: React.ReactNode; onConfirm: () => void; onCancel: () => void };

// ── Reusable auto-saving text setting (no Save button) ────────────────────────
// Persists on blur and on Enter. Folder-location fields route through a
// confirmation popup before saving (and revert the input on cancel).

function TextSetting({
  label, description, initial, placeholder, onSave, browse, mono, confirm, requestConfirm, footer,
}: {
  label: string;
  description: React.ReactNode;
  initial: string;
  placeholder?: string;
  onSave: (value: string) => Promise<string>;
  browse?: boolean;
  mono?: boolean;
  confirm?: { title: string; message: React.ReactNode };
  requestConfirm: (req: ConfirmRequest) => void;
  footer?: React.ReactNode;
}) {
  const [value, setValue] = useState(initial);
  const [status, setStatus] = useState<'idle' | 'saving' | 'saved'>('idle');
  const [error, setError] = useState<string | null>(null);
  const [browsing, setBrowsing] = useState(false);
  const savedRef = useRef(initial);

  useEffect(() => { setValue(initial); savedRef.current = initial; }, [initial]);

  async function doSave(v: string) {
    setStatus('saving');
    setError(null);
    try {
      const result = await onSave(v.trim());
      setValue(result);
      savedRef.current = result;
      setStatus('saved');
      setTimeout(() => setStatus('idle'), 2000);
    } catch (e: any) {
      setError(String(e.message || e).replace(/^\d+\s/, ''));
      setStatus('idle');
    }
  }

  function attemptSave(v: string = value) {
    if (v.trim() === savedRef.current.trim()) return;  // unchanged → nothing to save
    if (confirm) {
      requestConfirm({
        title: confirm.title,
        message: confirm.message,
        onConfirm: () => doSave(v),
        onCancel: () => setValue(savedRef.current),
      });
    } else {
      doSave(v);
    }
  }

  async function handleBrowse() {
    setBrowsing(true);
    setError(null);
    try {
      const res = await api.browseFolder();
      if (res.path) { setValue(res.path); attemptSave(res.path); }
    } catch {
      setError('Could not open folder picker — type the path manually.');
    } finally {
      setBrowsing(false);
    }
  }

  return (
    <div style={{ marginBottom: 26 }}>
      <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>
        {label}
      </label>
      <p style={{ margin: '0 0 10px', fontSize: '0.75rem', color: '#94a3b8', lineHeight: 1.5 }}>
        {description}
      </p>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input
          type="text"
          value={value}
          placeholder={placeholder}
          onChange={(e) => setValue(e.target.value)}
          onBlur={() => attemptSave()}
          onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
          style={{
            flex: 1, minWidth: 0, padding: '6px 10px', background: '#1e293b',
            border: `1px solid ${error ? '#b91c1c' : '#334155'}`, borderRadius: 6,
            color: '#f1f5f9', fontSize: '0.82rem', fontFamily: mono ? 'monospace' : 'inherit',
          }}
        />
        {browse && (
          <button
            onClick={handleBrowse}
            disabled={browsing}
            style={{
              padding: '6px 12px', background: '#334155', border: 'none', borderRadius: 6,
              color: '#e2e8f0', fontSize: '0.78rem', cursor: browsing ? 'wait' : 'pointer',
              fontWeight: 600, whiteSpace: 'nowrap',
            }}
          >
            {browsing ? '…' : 'Browse'}
          </button>
        )}
        <span style={{
          fontSize: '0.72rem', fontWeight: 600, whiteSpace: 'nowrap', width: 64, textAlign: 'right',
          color: status === 'saved' ? '#4ade80' : '#64748b',
        }}>
          {status === 'saving' ? 'Saving…' : status === 'saved' ? '✓ Saved' : 'Auto-saves'}
        </span>
      </div>
      {error && <p style={{ margin: '6px 0 0', fontSize: '0.72rem', color: '#f87171' }}>{error}</p>}
      {footer}
    </div>
  );
}

// ── Google OAuth client loader ────────────────────────────────────────────────
// The OAuth client secret is NOT shipped with the app. The user loads the JSON
// downloaded from Google Cloud Console here, once; it's stored locally and used
// for sign-in.

function OAuthClientSetting() {
  const [status, setStatus] = useState<{ configured: boolean; client_id: string | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [paste, setPaste] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { api.getOAuthClient().then(setStatus).catch(() => {}); }, []);

  async function load(text: string) {
    setBusy(true); setError(null); setSaved(false);
    try {
      let parsed: unknown;
      try { parsed = JSON.parse(text); }
      catch { throw new Error('That is not valid JSON.'); }
      const res = await api.setOAuthClient(parsed);
      setStatus({ configured: true, client_id: res.client_id });
      setPaste('');
      setSaved(true); setTimeout(() => setSaved(false), 2500);
    } catch (e: any) {
      setError(String(e.message || e).replace(/^\d+\s/, ''));
    } finally { setBusy(false); }
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => load(String(reader.result || ''));
    reader.onerror = () => setError('Could not read that file.');
    reader.readAsText(file);
    e.target.value = '';  // allow re-selecting the same file
  }

  return (
    <div style={{ marginBottom: 26 }}>
      <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>
        Google OAuth client
      </label>
      <p style={{ margin: '0 0 10px', fontSize: '0.75rem', color: '#94a3b8', lineHeight: 1.5 }}>
        Sign-in credentials are not bundled with the app. Load the OAuth client JSON
        (a Google Cloud Console <em>Desktop app</em> client) provided to you. It's stored
        on this machine only and used to connect Google Drive.
      </p>

      <div style={{
        fontSize: '0.76rem', marginBottom: 10,
        color: status?.configured ? '#4ade80' : '#fbbf24',
      }}>
        {status == null ? '…'
          : status.configured
            ? <>✓ Loaded — client&nbsp;ID <span style={{ fontFamily: 'monospace', color: '#cbd5e1' }}>{status.client_id}</span></>
            : '⚠ No credentials loaded yet — sign-in is disabled until you load them.'}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input ref={fileRef} type="file" accept=".json,application/json" onChange={onFile} style={{ display: 'none' }} />
        <button
          onClick={() => fileRef.current?.click()}
          disabled={busy}
          style={{
            padding: '6px 12px', background: '#334155', border: 'none', borderRadius: 6,
            color: '#e2e8f0', fontSize: '0.78rem', cursor: busy ? 'wait' : 'pointer', fontWeight: 600,
          }}
        >
          {busy ? 'Loading…' : 'Choose JSON file…'}
        </button>
        {saved && <span style={{ fontSize: '0.72rem', fontWeight: 600, color: '#4ade80' }}>✓ Saved</span>}
      </div>

      <details style={{ marginTop: 10, fontSize: '0.74rem', color: '#94a3b8' }}>
        <summary style={{ cursor: 'pointer' }}>…or paste the JSON</summary>
        <textarea
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          placeholder='{ "installed": { "client_id": "…", "client_secret": "…", … } }'
          rows={5}
          style={{
            width: '100%', marginTop: 8, padding: '8px 10px', background: '#1e293b',
            border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9',
            fontSize: '0.76rem', fontFamily: 'monospace', resize: 'vertical', boxSizing: 'border-box',
          }}
        />
        <button
          onClick={() => load(paste)}
          disabled={busy || !paste.trim()}
          style={{
            marginTop: 6, padding: '6px 12px', borderRadius: 6, border: 'none', fontWeight: 600,
            fontSize: '0.78rem', color: '#fff',
            background: busy || !paste.trim() ? '#334155' : '#3b82f6',
            cursor: busy || !paste.trim() ? 'not-allowed' : 'pointer',
          }}
        >
          Load pasted JSON
        </button>
      </details>

      {error && <p style={{ margin: '8px 0 0', fontSize: '0.72rem', color: '#f87171' }}>{error}</p>}
    </div>
  );
}

// ── Settings panel ────────────────────────────────────────────────────────────

export function SettingsPanel() {
  const [cfg, setCfg] = useState<any | null>(null);
  const [confirmReq, setConfirmReq] = useState<ConfirmRequest | null>(null);

  const [chunkInput, setChunkInput] = useState<string>('5');
  const [chunkSaved, setChunkSaved] = useState(false);
  const chunkSavedRef = useRef<string>('5');

  useEffect(() => {
    api.getConfig().then((c) => {
      setCfg(c);
      const mb = String(Number(c.chunk_size_mb) || 5);
      setChunkInput(mb);
      chunkSavedRef.current = mb;
    }).catch(() => {});
  }, []);

  function requestConfirm(req: ConfirmRequest) { setConfirmReq(req); }

  async function saveChunk() {
    const mb = parseFloat(chunkInput);
    if (isNaN(mb) || mb <= 0 || String(mb) === chunkSavedRef.current) return;
    try {
      const result = await api.setChunkSizeMb(mb);
      const v = String(result.chunk_size_mb);
      setChunkInput(v);
      chunkSavedRef.current = v;
      setChunkSaved(true);
      setTimeout(() => setChunkSaved(false), 2000);
    } catch {}
  }

  if (!cfg) {
    return <div style={{ padding: '20px 24px', color: '#94a3b8', fontSize: '0.85rem' }}>Loading settings…</div>;
  }

  const chunkSizeMb = Number(cfg.chunk_size_mb) || 5;
  const estimatedFiles = chunkSizeMb > 0 ? Math.ceil(500 / chunkSizeMb) : '—';

  return (
    <div style={{ padding: '20px 24px', maxWidth: 560 }}>
      <h2 style={{ margin: '0 0 8px', fontSize: '0.9rem', fontWeight: 700, color: '#f1f5f9', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
        Settings
      </h2>
      <p style={{ margin: '0 0 22px', fontSize: '0.72rem', color: '#94a3b8' }}>
        Changes save automatically and take effect on the next sync run.
      </p>

      <SectionTitle>Google sign-in</SectionTitle>

      <OAuthClientSetting />

      <SectionTitle>Google Drive folders</SectionTitle>

      <TextSetting
        label="Input content folder (Drive URL)"
        description="The Drive folder to read source files from. Paste the folder's share URL or its ID."
        initial={cfg.source_folder_url || ''}
        placeholder="https://drive.google.com/drive/folders/…"
        mono requestConfirm={requestConfirm}
        confirm={{
          title: 'Change the source Drive folder?',
          message: 'This changes which Drive folder is treated as the source of truth. On the next sync the app will re-discover files, process any new ones, and remove from the mirror any extracts whose source no longer exists.',
        }}
        onSave={async (v) => (await api.setSourceFolder(v)).url}
      />

      <TextSetting
        label="Chunks (output) folder (Drive URL)"
        description="The Drive folder that aggregated chunk files are uploaded to (NotebookLM syncs from here)."
        initial={cfg.output_folder_url || ''}
        placeholder="https://drive.google.com/drive/folders/…"
        mono requestConfirm={requestConfirm}
        confirm={{
          title: 'Change the chunks (output) Drive folder?',
          message: 'This changes where aggregated chunks are stored and that NotebookLM syncs from. On the next sync, chunks are reconciled against this folder (existing chunks reused by name, obsolete ones removed). Remember to re-point NotebookLM at this folder.',
        }}
        onSave={async (v) => (await api.setOutputFolder(v)).url}
      />

      <TextSetting
        label="Extracted text (mirror) folder (Drive URL)"
        description="The Drive folder that per-file extracted text is mirrored to, so already-processed files are reused across machines."
        initial={cfg.extracted_text_folder_url || ''}
        placeholder="https://drive.google.com/drive/folders/…"
        mono requestConfirm={requestConfirm}
        confirm={{
          title: 'Change the mirror Drive folder?',
          message: 'This changes where per-file extracted text is cached for reuse across machines. On the next sync the app reconciles the mirror against this folder; extracts not present here may be re-uploaded.',
        }}
        onSave={async (v) => (await api.setExtractedTextFolder(v)).url}
      />

      <SectionTitle>Local storage</SectionTitle>

      <TextSetting
        label="Data folder"
        description="Where the app keeps its data for this machine. Pick a folder with enough space for your media."
        initial={cfg.data_folder || ''}
        placeholder="/path/to/data"
        mono browse requestConfirm={requestConfirm}
        confirm={{
          title: 'Change the data folder?',
          message: (
            <>
              This changes where the app stores its data on this machine. If the new folder doesn't already
              have your content, the app may need to <strong>download some of it again</strong> on the next sync.
              Anything already there is reused, so no work is wasted.
            </>
          ),
        }}
        onSave={async (v) => {
          const r = await api.setDataFolder(v);
          api.getConfig().then(setCfg).catch(() => {});  // refresh derived paths
          return r.data_folder;
        }}
        footer={
          <div style={{ marginTop: 8, fontSize: '0.72rem', color: '#94a3b8' }}>
            Takes effect immediately — no restart needed.
          </div>
        }
      />

      <SectionTitle>Processing</SectionTitle>

      <TextSetting
        label="Ignore extensions"
        description="Comma-separated list of file extensions to skip entirely during processing (e.g. .tmp, .zip, .ico)."
        initial={(cfg.ignore_extensions || []).join(', ')}
        placeholder=".tmp, .zip, .ico"
        mono requestConfirm={requestConfirm}
        onSave={async (v) => {
          const exts = v.split(/[,\s]+/).map((s) => s.trim()).filter(Boolean);
          const res = await api.setIgnoreExtensions(exts);
          return res.ignore_extensions.join(', ');
        }}
      />

      {/* Chunk size — auto-saves on blur/Enter */}
      <div style={{ marginBottom: 26 }}>
        <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: '#94a3b8', marginBottom: 6 }}>
          Chunk size (MB)
        </label>
        <p style={{ margin: '0 0 10px', fontSize: '0.75rem', color: '#94a3b8', lineHeight: 1.5 }}>
          Maximum size of each aggregated output file uploaded to Drive. Smaller chunks = more files.
          NotebookLM supports up to 300 sources.
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input
            type="number" min="1" max="200" step="1"
            value={chunkInput}
            onChange={(e) => setChunkInput(e.target.value)}
            onBlur={saveChunk}
            onKeyDown={(e) => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur(); }}
            style={{
              width: 80, padding: '6px 10px', background: '#1e293b',
              border: '1px solid #334155', borderRadius: 6, color: '#f1f5f9', fontSize: '0.85rem',
            }}
          />
          <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>MB</span>
          <span style={{ fontSize: '0.72rem', fontWeight: 600, color: chunkSaved ? '#4ade80' : '#64748b' }}>
            {chunkSaved ? '✓ Saved' : 'Auto-saves'}
          </span>
        </div>
        <p style={{ margin: '8px 0 0', fontSize: '0.72rem', color: '#94a3b8' }}>
          At {chunkSizeMb} MB/chunk with ~500 MB of content ≈ {estimatedFiles} output files
        </p>
      </div>

      {/* File relevance info */}
      <div style={{ padding: '12px 14px', background: '#0f172a', borderRadius: 8, border: '1px solid #1e293b' }}>
        <p style={{ margin: 0, fontSize: '0.75rem', color: '#94a3b8', lineHeight: 1.6 }}>
          <strong style={{ color: '#cbd5e1' }}>File relevance</strong> — hover over any file in the tree and click{' '}
          <span style={{ fontFamily: 'monospace', background: '#1e293b', padding: '1px 5px', borderRadius: 3 }}>✓</span>{' '}
          to toggle it as <em>not relevant</em>. Ignored files are shown dimmed and excluded from aggregated output.
        </p>
      </div>

      <ConfirmDialog
        open={!!confirmReq}
        title={confirmReq?.title || ''}
        message={confirmReq?.message}
        confirmLabel="Apply change"
        onConfirm={() => { confirmReq?.onConfirm(); setConfirmReq(null); }}
        onCancel={() => { confirmReq?.onCancel(); setConfirmReq(null); }}
      />
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 style={{
      margin: '0 0 14px', fontSize: '0.72rem', fontWeight: 700, color: '#94a3b8',
      textTransform: 'uppercase', letterSpacing: '0.06em',
      borderBottom: '1px solid #1e293b', paddingBottom: 6,
    }}>
      {children}
    </h3>
  );
}
