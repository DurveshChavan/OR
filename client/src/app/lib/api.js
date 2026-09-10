// Every service-desk call the client is allowed to make, in one place.
//
// Two things here are not stylistic and will break the application if they are
// changed. First, `credentials: "include"`: the API authenticates with an httpOnly
// session cookie, so a fetch without it signs in successfully and then gets a
// 401 on everything afterwards. Second, the paths: `tests/servicedesk/test_client_contract.py`
// reads the string literals out of this file and fails if one of them is not in
// the frozen `docs/openapi_api.json`, so a path is written as a literal here and
// never assembled somewhere else.
//
// No business logic lives in this file. Nothing recomputes a reason, a risk or
// a cost; the server stores those and the screens display what it returns.

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "";

/** A failure carrying the server's error envelope, so a screen can name it. */
export class ApiError extends Error {
  constructor({ code, message, details, requestId, status }) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details || {};
    this.requestId = requestId;
    this.status = status;
  }
}

async function request(path, { method = "GET", body } = {}) {
  let response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      method,
      credentials: "include",
      headers: body === undefined ? undefined : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (cause) {
    throw new ApiError({
      code: "API_UNREACHABLE",
      message: "The service-desk API did not answer. Is it running?",
      status: 0,
    });
  }

  const requestId = response.headers.get("X-Request-ID");
  const text = await response.text();
  const parsed = text ? safeJson(text) : null;

  if (!response.ok) {
    const envelope = parsed && parsed.error ? parsed.error : {};
    throw new ApiError({
      code: envelope.code || "REQUEST_FAILED",
      message: envelope.message || `${method} ${path} failed (${response.status})`,
      details: envelope.details,
      requestId: (parsed && parsed.request_id) || requestId,
      status: response.status,
    });
  }
  return parsed;
}

function safeJson(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

const get = (path) => request(path);
const post = (path, body) => request(path, { method: "POST", body: body ?? {} });
const patch = (path, body) => request(path, { method: "PATCH", body });
const put = (path, body) => request(path, { method: "PUT", body });

export const api = {
  health: () => get("/api/health"),

  login: (username, password) => post("/api/login", { username, password }),
  logout: () => post("/api/logout"),
  me: () => get("/api/me"),

  listTickets: (query = {}) => get(`/api/tickets${toQuery(query)}`),
  createTicket: (body) => post("/api/tickets", body),
  getTicket: (id) => get(`/api/tickets/${id}`),
  patchTicket: (id, body) => patch(`/api/tickets/${id}`, body),
  listEvents: (id) => get(`/api/tickets/${id}/events`),
  acknowledgeEscalation: (id, note) =>
    post(`/api/tickets/${id}/escalation-acknowledgement`, { note }),
  rescore: (body) => post("/api/tickets/rescore", body ?? {}),

  recommend: (ticketIds, mode) =>
    post("/api/assignment-decisions", { ticket_ids: ticketIds, mode }),
  getDecision: (decisionId) => get(`/api/assignment-decisions/${decisionId}`),
  acceptDecision: (decisionId) =>
    post(`/api/assignment-decisions/${decisionId}/accept`),
  overrideDecision: (decisionId, agentId, reason) =>
    post(`/api/assignment-decisions/${decisionId}/override`, {
      agent_id: agentId,
      reason,
    }),

  listAgents: () => get("/api/agents"),
  createAgent: (body) => post("/api/agents", body),
  patchAgent: (id, body) => patch(`/api/agents/${id}`, body),
  replaceSkills: (id, skills) => put(`/api/agents/${id}/skills`, { skills }),

  listPolicies: () => get("/api/sla-policies"),
  patchPolicy: (id, body) => patch(`/api/sla-policies/${id}`, body),

  riskRadar: (query = {}) => get(`/api/risk-radar${toQuery(query)}`),

  listMachines: (query = {}) => get(`/api/machines${toQuery(query)}`),
  createMachine: (body) => post("/api/machines", body),
  patchMachine: (id, body) => patch(`/api/machines/${id}`, body),
  machineAdvice: (id) => get(`/api/machines/${id}/replacement-advice`),
  fleetAdvice: (query = {}) => get(`/api/replacement-advice${toQuery(query)}`),
  groupAdvice: (body) => post("/api/replacement-advice/group", body),
  linkTicketMachine: (ticketId, machineId) =>
    put(`/api/tickets/${ticketId}/machine`, { machine_id: machineId }),
};

function toQuery(params) {
  const entries = Object.entries(params).filter(
    ([, value]) => value !== undefined && value !== null && value !== ""
  );
  if (!entries.length) return "";
  return `?${new URLSearchParams(entries).toString()}`;
}
