import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryKeys } from "../lib/queryClient";

export function useDistribution() {
  return useQuery({ queryKey: queryKeys.distribution, queryFn: api.getDistribution });
}

export function useResolveDistribution() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.postDistribution(body),
    onSuccess: (result) => {
      queryClient.setQueryData(queryKeys.distribution, result);
    },
  });
}
