import { apiRequest } from "./client";

export type Account = {
  telegram_user_id: number;
  display_name: string;
  username: string | null;
};

export type AuthStatus = {
  authenticated: boolean;
  account: Account | null;
};

export type AuthStep = {
  challenge_id: string;
  next_step: "code" | "password" | "complete";
  account: Account | null;
};

export function fetchAuthStatus(): Promise<AuthStatus> {
  return apiRequest<AuthStatus>("/api/auth/status");
}

export function startAuth(apiId: number, apiHash: string, phone: string): Promise<AuthStep> {
  return apiRequest<AuthStep>("/api/auth/start", {
    method: "POST",
    body: JSON.stringify({ api_id: apiId, api_hash: apiHash, phone }),
  });
}

export function verifyCode(challengeId: string, code: string): Promise<AuthStep> {
  return apiRequest<AuthStep>("/api/auth/verify-code", {
    method: "POST",
    body: JSON.stringify({ challenge_id: challengeId, code }),
  });
}

export function verifyPassword(challengeId: string, password: string): Promise<AuthStep> {
  return apiRequest<AuthStep>("/api/auth/verify-password", {
    method: "POST",
    body: JSON.stringify({ challenge_id: challengeId, password }),
  });
}

export function logout(): Promise<void> {
  return apiRequest<void>("/api/auth/logout", { method: "POST" });
}
