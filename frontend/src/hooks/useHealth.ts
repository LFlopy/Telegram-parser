import { useEffect, useState } from "react";
import { healthCheck, type HealthState } from "../api/health";

export function useHealth(): HealthState {
  const [health, setHealth] = useState<HealthState>({ state: "loading" });

  useEffect(() => healthCheck(setHealth), []);

  return health;
}
