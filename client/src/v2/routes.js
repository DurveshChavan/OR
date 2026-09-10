// The four screens, plus sign-in. Four is the whole first release (spec I):
// anything that is not queue, ticket detail, Risk Radar or administration does
// not have a route here.

export const V2_NAV = [
  { to: "/v2", label: "Queue", hint: "dispatch", end: true },
  { to: "/v2/radar", label: "Risk Radar", hint: "review", end: false },
  { to: "/v2/admin", label: "Administration", hint: "manager", end: false },
];
