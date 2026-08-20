import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryKeys } from "../lib/queryClient";

export function useEscalations() {
  return useQuery({ queryKey: queryKeys.escalations, queryFn: api.getEscalations });
}

export function useEscalationGame() {
  return useQuery({ queryKey: queryKeys.escalationGame, queryFn: api.getEscalationGame });
}
