import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { NAV_ITEMS } from "../lib/routes";

// Cobalt's signature interactive move: a real ⌘K palette, not just a
// styled-to-look-like-one affordance. Opens via the sidebar button, the
// OPEN_EVENT it dispatches, or Cmd/Ctrl+K from anywhere in the app.
export const OPEN_EVENT = "slatd:open-palette";

export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef(null);
  const restoreFocusRef = useRef(null);
  const navigate = useNavigate();

  const filtered = NAV_ITEMS.filter((item) =>
    (item.label + " " + item.hint).toLowerCase().includes(query.toLowerCase())
  );

  function openPalette() {
    restoreFocusRef.current = document.activeElement;
    setQuery("");
    setActiveIndex(0);
    setOpen(true);
  }

  function closePalette() {
    setOpen(false);
    restoreFocusRef.current?.focus?.();
  }

  useEffect(() => {
    function onKeydown(e) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        open ? closePalette() : openPalette();
      } else if (e.key === "Escape" && open) {
        closePalette();
      }
    }
    function onOpenEvent() {
      openPalette();
    }
    window.addEventListener("keydown", onKeydown);
    window.addEventListener(OPEN_EVENT, onOpenEvent);
    return () => {
      window.removeEventListener("keydown", onKeydown);
      window.removeEventListener(OPEN_EVENT, onOpenEvent);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  useEffect(() => {
    setActiveIndex(0);
  }, [query]);

  function go(item) {
    navigate(item.to);
    closePalette();
  }

  function onKeyDownList(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((i) => (filtered.length ? (i + 1) % filtered.length : 0));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => (filtered.length ? (i - 1 + filtered.length) % filtered.length : 0));
    } else if (e.key === "Enter" && filtered[activeIndex]) {
      e.preventDefault();
      go(filtered[activeIndex]);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-ink/30 pt-24 px-4"
      onClick={closePalette}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md rounded-card border border-rule-2 bg-surface shadow-[0_1px_2px_oklch(24%_0.02_258_/_0.08)] overflow-hidden"
      >
        <div className="flex items-center gap-2 border-b border-rule px-3 py-2.5">
          <span className="font-mono text-xs text-muted" aria-hidden="true">$</span>
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDownList}
            placeholder="Jump to a page..."
            className="flex-1 bg-transparent font-mono text-sm text-ink placeholder:text-muted focus:outline-none"
            aria-label="Search pages"
            role="combobox"
            aria-expanded="true"
            aria-controls="palette-listbox"
            aria-activedescendant={filtered[activeIndex] ? `palette-option-${filtered[activeIndex].to}` : undefined}
            aria-autocomplete="list"
          />
          <kbd className="hidden sm:inline font-mono-label text-[0.625rem] text-muted border border-rule-2 rounded px-1 py-0.5" aria-hidden="true">
            ESC
          </kbd>
          <button
            type="button"
            onClick={closePalette}
            aria-label="Close command palette"
            className="rounded-control p-1.5 text-muted hover:text-ink-2 hover:bg-paper-2 transition-colors duration-150 ease-out"
          >
            <svg width="14" height="14" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <ul id="palette-listbox" role="listbox" aria-label="Pages" className="max-h-72 overflow-y-auto py-1">
          {filtered.length === 0 && (
            <li className="px-3 py-3 text-sm text-muted">No page matches "{query}".</li>
          )}
          {filtered.map((item, i) => (
            <li key={item.to} role="presentation">
              <button
                type="button"
                id={`palette-option-${item.to}`}
                role="option"
                aria-selected={i === activeIndex}
                onClick={() => go(item)}
                onMouseEnter={() => setActiveIndex(i)}
                className={`flex w-full items-center justify-between px-3 py-2.5 text-left text-sm transition-colors duration-150 ease-out ${
                  i === activeIndex ? "bg-accent-soft text-ink" : "text-ink-2"
                }`}
              >
                <span>{item.label}</span>
                <span className="font-mono-label text-[0.625rem] text-muted">{item.hint}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
