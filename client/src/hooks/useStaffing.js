import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryKeys } from "../lib/queryClient";

export function useStaffing() {
  return useQuery({ queryKey: queryKeys.staffing, queryFn: api.getStaffing });
}

export function useResolveStaffing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.postStaffing(body),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.staffing, result);
      // funded headcount changed -> assignment/schedule/escalations/
      // hardware comparisons downstream of it are stale.
      queryClient.invalidateQueries({ queryKey: ["assignment"] });
      queryClient.invalidateQueries({ queryKey: queryKeys.schedule });
      queryClient.invalidateQueries({ queryKey: queryKeys.escalations });
      queryClient.invalidateQueries({ queryKey: queryKeys.comparison });
    },
  });
}
