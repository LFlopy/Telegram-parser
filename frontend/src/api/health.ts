export type HealthState = {
  state: "loading" | "online" | "offline";
  body?: HealthBody;
};

export type HealthBody = {
  status: string;
  name?: string;
  version?: string;
  time?: string;
};

const POLL_INTERVAL_MS = 5000;

export async function fetchHealth(): Promise<HealthBody> {
  const resp = await fetch("/api/health", { headers: { Accept: "application/json" } });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return (await resp.json()) as HealthBody;
}

export function healthCheck(onChange: (s: HealthState) => void): () => void {
  let disposed = false;

  const check = async () => {
    try {
      const body = await fetchHealth();
      if (!disposed) onChange({ state: "online", body });
    } catch {
      if (!disposed) onChange({ state: "offline" });
    }
  };

  void check();
  const timer = window.setInterval(() => void check(), POLL_INTERVAL_MS);
  return () => {
    disposed = true;
    window.clearInterval(timer);
  };
}
