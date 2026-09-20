import { useEffect, useRef, useState, useCallback } from 'react';

const MAX_RETRIES = 5;
const NO_RETRY_CODES = new Set([4400, 4401, 4403, 4404]);

function wsBase() {
  // Independent override first (e.g. separate WS terminator in production),
  // then derive wss:// from an absolute VITE_API_BASE_URL, else same-origin.
  const dedicated = import.meta.env.VITE_WS_BASE_URL;
  if (dedicated && /^wss?:\/\//.test(dedicated)) {
    return dedicated.replace(/\/$/, '');
  }
  const configured = import.meta.env.VITE_API_BASE_URL;
  if (configured && /^https?:\/\//.test(configured)) {
    return configured.replace(/\/$/, '').replace(/^http/, 'ws');
  }
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/api/v1`;
}

/**
 * Customer-scoped live queue socket.
 * Server-push only: every event triggers `onEvent`, callers refetch REST
 * (backend remains the source of truth). Bounded reconnect with backoff;
 * auth failures (44xx) are never retried.
 */
export function useQueueSocket({ salonId, barberId, date, enabled = true, onEvent }) {
  const [connected, setConnected] = useState(false);
  const [lastEvent, setLastEvent] = useState(null);
  const socketRef = useRef(null);
  const retriesRef = useRef(0);
  const timerRef = useRef(null);
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  const cleanup = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.onclose = null;
      try {
        socketRef.current.close();
      } catch {
        /* already closed */
      }
      socketRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!enabled || !salonId) return undefined;
    const token = localStorage.getItem('token');
    if (!token) return undefined;

    let stopped = false;
    const params = new URLSearchParams({ token });
    if (barberId) params.set('barber_id', String(barberId));
    if (date) params.set('date', String(date).slice(0, 10));

    const connect = () => {
      if (stopped) return;
      const ws = new WebSocket(`${wsBase()}/ws/queue/${salonId}?${params.toString()}`);
      socketRef.current = ws;

      ws.onopen = () => {
        retriesRef.current = 0;
        setConnected(true);
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          setLastEvent(msg);
          handlerRef.current?.(msg);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = (ev) => {
        setConnected(false);
        socketRef.current = null;
        if (stopped || NO_RETRY_CODES.has(ev.code) || retriesRef.current >= MAX_RETRIES) return;
        const delay = Math.min(1000 * 2 ** retriesRef.current, 16000);
        retriesRef.current += 1;
        timerRef.current = setTimeout(connect, delay);
      };
    };

    connect();
    return () => {
      stopped = true;
      cleanup();
      setConnected(false);
    };
  }, [enabled, salonId, barberId, date, cleanup]);

  return { connected, lastEvent };
}
