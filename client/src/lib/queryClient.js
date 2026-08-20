import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

// Query keys shared between hooks and the mutations that must invalidate
// them (scenario/staffing/hardware changes ripple through most pages,
// since the server holds one scenario in module-level state).
export const queryKeys = {
  staffing: ["staffing"],
  distribution: ["distribution"],
  assignment: (aged) => ["assignment", aged],
  schedule: ["schedule"],
  escalations: ["escalations"],
  escalationGame: ["escalationGame"],
  incident: ["incident"],
  hardware: ["hardware"],
  comparison: ["comparison"],
};

export function invalidateAllScenarioData(queryClient) {
  return queryClient.invalidateQueries();
}
