// The three interaction primitives the rest of the interface is built from.
//
// The rules they encode come from Apple's fluid-interface work, translated for
// a data application rather than a gesture-driven one:
//
// * feedback belongs on pointer-down, not on release. A control that waits for
//   a click before acknowledging the press reads as dead, and the delay is the
//   thing people feel even when they cannot name it;
// * motion is critically damped by default - it settles without overshoot.
//   Bounce is reserved for motion a person's own momentum started, and nothing
//   in this application is dragged, so nothing here bounces;
// * every transition animates `transform` and `opacity` only, so it stays on
//   the compositor, and every one of them disappears under
//   `prefers-reduced-motion`.
//
// No animation library. The two curves below and a CSS transition cover a
// screen full of tables; a spring engine would be a dependency to explain at a
// viva for motion nobody can interrupt.

import { useEffect, useRef, useState } from "react";

//: Critically damped feel, response ~0.35s. Used for anything appearing.
export const EASE_SETTLE = "cubic-bezier(0.16, 1, 0.3, 1)";
//: The mirror of it, for anything leaving, so a path in equals the path out.
export const EASE_LEAVE = "cubic-bezier(0.7, 0, 0.84, 0)";

/** A control that acknowledges the press itself, at pointer-down. */
export function PressableProps() {
  return {
    onPointerDown: (event) => {
      const el = event.currentTarget;
      el.style.transition = "transform 90ms " + EASE_SETTLE;
      el.style.transform = "scale(0.975)";
    },
    onPointerUp: releasePress,
    onPointerLeave: releasePress,
    onPointerCancel: releasePress,
  };
}

function releasePress(event) {
  const el = event.currentTarget;
  el.style.transition = "transform 220ms " + EASE_SETTLE;
  el.style.transform = "";
}

/** Button with press feedback and a consistent set of tones. */
export function Button({
  tone = "neutral",
  size = "md",
  className = "",
  children,
  ...rest
}) {
  const tones = {
    accent:
      "bg-accent text-accent-ink border border-transparent hover:brightness-110",
    neutral:
      "bg-surface text-ink border border-rule-2 hover:border-rule-2 hover:bg-paper-2",
    quiet: "bg-transparent text-ink-2 border border-transparent hover:bg-paper-2",
    danger: "bg-transparent text-critical border border-critical/40 hover:bg-critical-soft",
  };
  const sizes = {
    sm: "px-2.5 py-1 text-[13px]",
    md: "px-3.5 py-2 text-sm",
  };
  return (
    <button
      {...PressableProps()}
      {...rest}
      className={
        "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-control)] " +
        "font-medium transition-[background,border-color,filter,opacity] duration-150 " +
        "disabled:cursor-not-allowed disabled:opacity-45 " +
        `${tones[tone]} ${sizes[size]} ${className}`
      }
    >
      {children}
    </button>
  );
}

/** Content that materialises rather than snapping in.
 *
 *  Scale and opacity together, from a stated origin, so a panel reads as
 *  arriving from the thing that opened it instead of fading in from nowhere.
 */
export function Appear({ children, delay = 0, origin = "top center", className = "" }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const id = requestAnimationFrame(() => setShown(true));
    return () => cancelAnimationFrame(id);
  }, []);
  return (
    <div
      className={className}
      style={{
        transformOrigin: origin,
        opacity: shown ? 1 : 0,
        transform: shown ? "none" : "translateY(6px) scale(0.995)",
        transition: `opacity 260ms ${EASE_SETTLE} ${delay}ms, transform 320ms ${EASE_SETTLE} ${delay}ms`,
      }}
    >
      {children}
    </div>
  );
}

/** A number that moves to its new value instead of jumping to it.
 *
 *  Used only where a value updates in place under the reader's eye - a count
 *  that changes after an action. Reduced motion disables it outright rather
 *  than shortening it, because a fast count-up is still motion.
 */
export function useSettledNumber(value, duration = 420) {
  const [shown, setShown] = useState(value);
  const from = useRef(value);
  useEffect(() => {
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced || from.current === value) {
      from.current = value;
      setShown(value);
      return undefined;
    }
    const start = performance.now();
    const origin = from.current;
    let frame;
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      // Same settle curve as the CSS one, evaluated directly.
      const eased = 1 - Math.pow(1 - t, 3);
      setShown(origin + (value - origin) * eased);
      if (t < 1) frame = requestAnimationFrame(step);
      else from.current = value;
    };
    frame = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame);
  }, [value, duration]);
  return shown;
}
