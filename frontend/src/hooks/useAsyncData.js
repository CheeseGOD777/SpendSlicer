// frontend/src/hooks/useAsyncData.js
import { useEffect, useRef, useState } from "react";
import { recordCe } from "../lib/ceMeter";

/**
 * loader receives an AbortSignal and should pass it to fetch().
 * State only updates from the latest in-flight request.
 */
export function useAsyncData(loader, deps) {
  const [state, setState] = useState({ loading: true, error: "", data: null, meta: null });
  const inFlight = useRef(null);

  useEffect(() => {
    inFlight.current?.abort();
    const ctrl = new AbortController();
    inFlight.current = ctrl;

    setState((prev) => ({ ...prev, loading: true, error: "" }));

    loader(ctrl.signal)
      .then(({ data, meta }) => {
        if (ctrl.signal.aborted) return;
        recordCe(meta);
        setState({ loading: false, error: "", data, meta: meta || null });
      })
      .catch((err) => {
        if (ctrl.signal.aborted || err?.name === "AbortError") return;
        setState((prev) => ({
          loading: false,
          error: err?.message || "Failed",
          data: prev.data,
          meta: prev.meta,
        }));
      });

    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return state;
}
