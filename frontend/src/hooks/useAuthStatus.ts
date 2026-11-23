import { useCallback, useEffect, useState } from "react";
import { fetchAuthStatus, type AuthStatus } from "../api/auth";

type AuthStatusState =
  | { state: "loading"; data: null }
  | { state: "ready"; data: AuthStatus }
  | { state: "error"; data: null };

export function useAuthStatus() {
  const [status, setStatus] = useState<AuthStatusState>({ state: "loading", data: null });

  const refresh = useCallback(async () => {
    try {
      const data = await fetchAuthStatus();
      setStatus({ state: "ready", data });
    } catch {
      setStatus({ state: "error", data: null });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { status, refresh };
}
