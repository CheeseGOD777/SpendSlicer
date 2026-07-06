// frontend/src/hooks/useAsyncData.js
import { useCallback, useEffect, useRef, useState } from "react";
import { recordCe } from "../lib/ceMeter";

/**
 * loader receives an AbortSignal and should pass it to fetch().
 * State only updates from the latest in-flight request.
 * `reload()` re-runs the loader (used by Retry buttons and polls).
 * `backendError` carries HTTP-200 {error:"..."} payload messages.
 */
export function useAsyncData(loader, deps) {
  const [state, setState] = useState({ loading: true, error: "", backendError: null, data: null, meta: null });
  const [tick, setTick] = useState(0);
  const inFlight = useRef(null);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    inFlight.current?.abort();
    const ctrl = new AbortController();
    inFlight.current = ctrl;

    setState((prev) => ({ ...prev, loading: true, error: "" }));

    loader(ctrl.signal)
      .then((result) => {
        if (ctrl.signal.aborted) return;
        const { data, meta } = result ?? {};
        recordCe(meta);
        setState({
          loading: false,
          error: "",
          backendError: meta?.backendError || null,
          data: data ?? null,
          meta: meta || null,
        });
      })
      .catch((err) => {
        if (ctrl.signal.aborted || err?.name === "AbortError") return;
        setState((prev) => ({
          loading: false,
          error: err?.message || "Failed",
          backendError: prev.backendError,
          data: prev.data,
          meta: prev.meta,
        }));
      });

    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  return { ...state, reload };
}
