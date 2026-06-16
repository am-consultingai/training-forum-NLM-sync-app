import { useEffect, useState } from 'react';
import { api } from '../api/client';

interface Props {
  /** Called once the model is present and the app is ready to use. */
  onReady: () => void;
}

interface SetupEvent {
  message: string;
  fraction: number | null;
  running?: boolean;
  done?: boolean;
  error?: string | null;
}

/**
 * First-run gate. Blocks the app until the Hebrew transcription model (~3 GB) is
 * present locally. If it's missing, offers a one-click download that also fetches
 * NVIDIA CUDA libraries on GPU machines, streaming progress over SSE.
 *
 * While the model is present it renders nothing and immediately reports ready.
 */
export function ModelSetupGate({ onReady }: Props) {
  const [checked, setChecked] = useState(false);
  const [needed, setNeeded] = useState(false);
  const [gpu, setGpu] = useState(false);
  const [running, setRunning] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState<string | null>(null);

  // Initial check.
  useEffect(() => {
    let cancelled = false;
    api.getSetupStatus()
      .then((s) => {
        if (cancelled) return;
        setGpu(s.gpu_present);
        if (s.ready) { onReady(); return; }
        setNeeded(true);
        setRunning(s.running);
        if (s.running) subscribe();
      })
      .catch(() => { /* backend not up yet — show the gate, let the user retry */ setNeeded(true); })
      .finally(() => { if (!cancelled) setChecked(true); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function subscribe() {
    const es = new EventSource('/api/setup/stream');
    es.onmessage = (e) => {
      try {
        const data: SetupEvent = JSON.parse(e.data);
        if (data.message) setMessage(data.message);
        if (data.error) { setError(data.error); setRunning(false); es.close(); return; }
        if (data.done) {
          es.close();
          onReady();
        }
      } catch { /* ignore malformed frames */ }
    };
    es.onerror = () => { es.close(); };
  }

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

  if (!checked || !needed) return null;

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1100,
    }}>
      <div style={{
        background: '#1e293b', border: '1px solid #334155',
        borderRadius: 12, padding: 32, width: 520, maxWidth: '90vw',
      }}>
        <h2 style={{ margin: '0 0 8px', fontSize: '1.1rem', color: '#f8fafc' }}>
          One-time setup
        </h2>
        <p style={{ margin: '0 0 16px', fontSize: '0.85rem', color: '#94a3b8', lineHeight: 1.5 }}>
          The Hebrew transcription model (about <strong>3&nbsp;GB</strong>) needs to be
          downloaded once before first use.
          {' '}
          {gpu
            ? 'An NVIDIA GPU was detected — GPU acceleration libraries will be installed too.'
            : 'No NVIDIA GPU was detected, so transcription will run on the CPU (noticeably slower).'}
          {' '}This only happens on first launch and needs an internet connection.
        </p>

        {running ? (
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0' }}>
            <span style={{
              display: 'inline-block', width: 16, height: 16,
              border: '2px solid #475569', borderTopColor: '#3b82f6',
              borderRadius: '50%', animation: 'spin 0.7s linear infinite',
            }} />
            <span style={{ fontSize: '0.88rem', color: '#e2e8f0' }}>
              {message || 'Working…'}
            </span>
          </div>
        ) : (
          <button
            onClick={start}
            style={{
              background: '#3b82f6', color: '#fff', border: 'none', borderRadius: 8,
              padding: '9px 20px', fontWeight: 600, fontSize: '0.9rem', cursor: 'pointer',
            }}
          >
            Download &amp; set up
          </button>
        )}

        {error && (
          <div style={{ marginTop: 14, color: '#f87171', fontSize: '0.82rem' }}>
            {error}
            <div style={{ marginTop: 8 }}>
              <button
                onClick={start}
                style={{
                  background: '#334155', color: '#e2e8f0', border: '1px solid #475569',
                  borderRadius: 6, padding: '6px 14px', fontSize: '0.82rem', cursor: 'pointer',
                }}
              >
                Retry
              </button>
            </div>
          </div>
        )}
      </div>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
