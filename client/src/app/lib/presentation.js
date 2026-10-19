import { formatMinutes } from "./format.js";

// The shell is the project title, read left to right: allocate, escalate,
// replace. Hardware replacement is a dispatcher destination as well as a
// manager one, and the reason is the escalation route: a dispatcher deciding
// whether to send a ticket to the replacement decision has to be able to see
// what that decision currently says about the machine. The API agrees - reads
// of the register are open to any signed-in user and only writes are
// manager-only - and the page hides the register form from anyone who cannot
// use it, so a dispatcher lands on numbers rather than on greyed-out controls.
const DISPATCH_NAVIGATION = [
  { to: "/", label: "Queue", end: true },
  { to: "/at-risk", label: "At risk", end: false },
  { to: "/hardware", label: "Hardware replacement", end: false },
];

// Operations is the one genuinely manager-only screen: SLA policy, the resolver
// roster and the manual rescore.
const MANAGER_NAVIGATION = [
  ...DISPATCH_NAVIGATION,
  { to: "/operations", label: "Operations", end: false },
];

// Every route an escalation review can take, in the order a dispatcher should
// consider them, with what each one asks of the person receiving it. The keys
// match `models.ESCALATION_TARGETS`; the server rejects anything else, so this
// list cannot quietly grow a route the desk does not have.
export const ESCALATION_TARGETS = [
  {
    value: "senior_resolver",
    label: "Senior resolver",
    detail: "Ask a senior resolver to take the ticket or advise on it.",
  },
  {
    value: "duty_manager",
    label: "Duty manager",
    detail: "Ask the duty manager to decide priority, staffing or policy.",
  },
  {
    value: "asset_replacement",
    label: "Replacement decision",
    detail: "Put the linked machine to the asset replacement decision.",
    requiresMachine: true,
  },
];

// How a review ends. Each one is a sentence about the ticket, not a status code.
// How a review ends. Each one is a sentence about the ticket, not a status
// code, and the two that assert something the ticket must actually show are
// refused by the server when it does not: a replacement needs the asset link,
// and a reassignment needs an owner that changed. The one that claims least is
// first, so the default selection cannot overstate what a review achieved.
export const ESCALATION_OUTCOMES = [
  {
    value: "no_action",
    label: "Reviewed, no change needed",
  },
  {
    value: "reassigned",
    label: "A different resolver now owns it",
    requiresNewOwner: true,
  },
  {
    value: "replacement_raised",
    label: "A hardware replacement was raised",
    requiresMachine: true,
  },
];

/** The stored target key as a dispatcher reads it. */
export function escalationTargetLabel(target) {
  const found = ESCALATION_TARGETS.find((one) => one.value === target);
  return found ? found.label : "Unnamed reviewer";
}

/** The stored outcome key as a dispatcher reads it. */
export function escalationOutcomeLabel(outcome) {
  const found = ESCALATION_OUTCOMES.find((one) => one.value === outcome);
  return found ? found.label : "Recorded outcome";
}

/** What the replacement arithmetic says about one linked machine, in a sentence. */
export function assetVerdict(advice) {
  if (!advice) return null;
  const overdue = advice.months_until_due < 0;
  const months = Math.abs(Math.round(advice.months_until_due));
  if (advice.verdict === "replace_now") {
    return {
      tone: "critical",
      headline: `${advice.asset_tag}: replace now`,
      detail: `Its own cost figures are cheapest at year ${advice.optimal_replacement_year}, which passed ${months} months ago.`,
      overdue,
    };
  }
  if (advice.verdict === "replace_soon") {
    return {
      tone: "warning",
      headline: `${advice.asset_tag}: replace soon`,
      detail: `Cheapest replacement year is ${advice.optimal_replacement_year}, reached in ${months} months.`,
      overdue,
    };
  }
  return {
    tone: "neutral",
    headline: `${advice.asset_tag}: keep`,
    detail: `Cheapest replacement year is ${advice.optimal_replacement_year}, still ${months} months away.`,
    overdue,
  };
}

export function navigationForRole(role) {
  return role === "manager" ? MANAGER_NAVIGATION : DISPATCH_NAVIGATION;
}

export function atRiskAction(ticket) {
  if (ticket.status === "escalation_review") {
    return {
      label: "Close review",
      detail: `In review with ${escalationTargetLabel(ticket.escalation_target).toLowerCase()}. Record what it decided.`,
      kind: "close",
    };
  }
  if (ticket.overdue || (ticket.priority === 1 && !ticket.current_assignee_id)) {
    return {
      label: "Review assignment",
      detail: "Deadline has passed. Confirm an owner and recovery plan.",
      kind: "assign",
    };
  }
  return {
    label: "Start escalation review",
    detail: "Record the response and move the ticket into escalation review.",
    kind: "escalate",
  };
}

export function recommendationAction(decision) {
  if (decision.state === "recommended" && decision.recommended_agent?.display_name) {
    return {
      label: `Assign to ${displayResolverName(decision.recommended_agent.display_name)}`,
      canAccept: true,
    };
  }
  return { label: "Review triage", canAccept: false };
}

/** Seed provenance belongs in the audit record, not in a resolver's name. */
export function displayResolverName(name) {
  return String(name || "Resolver unavailable").replace(/\s*\(demo\)\s*$/i, "");
}

/** Plain-language companion to the immutable, detailed decision reason. */
export function assignmentSummary(decision) {
  if (!decision?.recommended_agent?.display_name) {
    return "No eligible resolver is available. Review triage before assigning the ticket.";
  }
  const starts = Number(decision.projected_wait_minutes) > 0
    ? `Expected to start in ${formatMinutes(decision.projected_wait_minutes)}.`
    : "Available to start now.";
  const lateness = Number(decision.projected_lateness_minutes) > 0
    ? `Expected to finish ${formatMinutes(decision.projected_lateness_minutes)} after the SLA deadline.`
    : "Expected to finish within the SLA target.";
  return `${displayResolverName(decision.recommended_agent.display_name)} is the suggested resolver. ${starts} ${lateness}`;
}

// ITIL impact and urgency share one scale, 1 the most severe, as UCI-498 records
// them. The priority they produce is derived on the server, never here.
export const LEVELS = [
  { value: 1, label: "High" },
  { value: 2, label: "Medium" },
  { value: 3, label: "Low" },
];

export function levelLabel(value) {
  return LEVELS.find((one) => one.value === Number(value))?.label || "Not assessed";
}

/** A ticket's headline. Tickets from before titles existed get their own fields. */
export function ticketTitle(ticket) {
  if (ticket?.title) return ticket.title;
  const parts = [ticket?.category, ticket?.subcategory].filter(Boolean).join(" / ");
  return parts ? `${parts}${ticket.location ? ` at ${ticket.location}` : ""}` : "Untitled ticket";
}

export function workTypeLabel(value) {
  if (!value) return "No service group recorded";
  return /^category\s+\d+$/i.test(value) ? `Service group ${value}` : value;
}

export function activitySummary(event) {
  const payload = event?.payload || {};
  const detail = payload.reason || payload.note;
  const common = { technicalLabel: "View technical record", technicalOpen: false };

  if (event?.event_type === "TICKET_CREATED") {
    const derived = payload.priority_source === "impact_urgency_matrix"
      ? ` Priority P${payload.priority} came from impact ${levelLabel(payload.impact).toLowerCase()} and urgency ${levelLabel(payload.urgency).toLowerCase()}.`
      : "";
    return { title: "Ticket created", detail: `The ticket entered the queue.${derived}`, ...common };
  }
  if (event?.event_type === "RISK_SCORED") {
    return { title: "SLA risk refreshed", detail: "The system refreshed the SLA risk estimate.", ...common };
  }
  if (event?.event_type === "ASSIGNMENT_RECOMMENDED") {
    return { title: "Assignment suggested", detail: "The system prepared an assignment for review.", ...common };
  }
  if (event?.event_type === "ASSIGNMENT_ACCEPTED") {
    return { title: "Assignment confirmed", detail: "The recommended resolver was assigned.", ...common };
  }
  if (event?.event_type === "ASSIGNMENT_OVERRIDDEN") {
    return {
      title: "Assignment changed",
      detail: detail
        ? `A dispatcher chose a different resolver. Reason: ${detail}`
        : "A dispatcher chose a different resolver.",
      ...common,
    };
  }
  if (event?.event_type === "ESCALATION_RECOMMENDED") {
    return {
      title: "Escalation review suggested",
      detail: "The ticket met the review threshold. A dispatcher must decide the next action.",
      ...common,
    };
  }
  if (event?.event_type === "ESCALATION_ACKNOWLEDGED") {
    return {
      title: "Recovery action recorded",
      detail: detail || "A dispatcher recorded the response to the at-risk ticket.",
      ...common,
    };
  }
  if (event?.event_type === "TICKET_UPDATED" && payload.action === "escalation_review_started") {
    const target = escalationTargetLabel(payload.escalation_target).toLowerCase();
    return {
      title: `Escalation review opened with the ${target}`,
      detail: detail
        ? `The ticket moved to escalation review. Note: ${detail}`
        : "The ticket moved to escalation review.",
      ...common,
    };
  }
  if (event?.event_type === "TICKET_UPDATED" && payload.action === "escalation_review_closed") {
    const outcome = escalationOutcomeLabel(payload.outcome).toLowerCase();
    const asset = payload.replacement
      ? ` Replacement raised for ${payload.replacement.asset_tag}.`
      : "";
    return {
      title: "Escalation review closed",
      detail: `Outcome: ${outcome}.${asset}${detail ? ` Note: ${detail}` : ""}`,
      ...common,
    };
  }
  if (event?.event_type === "TICKET_UPDATED" && payload.action === "ticket_resolved") {
    const outcome = payload.sla_met
      ? "within its SLA deadline"
      : `${formatMinutes(payload.minutes_past_deadline)} after its SLA deadline`;
    return { title: "Resolved", detail: `Resolved ${outcome}.${detail ? ` Note: ${detail}` : ""}`, ...common };
  }
  if (event?.event_type === "TICKET_UPDATED" && payload.action === "ticket_closed") {
    return { title: "Closed", detail: detail ? `Note: ${detail}` : "The resolution was confirmed.", ...common };
  }
  if (event?.event_type === "TICKET_UPDATED" && payload.action === "ticket_reopened") {
    return {
      title: "Reopened",
      detail: `Back in the queue, unassigned; the deadline did not move.${detail ? ` Reason: ${detail}` : ""}`,
      ...common,
    };
  }
  if (event?.event_type === "TICKET_UPDATED" && payload.action === "demo_window_refreshed") {
    return {
      title: "Demo clock re-anchored",
      detail: `Opened and due times moved forward ${formatMinutes(payload.shift_minutes)}; nothing was re-decided.`,
      ...common,
    };
  }
  if (event?.event_type === "TICKET_UPDATED" && payload.field === "machine_id") {
    return payload.machine_id
      ? {
          title: `Affected machine linked: ${payload.asset_tag}`,
          detail:
            "A person stated which machine this ticket is about. Nothing infers " +
            "the link, and the dispatch decision does not read it.",
          ...common,
        }
      : {
          title: "Affected machine unlinked",
          detail: "The ticket is no longer connected to a machine.",
          ...common,
        };
  }
  if (event?.event_type === "TICKET_UPDATED") {
    return { title: "Ticket updated", detail: "Ticket details changed.", ...common };
  }
  return { title: "Activity recorded", detail: "The ticket history was updated.", ...common };
}

export function slaPreview(priority, policies) {
  const policy = (policies || []).find((row) => row.priority === Number(priority));
  if (!policy) return "SLA target will be set from the active policy.";
  return `P${policy.priority} SLA target: ${formatMinutes(policy.target_minutes)}`;
}
