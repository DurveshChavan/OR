// Why an accept button is disabled, worked out from what the API already says.
//
// The server refuses a stale acceptance in `services/decisions.check_not_stale`,
// which compares the policy version and the model version. The client checks
// the same two, plus two more it can see: whether the ticket has been edited
// since the recommendation was written, and whether the recommended resolver is
// still able to take the work. The interface names which of the four moved
// rather than saying "stale"; the server remains the authority, and a refusal
// that arrives anyway is shown with its own message.

export function stalenessReasons({ decision, ticket, policies, agents, health }) {
  if (!decision) return [];
  const reasons = [];

  const policy = (policies || []).find((one) => one.priority === ticket?.priority);
  if (policy && policy.version !== decision.policy_version) {
    reasons.push({
      dimension: "policy",
      text: `The SLA policy for priority ${ticket.priority} moved from version ${decision.policy_version} to ${policy.version} after this recommendation.`,
    });
  }

  const currentModel = health?.risk_model_version;
  if (currentModel && decision.model_version && currentModel !== decision.model_version) {
    reasons.push({
      dimension: "model",
      text: `The recommendation used risk model ${decision.model_version}; the installed artifact is ${currentModel}.`,
    });
  }

  if (ticket && decision.created_at && ticket.updated_at) {
    if (new Date(ticket.updated_at) > new Date(decision.created_at)) {
      reasons.push({
        dimension: "ticket",
        text: "The ticket was edited after this recommendation was written, so it was priced against different fields.",
      });
    }
  }

  const recommendedId = decision.recommended_agent?.id;
  if (recommendedId && agents) {
    const agent = agents.find((one) => one.id === recommendedId);
    if (!agent) {
      reasons.push({
        dimension: "agent",
        text: "The recommended resolver is no longer in the roster.",
      });
    } else if (!agent.is_active) {
      reasons.push({
        dimension: "agent",
        text: `${agent.display_name} has been deactivated since this recommendation.`,
      });
    } else if (
      ticket?.required_skill &&
      !agent.skills.some((skill) => skill.skill === ticket.required_skill)
    ) {
      reasons.push({
        dimension: "agent",
        text: `${agent.display_name} no longer holds the required ${ticket.required_skill} skill.`,
      });
    }
  }
  return reasons;
}

/** Resolvers a dispatcher may override to: active, and holding the skill. */
export function eligibleAgents(agents, requiredSkill) {
  return (agents || []).filter((agent) => {
    if (!agent.is_active) return false;
    if (!requiredSkill) return true;
    return agent.skills.some((skill) => skill.skill === requiredSkill);
  });
}
