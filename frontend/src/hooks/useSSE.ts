import { useEffect, useRef } from 'react';
import type { ProgressEvent } from '../types';

// Always-on SSE connection — stays open regardless of isRunning so the
// file tree and spinners update even when a sync was started externally.
export function useSSE(onEvent: (event: ProgressEvent) => void) {
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    let es: EventSource;
    let retryTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      es = new EventSource('/api/progress/stream');

      const handler = (e: MessageEvent) => {
        try {
          const data = JSON.parse(e.data) as ProgressEvent;
          data.type = (e as any).type || 'message';
          onEventRef.current(data);
        } catch {}
      };

      es.addEventListener('file_status', handler);
      es.addEventListener('stage_change', handler);
      es.addEventListener('run_complete', handler);
      es.addEventListener('error', handler);

      // Reconnect on connection error after a short delay
      es.onerror = () => {
        es.close();
        retryTimeout = setTimeout(connect, 3000);
      };
    }

    connect();
    return () => {
      clearTimeout(retryTimeout);
      es?.close();
    };
  }, []); // mount once, stays connected
}
