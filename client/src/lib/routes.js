// The legacy Operations Research demo's eight modules.
//
// After the phase 5 cutover these hang off `/legacy`. Both `TopNav` and the
// command palette read this list, so prefixing the paths here moves the whole
// legacy nav at once and neither component had to be touched.

export const NAV_ITEMS = [
  { to: "/legacy", label: "Overview", hint: "scenario" },
  { to: "/legacy/staffing", label: "Staffing Planner", hint: "LPP" },
  { to: "/legacy/regional-load", label: "Regional Load", hint: "transportation" },
  { to: "/legacy/assignment", label: "Ticket Assignment", hint: "Hungarian" },
  { to: "/legacy/work-queue", label: "Work Queue", hint: "Johnson's rule" },
  { to: "/legacy/escalations", label: "Escalation Advisor", hint: "decision + game" },
  { to: "/legacy/incident", label: "Major Incident", hint: "CPM/PERT" },
  { to: "/legacy/hardware", label: "Hardware Health", hint: "replacement" },
];

//: Where these modules used to live. `App.jsx` redirects each one so a link
//: written down before the cutover still lands on the page it named.
export const LEGACY_OLD_PATHS = [
  "/staffing",
  "/regional-load",
  "/assignment",
  "/work-queue",
  "/escalations",
  "/incident",
  "/hardware",
];
