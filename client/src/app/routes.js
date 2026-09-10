// The sections of the application. Nothing that is not a section has a route.
//
// "Methods" is where the Operations Research work lives: the linear programme
// that funds a headcount, the transportation and assignment methods, sequencing,
// decision and game theory, the project network, and the replacement analysis
// the hardware advisor uses. It is a section of this product rather than a
// separate demo, because the arithmetic under a recommendation is part of the
// product's argument, not a museum piece beside it.

export const NAV_ITEMS = [
  { to: "/", label: "Queue", end: true },
  { to: "/radar", label: "Risk Radar", end: false },
  { to: "/hardware", label: "Hardware", end: false },
  { to: "/methods", label: "Methods", end: false },
  { to: "/admin", label: "Administration", end: false },
];
