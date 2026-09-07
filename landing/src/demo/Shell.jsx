/* The app chrome, so a demo reads as the product and not as a widget.
   The real .app class is a 100vh grid, which cannot live inside a scrolling
   page, so .demo-shell in landing.css re-creates it at a bounded height.
   Everything inside is the product's own markup and stylesheet. */

import { Mark as BrandMark, IconBoard, IconServices, IconResources, IconAudit, IconExport }
  from "@app/lib/icons.jsx";
import { PROFILE } from "./data";

const NAV = [
  { key: "dashboard", label: "Dashboard", Icon: IconBoard },
  { key: "services",  label: "Services",  Icon: IconServices },
  { key: "resources", label: "Resources", Icon: IconResources },
  { key: "audit",     label: "Audit",     Icon: IconAudit },
  { key: "export",    label: "Export",    Icon: IconExport },
];

export function Shell({ page, onPage, title, children, tall = false }) {
  return (
    <div className={`demo-shell ${tall ? "demo-shell-tall" : ""}`}>
      <aside className="demo-rail" aria-hidden="true">
        <div className="rail-brand">
          <span className="rail-mark"><BrandMark /></span>
          <span className="rail-word">
            <span className="name">SpendSlicer</span>
          </span>
        </div>
        <div className="rail-sect">
          {NAV.slice(0, 3).map(({ key, label, Icon }) => (
            <span key={key} className={`rail-item ${page === key ? "on" : ""}`}>
              <Icon size={18} /><span className="rail-item-text">{label}</span>
            </span>
          ))}
        </div>
        <div className="rail-sect rail-sect-rule">
          {NAV.slice(3).map(({ key, label, Icon }) => (
            <span key={key} className="rail-item">
              <Icon size={18} /><span className="rail-item-text">{label}</span>
            </span>
          ))}
        </div>
      </aside>

      <div className="demo-main">
        <div className="board-bar">
          <span className="board-bar-title">{title}</span>
          <span className="board-bar-spacer" />
          <span className="board-bar-ctls">
            <span className="ctl demo-ctl">Month to date</span>
            <span className="ctl demo-ctl">{PROFILE}</span>
          </span>
        </div>
        <div className="demo-scroll">{children}</div>
      </div>
    </div>
  );
}

/* Tab strip for the surfaces section. The rail above is decorative; this is
   the real control, so it carries the roles and the keyboard handling. */
export function ShellTabs({ tabs, active, onSelect, label }) {
  const keydown = (e) => {
    const i = tabs.findIndex((t) => t.key === active);
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (step) {
      e.preventDefault();
      onSelect(tabs[(i + step + tabs.length) % tabs.length].key);
    } else if (e.key === "Home") {
      e.preventDefault(); onSelect(tabs[0].key);
    } else if (e.key === "End") {
      e.preventDefault(); onSelect(tabs[tabs.length - 1].key);
    }
  };

  return (
    <div className="demo-tabs" role="tablist" aria-label={label} onKeyDown={keydown}>
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          role="tab"
          id={`tab-${t.key}`}
          aria-controls={`panel-${t.key}`}
          aria-selected={active === t.key}
          tabIndex={active === t.key ? 0 : -1}
          className="demo-tab"
          onClick={() => onSelect(t.key)}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
