// Thin wrapper over the FastAPI engine endpoints. No business logic here --
// every number on screen traces back to one of these calls.

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`${options.method || "GET"} ${path} failed (${res.status}): ${detail}`);
  }
  return res.json();
}

const get = (path) => request(path);
const post = (path, body) => request(path, { method: "POST", body: JSON.stringify(body ?? {}) });

export const api = {
  health: () => get("/api/health"),

  postScenario: (body) => post("/api/scenario", body),

  getStaffing: () => get("/api/staffing"),
  postStaffing: (body) => post("/api/staffing", body),

  getDistribution: () => get("/api/distribution"),
  postDistribution: (body) => post("/api/distribution", body),

  getAssignment: (aged = false) => get(`/api/assignment?aged=${aged ? "true" : "false"}`),

  getSchedule: () => get("/api/schedule"),

  getEscalations: () => get("/api/escalations"),
  getEscalationGame: () => get("/api/escalations/game"),

  getIncident: (deadlineHours) =>
    get(`/api/incident${deadlineHours != null ? `?deadline_hours=${deadlineHours}` : ""}`),

  getHardware: () => get("/api/hardware"),
  postHardwareAge: (months) => post("/api/hardware/age", { months }),
  postHardwareReplace: (workstationIds) => post("/api/hardware/replace", { workstation_ids: workstationIds }),

  getComparison: () => get("/api/comparison"),
};
