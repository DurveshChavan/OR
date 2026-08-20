import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryKeys } from "../lib/queryClient";

export function useAssignment(aged = false, options = {}) {
  return useQuery({
    queryKey: queryKeys.assignment(aged),
    queryFn: () => api.getAssignment(aged),
    ...options,
  });
}
