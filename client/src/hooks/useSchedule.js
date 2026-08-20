import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { queryKeys } from "../lib/queryClient";

export function useSchedule() {
  return useQuery({ queryKey: queryKeys.schedule, queryFn: api.getSchedule });
}
