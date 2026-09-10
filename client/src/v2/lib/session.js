// Who is signed in, and what the running build can do.
//
// Both come from the API rather than from anything the browser stores: `/me`
// resolves the httpOnly session cookie, and `/health` says which artifacts
// loaded and which database dialect is serving. The demo badge and the
// manual-dispatch banner are driven from that answer, not from a build flag,
// so a screenshot cannot claim a model that was not there.

import { createContext, useContext } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { v2 } from "./api";

export const SessionContext = createContext(null);

export function useSessionQuery() {
  return useQuery({
    queryKey: ["v2", "me"],
    queryFn: async () => {
      try {
        return await v2.me();
      } catch (error) {
        if (error.status === 401) return null;
        throw error;
      }
    },
    retry: false,
    staleTime: 30_000,
  });
}

export function useHealth() {
  return useQuery({
    queryKey: ["v2", "health"],
    queryFn: v2.health,
    retry: false,
    staleTime: 30_000,
  });
}

export function useSession() {
  return useContext(SessionContext);
}

export function useInvalidateV2() {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: ["v2"] });
}

/** SQLite means the seeded offline database, which the screens must announce. */
export function isOfflineDemo(health) {
  return health?.dialect === "sqlite";
}
