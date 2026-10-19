import assert from "node:assert/strict";
import test from "node:test";

import {
  activitySummary,
  assetVerdict,
  assignmentSummary,
  atRiskAction,
  displayResolverName,
  escalationTargetLabel,
  navigationForRole,
  recommendationAction,
  slaPreview,
  ticketTitle,
} from "../src/app/lib/presentation.js";

test("dispatcher navigation is the three things the project title names", () => {
  assert.deepEqual(
    navigationForRole("dispatcher").map((item) => [item.to, item.label]),
    [
      ["/", "Queue"],
      ["/at-risk", "At risk"],
      ["/hardware", "Hardware replacement"],
    ]
  );
});

test("manager navigation adds operations, and never the worksheets", () => {
  assert.deepEqual(
    navigationForRole("manager").map((item) => [item.to, item.label]),
    [
      ["/", "Queue"],
      ["/at-risk", "At risk"],
      ["/hardware", "Hardware replacement"],
      ["/operations", "Operations"],
    ]
  );
});

test("both roles can see all three parts of the project", () => {
  // Allocation, escalation, replacement. A person should be able to see the
  // shape of the project from the shell without being told the title, and that
  // includes a dispatcher: sending a ticket to the replacement decision means
  // nothing if they cannot see what that decision says.
  for (const role of ["dispatcher", "manager"]) {
    const labels = navigationForRole(role).map((item) => item.label);
    assert.ok(labels.includes("Queue"), `${role} allocation`);
    assert.ok(labels.includes("At risk"), `${role} escalation`);
    assert.ok(labels.includes("Hardware replacement"), `${role} replacement`);
    assert.ok(
      !labels.some((label) => label.toLowerCase().includes("method")),
      "the research worksheets stay out of the operational shell"
    );
  }
  assert.ok(
    !navigationForRole("dispatcher").some((item) => item.to === "/operations"),
    "policy and the roster stay manager-only"
  );
});

test("an urgent unassigned ticket asks for assignment review", () => {
  assert.deepEqual(
    atRiskAction({ overdue: true, priority: 1, current_assignee_id: null }),
    {
      label: "Review assignment",
      detail: "Deadline has passed. Confirm an owner and recovery plan.",
      kind: "assign",
    }
  );
});

test("a high-risk assigned ticket asks for a recovery action", () => {
  assert.deepEqual(
    atRiskAction({ overdue: false, priority: 3, current_assignee_id: "agent-1" }),
    {
      label: "Start escalation review",
      detail: "Record the response and move the ticket into escalation review.",
      kind: "escalate",
    }
  );
});

test("a ticket already in review is offered the way out, not another way in", () => {
  // A state a ticket can enter and never leave is the acknowledgement ritual
  // one level up, which is the whole defect this replaced.
  const action = atRiskAction({
    overdue: true,
    priority: 1,
    current_assignee_id: null,
    status: "escalation_review",
    escalation_target: "duty_manager",
  });
  assert.equal(action.kind, "close");
  assert.equal(action.label, "Close review");
  assert.match(action.detail, /duty manager/);
});

test("an escalation target is shown as a person, never as a stored key", () => {
  assert.equal(escalationTargetLabel("senior_resolver"), "Senior resolver");
  assert.equal(escalationTargetLabel("asset_replacement"), "Replacement decision");
});

test("opening a review names who it went to", () => {
  const summary = activitySummary({
    event_type: "TICKET_UPDATED",
    payload: {
      action: "escalation_review_started",
      escalation_target: "senior_resolver",
      note: "Third outage this week.",
    },
  });
  assert.equal(summary.title, "Escalation review opened with the senior resolver");
});

test("closing a review says what it decided, and names the asset when there is one", () => {
  const summary = activitySummary({
    event_type: "TICKET_UPDATED",
    payload: {
      action: "escalation_review_closed",
      outcome: "replacement_raised",
      note: "Raised with asset planning.",
      replacement: { asset_tag: "LAP-0142", verdict: "replace_now" },
    },
  });
  assert.equal(summary.title, "Escalation review closed");
  assert.match(summary.detail, /a hardware replacement was raised/);
  assert.match(summary.detail, /LAP-0142/);
});

test("linking an asset is named in the history, not left as \"ticket updated\"", () => {
  const summary = activitySummary({
    event_type: "TICKET_UPDATED",
    payload: { field: "machine_id", machine_id: "m-1", asset_tag: "WS-1001" },
  });
  assert.equal(summary.title, "Affected machine linked: WS-1001");
});

test("an overdue machine reads as a decision, not as a verdict code", () => {
  const verdict = assetVerdict({
    asset_tag: "LAP-0142",
    verdict: "replace_now",
    optimal_replacement_year: 3,
    months_until_due: -24,
  });
  assert.equal(verdict.tone, "critical");
  assert.equal(verdict.headline, "LAP-0142: replace now");
  assert.match(verdict.detail, /passed 24 months ago/);
});

test("a recommendation uses the real assignment verb", () => {
  assert.deepEqual(
    recommendationAction({
      state: "recommended",
      recommended_agent: { display_name: "Priya Shah" },
    }),
    { label: "Assign to Priya Shah", canAccept: true }
  );
});

test("a non-assignment outcome does not offer a fake accept button", () => {
  assert.deepEqual(
    recommendationAction({ state: "queued", recommended_agent: null }),
    { label: "Review triage", canAccept: false }
  );
});

test("seed provenance is not shown as part of a resolver name", () => {
  assert.equal(displayResolverName("Resolver 12 (demo)"), "Resolver 12");
});

test("an assignment summary reads as an operational decision, not solver output", () => {
  assert.equal(
    assignmentSummary({
      recommended_agent: { display_name: "Resolver 12 (demo)" },
      projected_wait_minutes: 0,
      projected_lateness_minutes: 389,
    }),
    "Resolver 12 is the suggested resolver. Available to start now. Expected to finish 6h 29m after the SLA deadline."
  );
});

test("activity copy is human-readable while technical data stays collapsed", () => {
  const event = {
    event_type: "ASSIGNMENT_OVERRIDDEN",
    payload: {
      recommended_agent_id: "agent-1",
      assigned_agent_id: "agent-2",
      reason: "Priya is covering the outage.",
    },
  };

  assert.deepEqual(activitySummary(event), {
    title: "Assignment changed",
    detail: "A dispatcher chose a different resolver. Reason: Priya is covering the outage.",
    technicalLabel: "View technical record",
    technicalOpen: false,
  });
});

test("ticket creation previews the SLA target before submission", () => {
  assert.equal(
    slaPreview(2, [
      { priority: 1, target_minutes: 60 },
      { priority: 2, target_minutes: 240 },
    ]),
    "P2 SLA target: 4h 00m"
  );
});

test("a ticket's headline is its title, or its own fields when it has none", () => {
  assert.equal(ticketTitle({ title: "VPN drops hourly" }), "VPN drops hourly");
  assert.equal(
    ticketTitle({ category: "Category 42", subcategory: "Subcategory 223", location: "Location 204" }),
    "Category 42 / Subcategory 223 at Location 204"
  );
  assert.equal(ticketTitle({}), "Untitled ticket");
});

test("the lifecycle reads as sentences, including a breach", () => {
  const resolved = (payload) =>
    activitySummary({ event_type: "TICKET_UPDATED", payload: { action: "ticket_resolved", ...payload } });
  assert.match(resolved({ sla_met: true, note: "Reset VPN" }).detail, /within its SLA deadline\. Note: Reset VPN/);
  assert.match(resolved({ sla_met: false, minutes_past_deadline: 125 }).detail, /2h 05m after its SLA deadline/);
  const reopened = activitySummary({ event_type: "TICKET_UPDATED", payload: { action: "ticket_reopened", note: "Back" } });
  assert.equal(reopened.title, "Reopened");
  assert.match(reopened.detail, /deadline did not move/);
});

test("a derived priority says where it came from", () => {
  const created = activitySummary({
    event_type: "TICKET_CREATED",
    payload: { priority: 2, impact: 2, urgency: 1, priority_source: "impact_urgency_matrix" },
  });
  assert.match(created.detail, /P2 came from impact medium and urgency high/);
});
