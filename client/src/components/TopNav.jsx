import { useState } from "react";
import { NavLink } from "react-router-dom";
import { NAV_ITEMS } from "../lib/routes";
import { OPEN_EVENT } from "./CommandPalette";

function PaletteButton({ className = "" }) {
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new CustomEvent(OPEN_EVENT))}
      className={`flex items-center gap-1.5 rounded-control border border-rule-2 px-2.5 py-2 font-mono-label text-[0.625rem] text-muted hover:text-ink-2 hover:border-accent transition-colors duration-150 ease-out ${className}`}
    >
      <span aria-hidden="true">⌘K</span>
      <span className="sr-only">Open command palette</span>
    </button>
  );
}

// Deliberately not a left sidebar with a list of boxed links — that shape is
// the single most recognisable "generic admin template" tell regardless of
// colour. A numbered tab strip across the top reads as an instrument panel,
// not a CMS nav, and gives every route back the full page width to work with.
export default function TopNav() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-40 border-b border-rule bg-paper-2">
      <div className="flex items-center gap-4 px-4 sm:px-6 h-14">
        <p className="font-mono-label text-xs font-medium text-ink shrink-0">SLA Ticket Desk</p>

        <nav aria-label="Modules" className="hidden md:flex flex-1 min-w-0 overflow-x-auto">
          <ul className="flex items-stretch h-14 -mb-px">
            {NAV_ITEMS.map((item, i) => (
              <li key={item.to} className="shrink-0">
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    `flex h-full items-center gap-1.5 px-3 text-sm border-b-2 whitespace-nowrap transition-colors duration-150 ease-out ${
                      isActive
                        ? "border-accent text-ink font-medium"
                        : "border-transparent text-muted hover:text-ink-2 hover:border-rule-2"
                    }`
                  }
                >
                  <span className="font-mono text-[0.6875rem] text-muted tabular-nums" aria-hidden="true">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>

        <div className="flex-1 md:hidden" />

        <div className="flex items-center gap-2 shrink-0">
          <PaletteButton className="hidden sm:flex" />
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-controls="mobile-nav-sheet"
            aria-label={open ? "Close navigation" : "Open navigation"}
            className="md:hidden rounded-control border border-rule-2 px-2.5 py-2 text-ink-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus focus-visible:outline-offset-2"
          >
            <span className="sr-only">{open ? "Close navigation" : "Open navigation"}</span>
            <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
              {open ? (
                <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              ) : (
                <path d="M2 4h12M2 8h12M2 12h12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {open && (
        <nav
          id="mobile-nav-sheet"
          aria-label="Modules"
          className="md:hidden border-t border-rule bg-paper-2"
        >
          <ul className="py-1">
            {NAV_ITEMS.map((item, i) => (
              <li key={item.to}>
                <NavLink
                  to={item.to}
                  end={item.to === "/"}
                  onClick={() => setOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-2 px-4 py-2.5 text-sm transition-colors duration-150 ease-out ${
                      isActive ? "text-accent font-medium" : "text-muted hover:text-ink-2"
                    }`
                  }
                >
                  <span className="font-mono text-[0.6875rem] tabular-nums" aria-hidden="true">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
          <div className="sm:hidden px-4 pb-3">
            <PaletteButton className="w-full justify-center" />
          </div>
        </nav>
      )}
    </header>
  );
}
