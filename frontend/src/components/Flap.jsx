import { useEffect, useRef, useState } from "react";

/* Split-flap numerals — the board's signature motion.
   Digits roll to their new value on change; everything else is set solid.
   Under prefers-reduced-motion the roll is instant (CSS drops the transition). */

const DIGITS = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];

function Cell({ digit, delay }) {
  const [shown, setShown] = useState(digit);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      setShown(digit);
      return;
    }
    const t = setTimeout(() => setShown(digit), delay);
    return () => clearTimeout(t);
  }, [digit, delay]);

  const idx = DIGITS.indexOf(shown);
  return (
    <span className="flap-cell">
      <span className="flap-strip" style={{ transform: `translateY(-${Math.max(0, idx) * 0.9}em)` }}>
        {DIGITS.map((d) => (
          <span key={d}>{d}</span>
        ))}
      </span>
    </span>
  );
}

/**
 * `text` is a fully formatted string (e.g. "$1,284.502"). Digits flap;
 * separators, currency marks and letters stay fixed. The whole value is
 * exposed to assistive tech as one string so the roll is never read out
 * character by character.
 */
export function Flap({ text, className = "" }) {
  const chars = String(text ?? "").split("");
  let digitIndex = 0;
  return (
    <span className={`flap ${className}`.trim()}>
      <span className="sr-only">{String(text ?? "")}</span>
      <span className="flap-cells" aria-hidden="true">
        {chars.map((c, i) => {
          if (c >= "0" && c <= "9") {
            const d = digitIndex++;
            return <Cell key={`d${i}`} digit={c} delay={d * 34} />;
          }
          return (
            <span className="flap-fixed" key={`f${i}`}>
              {c}
            </span>
          );
        })}
      </span>
    </span>
  );
}
