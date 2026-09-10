// Every version-2 call the client is allowed to make, in one place.
//
// Two things here are not stylistic and will break the application if they are
// changed. First, `credentials: "include"`: v2 authenticates with an httpOnly
// session cookie, so a fetch without it signs in successfully and then gets a
// 401 on everything afterwards. Second, the paths: `tests/v2/test_client_contract.py`
// reads the string literals out of this file and fails if one of them is not in
// the frozen `docs/openapi_v2.json`, so a path is written as a literal here and
// never assembled somewhere else.
//
// No business logic lives in this file. Nothing recomputes a reason, a risk or
// a cost; the server stores those and the screens display what it returns.

const BASE_URL = import.meta.env.VITE_API_V2_BASE_URL || "";

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
      message: "The version-2 API did not answer. Is it running?",
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

export const v2 = {
  health: () => get("/api/v2/health"),

  login: (username, password) => post("/api/v2/login", { username, password }),
  logout: () => post("/api/v2/logout"),
  me: () => get("/api/v2/me"),

  listTickets: (query = {}) => get(`/api/v2/tickets${toQuery(query)}`),
  createTicket: (body) => post("/api/v2/tickets", body),
  getTicket: (id) => get(`/api/v2/tickets/${id}`),
  patchTicket: (id, body) => patch(`/api/v2/tickets/${id}`, body),
  listEvents: (id) => get(`/api/v2/tickets/${id}/events`),
  acknowledgeEscalation: (id, note) =>
    post(`/api/v2/tickets/${id}/escalation-acknowledgement`, { note }),
  rescore: (body) => post("/api/v2/tickets/rescore", body ?? {}),

  recommend: (ticketIds, mode) =>
    post("/api/v2/assignment-decisions", { ticket_ids: ticketIds, mode }),
  getDecision: (decisionId) => get(`/api/v2/assignment-decisions/${decisionId}`),
  acceptDecision: (decisionId) =>
    post(`/api/v2/assignment-decisions/${decisionId}/accept`),
  overrideDecision: (decisionId, agentId, reason) =>
    post(`/api/v2/assignment-decisions/${decisionId}/override`, {
      agent_id: agentId,
      reason,
    }),

  listAgents: () => get("/api/v2/agents"),
  createAgent: (body) => post("/api/v2/agents", body),
  patchAgent: (id, body) => patch(`/api/v2/agents/${id}`, body),
  replaceSkills: (id, skills) => put(`/api/v2/agents/${id}/skills`, { skills }),

  listPolicies: () => get("/api/v2/sla-policies"),
  patchPolicy: (id, body) => patch(`/api/v2/sla-policies/${id}`, body),

  riskRadar: (query = {}) => get(`/api/v2/risk-radar${toQuery(query)}`),
};

function toQuery(params) {
  const entries = Object.entries(params).filter(
    ([, value]) => value !== undefined && value !== null && value !== ""
  );
  if (!entries.length) return "";
  return `?${new URLSearchParams(entries).toString()}`;
}
