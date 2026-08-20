import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryKeys } from "../lib/queryClient";

export function useHardware() {
  return useQuery({ queryKey: queryKeys.hardware, queryFn: api.getHardware });
}

export function useComparison() {
  return useQuery({ queryKey: queryKeys.comparison, queryFn: api.getComparison });
}

export function useAgeHardware() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (months) => api.postHardwareAge(months),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.hardware });
      queryClient.invalidateQueries({ queryKey: queryKeys.comparison });
      queryClient.invalidateQueries({ queryKey: ["assignment"] });
    },
  });
}

export function useReplaceHardware() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (workstationIds) => api.postHardwareReplace(workstationIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.hardware });
      queryClient.invalidateQueries({ queryKey: queryKeys.comparison });
      queryClient.invalidateQueries({ queryKey: ["assignment"] });
    },
  });
}
