/* The three surfaces that carry the argument, in the app's own chrome.
   Audit and Export are named in the copy beside this and left out of the
   demo on purpose: a waste list and a file picker explain themselves. */

import { useState } from "react";
import { Shell, ShellTabs } from "./Shell";
import { SurfaceDashboard } from "./SurfaceDashboard";
import { SurfaceServices } from "./SurfaceServices";
import { SurfaceResources } from "./SurfaceResources";

const TABS = [
  { key: "dashboard", label: "Dashboard", title: "Dashboard", Body: SurfaceDashboard },
  { key: "services",  label: "Services",  title: "Services",  Body: SurfaceServices },
  { key: "resources", label: "Resources", title: "Resources", Body: SurfaceResources },
];

export function Surfaces() {
  const [active, setActive] = useState("dashboard");
  const tab = TABS.find((t) => t.key === active);
  const { Body } = tab;

  return (
    <div className="surfaces">
      <ShellTabs tabs={TABS} active={active} onSelect={setActive} label="Product screens" />
      <div
        role="tabpanel"
        id={`panel-${active}`}
        aria-labelledby={`tab-${active}`}
        tabIndex={0}
        className="surfaces-panel"
      >
        <Shell page={active} title={tab.title} tall>
          <Body />
        </Shell>
      </div>
    </div>
  );
}
