import { useEffect, useState } from "react";
import { subscribeCue } from "../lib/cues";

const at = (ts) =>
  new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });

/* THE CUE RAISE — the board announces every change instead of repainting
   silently. Rendered as a live region so the announcement is not visual-only. */
export function CueStrip() {
  const [cue, setCue] = useState(null);
  useEffect(() => subscribeCue(setCue), []);
  if (!cue) return null;
  return (
    <div className="cue" role="status" aria-live="polite">
      <span className={`cue-dot ${cue.kind}`} aria-hidden="true" />
      <span className="cue-what">{cue.what}</span>
      {cue.detail && <span>{cue.detail}</span>}
      <span className="cue-time">{at(cue.at)}</span>
    </div>
  );
}
