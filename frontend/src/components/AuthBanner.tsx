interface Props {
  redirectUri: string;
}

export function AuthBanner({ redirectUri }: Props) {
  function handleConnect() {
    // Open the auth flow in the same tab so the callback redirect works
    window.location.href = '/api/auth/start';
  }

  return (
    <div style={{
      margin: 16,
      background: '#1e293b',
      border: '1px solid #f59e0b55',
      borderRadius: 10,
      padding: '14px 16px',
      display: 'flex',
      flexDirection: 'column',
      gap: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: '1.1rem' }}>🔑</span>
        <strong style={{ color: '#fbbf24', fontSize: '0.9rem' }}>Google Drive not connected</strong>
      </div>
      <p style={{ margin: 0, fontSize: '0.82rem', color: '#94a3b8', lineHeight: 1.5 }}>
        You need to authorize this app to access Google Drive.
        Click the button below — you'll be redirected to Google's consent screen and back here automatically.
      </p>
      <details style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
        <summary style={{ cursor: 'pointer', color: '#94a3b8' }}>Prerequisite: add redirect URI</summary>
        <div style={{ marginTop: 6, lineHeight: 1.6 }}>
          In <a href="https://console.cloud.google.com/apis/credentials" target="_blank" rel="noreferrer" style={{ color: '#60a5fa' }}>Google Cloud Console → Credentials</a>,
          edit your OAuth client and add this to <strong>Authorized redirect URIs</strong>:
          <pre style={{ background: '#0f172a', padding: '6px 10px', borderRadius: 4, margin: '4px 0', fontSize: '0.8rem', color: '#e2e8f0' }}>{redirectUri}</pre>
        </div>
      </details>
      <button
        onClick={handleConnect}
        style={{
          background: '#1d4ed8',
          color: '#fff',
          border: 'none',
          borderRadius: 8,
          padding: '8px 18px',
          fontWeight: 600,
          fontSize: '0.88rem',
          cursor: 'pointer',
          alignSelf: 'flex-start',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"/></svg>
        Connect Google Drive
      </button>
    </div>
  );
}
