import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import amLogo from '../assets/am-logo.png';

/**
 * First-run setup wizard. Walks a non-technical user through everything needed
 * before the main UI is usable, in one guided flow:
 *
 *   1. Model        — download the Hebrew transcription model (~3 GB)
 *   2. OAuth client — load the Google OAuth client JSON
 *   3. Sign in      — authorize Google Drive
 *   4. Data folder  — pick where local data is stored
 *
 * Each step reuses an existing backend endpoint (no backend changes). Steps that
 * are already satisfied are skipped silently. The current step is always derived
 * from backend state on mount, so the Google sign-in redirect (which navigates
 * away and back to "/") resumes the wizard at the correct step.
 *
 * Calls onComplete() once all four checks pass.
 */

type StepKey = 'model' | 'oauth' | 'auth' | 'data';

const STEPS: { key: StepKey; label: string }[] = [
  { key: 'model', label: 'Model' },
  { key: 'oauth', label: 'Google client' },
  { key: 'auth', label: 'Sign in' },
  { key: 'data', label: 'Data folder' },
];

interface Status {
  model: boolean;
  oauth: boolean;
  auth: boolean;
  data: boolean;
  gpu: boolean;
  modelRunning: boolean;
  redirectUri: string;
}

interface Props {
  onComplete: () => void;
}

export function FirstRunWizard({ onComplete }: Props) {
  const [status, setStatus] = useState<Status | null>(null);
  const [checking, setChecking] = useState(true);

  // Re-read all four backend checks and recompute which step we're on.
  const refresh = useCallback(async (): Promise<Status> => {
    const [setup, oauth, auth, cfg] = await Promise.all([
      api.getSetupStatus().catch(() => null),
      api.getOAuthClient().catch(() => null),
      api.getAuthStatus().catch(() => null),
      api.getConfig().catch(() => null),
    ]);
    const s: Status = {
      model: !!setup?.ready,
      oauth: !!oauth?.configured,
      auth: !!auth?.authorized,
      data: !!(cfg && (cfg.data_folder_configured as boolean)),
      gpu: !!setup?.gpu_present,
      modelRunning: !!setup?.running,
      redirectUri: auth?.redirect_uri || 'http://localhost:8000/api/auth/callback',
    };
    setStatus(s);
    return s;
  }, []);

  useEffect(() => {
    refresh().finally(() => setChecking(false));
  }, [refresh]);

  // Advance: re-check; if all satisfied, finish.
  const advance = useCallback(async () => {
    const s = await refresh();
    if (s.model && s.oauth && s.auth && s.data) onComplete();
  }, [refresh, onComplete]);

  // If everything is already satisfied on first load, complete immediately
  // (renders nothing) so a returning user never sees the wizard.
  useEffect(() => {
    if (status && status.model && status.oauth && status.auth && status.data) onComplete();
  }, [status, onComplete]);

  if (checking || !status) return null;

  const current = STEPS.find((st) => !status[st.key]);
  if (!current) return null; // all done — onComplete already fired

  const currentIndex = STEPS.findIndex((st) => st.key === current.key);

  return (
    <div style={overlay}>
      <div style={card}>
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 18 }}>
          <img src={amLogo} alt="AM Consulting" style={{ height: 26, display: 'block' }} />
        </div>

        <StepDots steps={STEPS} status={status} currentIndex={currentIndex} />

        <div style={{ marginTop: 20 }}>
          {current.key === 'model' && <ModelStep status={status} onDone={advance} />}
          {current.key === 'oauth' && <OAuthStep onDone={advance} />}
          {current.key === 'auth' && <AuthStep redirectUri={status.redirectUri} onRecheck={advance} />}
          {current.key === 'data' && <DataStep onDone={advance} />}
        </div>
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}

// ── Step indicator ────────────────────────────────────────────────────────────

function StepDots({ steps, status, currentIndex }: {
  steps: typeof STEPS; status: Status; currentIndex: number;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6 }}>
      {steps.map((st, i) => {
        const done = status[st.key];
        const active = i === currentIndex;
        const color = done ? '#10b981' : active ? '#22d3ee' : '#334155';
        return (
          <div key={st.key} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
              <div style={{
                width: 22, height: 22, borderRadius: '50%',
                background: done ? '#10b981' : 'transparent',
                border: `2px solid ${color}`, color: done ? '#0b0f19' : color,
                fontSize: '0.7rem', fontWeight: 700,
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}>
                {done ? '✓' : i + 1}
              </div>
              <span style={{ fontSize: '0.6rem', color: active ? '#e2e8f0' : '#64748b', whiteSpace: 'nowrap' }}>
                {st.label}
              </span>
            </div>
            {i < steps.length - 1 && <div style={{ width: 22, height: 2, background: '#334155', marginBottom: 16 }} />}
          </div>
        );
      })}
    </div>
  );
}

// ── Step 1: model download ────────────────────────────────────────────────────

function ModelStep({ status, onDone }: { status: Status; onDone: () => void }) {
  const [running, setRunning] = useState(status.modelRunning);
  const [message, setMessage] = useState('');
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const subscribe = useCallback(() => {
    const es = new EventSource('/api/setup/stream');
    esRef.current = es;
    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.message) setMessage(data.message);
        if (data.error) { setError(data.error); setRunning(false); es.close(); return; }
        if (data.done) { es.close(); onDone(); }
      } catch { /* ignore malformed frames */ }
    };
    es.onerror = () => { es.close(); };
  }, [onDone]);

  useEffect(() => {
    if (status.modelRunning) subscribe();
    return () => { esRef.current?.close(); };
  }, [status.modelRunning, subscribe]);

  async function start() {
    setError(null);
    setRunning(true);
    setMessage('Starting…');
    try {
      await api.startSetup();
      subscribe();
    } catch (err: any) {
      setError(err?.message || 'Could not start setup.');
      setRunning(false);
    }
  }

  return (
    <div>
      <StepTitle>One-time model download</StepTitle>
      <StepBody>
        The Hebrew transcription model (about <strong>3&nbsp;GB</strong>) is downloaded
        once before first use.{' '}
        {status.gpu
          ? 'An NVIDIA GPU was detected — GPU acceleration libraries will be installed too.'
          : 'No NVIDIA GPU was detected, so transcription will run on the CPU (noticeably slower).'}
        {' '}This needs an internet connection.
      </StepBody>
      {running ? (
        <Spinner text={message || 'Working…'} />
      ) : (
        <PrimaryButton onClick={start}>Download &amp; set up</PrimaryButton>
      )}
      {error && <ErrorWithRetry error={error} onRetry={start} />}
    </div>
  );
}

// ── Step 2: OAuth client JSON ─────────────────────────────────────────────────

function OAuthStep({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paste, setPaste] = useState('');
  const fileRef = useRef<HTMLInputElement>(null);

  async function load(text: string) {
    setBusy(true); setError(null);
    try {
      let parsed: unknown;
      try { parsed = JSON.parse(text); }
      catch { throw new Error('That is not valid JSON.'); }
      await api.setOAuthClient(parsed);
      onDone();
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
    e.target.value = '';
  }

  return (
    <div>
      <StepTitle>Load your Google sign-in file</StepTitle>
      <StepBody>
        Select the Google OAuth client JSON (a Google Cloud Console <em>Desktop app</em>{' '}
        client) provided to you. It is stored on this machine only and used to connect
        Google Drive.
      </StepBody>

      <input ref={fileRef} type="file" accept=".json,application/json" onChange={onFile} style={{ display: 'none' }} />
      <PrimaryButton onClick={() => fileRef.current?.click()} disabled={busy}>
        {busy ? 'Loading…' : 'Choose JSON file…'}
      </PrimaryButton>

      <details style={{ marginTop: 12, fontSize: '0.74rem', color: '#94a3b8' }}>
        <summary style={{ cursor: 'pointer' }}>…or paste the JSON</summary>
        <textarea
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          placeholder='{ "installed": { "client_id": "…", "client_secret": "…", … } }'
          rows={5}
          style={{
            width: '100%', marginTop: 8, padding: '8px 10px', background: '#0d1321',
            border: '1px solid #334155', borderRadius: 6, color: '#f3f4f6',
            fontSize: '0.76rem', fontFamily: 'monospace', resize: 'vertical', boxSizing: 'border-box',
          }}
        />
        <button
          onClick={() => load(paste)}
          disabled={busy || !paste.trim()}
          style={{
            marginTop: 6, padding: '6px 12px', borderRadius: 6, border: 'none', fontWeight: 600,
            fontSize: '0.78rem', color: '#fff',
            background: busy || !paste.trim() ? '#334155' : '#2563eb',
            cursor: busy || !paste.trim() ? 'not-allowed' : 'pointer',
          }}
        >
          Load pasted JSON
        </button>
      </details>

      {error && <p style={{ margin: '10px 0 0', fontSize: '0.78rem', color: '#f87171' }}>{error}</p>}
    </div>
  );
}

// ── Step 3: Google sign-in ────────────────────────────────────────────────────

function AuthStep({ redirectUri, onRecheck }: { redirectUri: string; onRecheck: () => void }) {
  return (
    <div>
      <StepTitle>Connect Google Drive</StepTitle>
      <StepBody>
        Authorize this app to access Google Drive. You'll be redirected to Google's
        consent screen and brought back here automatically.
      </StepBody>

      <details style={{ fontSize: '0.76rem', color: '#94a3b8', marginBottom: 14 }}>
        <summary style={{ cursor: 'pointer' }}>Prerequisite: add redirect URI</summary>
        <div style={{ marginTop: 6, lineHeight: 1.6 }}>
          In{' '}
          <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer" style={{ color: '#38bdf8' }}>
            Google Cloud Console → Credentials
          </a>
          , edit your OAuth client and add this to <strong>Authorized redirect URIs</strong>:
          <pre style={{ background: '#0d1321', padding: '6px 10px', borderRadius: 4, margin: '4px 0', fontSize: '0.78rem', color: '#e2e8f0', whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{redirectUri}</pre>
        </div>
      </details>

      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <PrimaryButton onClick={() => { window.location.href = '/api/auth/start'; }}>
          Connect Google Drive
        </PrimaryButton>
        <button onClick={onRecheck} style={linkButton}>I've already connected — re-check</button>
      </div>
    </div>
  );
}

// ── Step 4: data folder ───────────────────────────────────────────────────────

function DataStep({ onDone }: { onDone: () => void }) {
  const [path, setPath] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [browsing, setBrowsing] = useState(false);

  async function handleBrowse() {
    setBrowsing(true); setError(null);
    try {
      const res = await api.browseFolder();
      if (res.path) setPath(res.path);
    } catch {
      setError('Could not open the folder picker — type the path manually.');
    } finally { setBrowsing(false); }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!path.trim()) return;
    setSaving(true); setError(null);
    try {
      await api.setDataFolder(path.trim());
      onDone();
    } catch (err: any) {
      setError(String(err.message || err).replace(/^\d+\s/, '') || 'Could not save path.');
    } finally { setSaving(false); }
  }

  return (
    <form onSubmit={handleSubmit}>
      <StepTitle>Choose a local data folder</StepTitle>
      <StepBody>
        All local data — downloads, the extracted-text mirror, chunks, and the database —
        is stored under this folder. Pick one with enough space for your media files.
      </StepBody>

      <div style={{ display: 'flex', gap: 8 }}>
        <input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="C:\Users\you\drive-content"
          autoFocus
          style={{
            flex: 1, minWidth: 0, background: '#0d1321', border: '1px solid #334155',
            borderRadius: 6, padding: '8px 12px', color: '#f3f4f6', fontSize: '0.85rem',
            fontFamily: 'monospace',
          }}
        />
        <button
          type="button" onClick={handleBrowse} disabled={browsing}
          style={{
            background: '#334155', color: '#e2e8f0', border: 'none', borderRadius: 6,
            padding: '8px 14px', fontSize: '0.82rem', cursor: browsing ? 'wait' : 'pointer',
            whiteSpace: 'nowrap', fontWeight: 600,
          }}
        >
          {browsing ? 'Opening…' : 'Browse…'}
        </button>
      </div>

      {error && <p style={{ margin: '10px 0 0', fontSize: '0.78rem', color: '#f87171' }}>{error}</p>}

      <div style={{ marginTop: 16 }}>
        <PrimaryButton type="submit" disabled={saving || !path.trim()}>
          {saving ? 'Saving…' : 'Finish setup'}
        </PrimaryButton>
      </div>
    </form>
  );
}

// ── Shared bits ───────────────────────────────────────────────────────────────

function StepTitle({ children }: { children: React.ReactNode }) {
  return <h2 style={{ margin: '0 0 8px', fontSize: '1.05rem', color: '#f3f4f6' }}>{children}</h2>;
}

function StepBody({ children }: { children: React.ReactNode }) {
  return <p style={{ margin: '0 0 16px', fontSize: '0.85rem', color: '#94a3b8', lineHeight: 1.55 }}>{children}</p>;
}

function PrimaryButton({ children, onClick, disabled, type = 'button' }: {
  children: React.ReactNode; onClick?: () => void; disabled?: boolean; type?: 'button' | 'submit';
}) {
  return (
    <button
      type={type} onClick={onClick} disabled={disabled}
      style={{
        background: disabled ? '#334155' : '#2563eb', color: '#fff', border: 'none', borderRadius: 8,
        padding: '9px 20px', fontWeight: 600, fontSize: '0.9rem',
        cursor: disabled ? 'not-allowed' : 'pointer',
      }}
    >
      {children}
    </button>
  );
}

function Spinner({ text }: { text: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0' }}>
      <span style={{
        display: 'inline-block', width: 16, height: 16,
        border: '2px solid #475569', borderTopColor: '#22d3ee',
        borderRadius: '50%', animation: 'spin 0.7s linear infinite',
      }} />
      <span style={{ fontSize: '0.88rem', color: '#e2e8f0' }}>{text}</span>
    </div>
  );
}

function ErrorWithRetry({ error, onRetry }: { error: string; onRetry: () => void }) {
  return (
    <div style={{ marginTop: 14, color: '#f87171', fontSize: '0.82rem' }}>
      {error}
      <div style={{ marginTop: 8 }}>
        <button
          onClick={onRetry}
          style={{
            background: '#334155', color: '#e2e8f0', border: '1px solid #475569',
            borderRadius: 6, padding: '6px 14px', fontSize: '0.82rem', cursor: 'pointer',
          }}
        >
          Retry
        </button>
      </div>
    </div>
  );
}

const overlay: React.CSSProperties = {
  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.8)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1100,
};

const card: React.CSSProperties = {
  background: '#0d1321', border: '1px solid #334155',
  borderRadius: 12, padding: 32, width: 540, maxWidth: '90vw',
};

const linkButton: React.CSSProperties = {
  background: 'none', border: 'none', color: '#94a3b8',
  fontSize: '0.78rem', cursor: 'pointer', textDecoration: 'underline',
};
