import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";

export function useGenerateScenario() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body) => api.postScenario(body),
    onSuccess: () => {
      // the server replaced its whole scenario -- every downstream page's
      // data is stale now, so refetch everything rather than guess which
      // query keys are affected.
      queryClient.invalidateQueries();
    },
  });
}
