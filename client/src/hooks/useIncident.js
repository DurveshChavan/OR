import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryKeys } from "../lib/queryClient";

export function useIncident(deadlineHours) {
  return useQuery({
    queryKey: [...queryKeys.incident, deadlineHours ?? "default"],
    queryFn: () => api.getIncident(deadlineHours),
  });
}
