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

type ApiErrorBody = {
  code?: string;
  message?: string;
};

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });

  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiErrorBody;
    throw new ApiError(
      response.status,
      body.code ?? "request_failed",
      body.message ?? `Ошибка запроса (${response.status})`,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function fetchAuthStatus(): Promise<AuthStatus> {
  return request<AuthStatus>("/api/auth/status");
}

export function startAuth(apiId: number, apiHash: string, phone: string): Promise<AuthStep> {
  return request<AuthStep>("/api/auth/start", {
    method: "POST",
    body: JSON.stringify({ api_id: apiId, api_hash: apiHash, phone }),
  });
}

export function verifyCode(challengeId: string, code: string): Promise<AuthStep> {
  return request<AuthStep>("/api/auth/verify-code", {
    method: "POST",
    body: JSON.stringify({ challenge_id: challengeId, code }),
  });
}

export function verifyPassword(challengeId: string, password: string): Promise<AuthStep> {
  return request<AuthStep>("/api/auth/verify-password", {
    method: "POST",
    body: JSON.stringify({ challenge_id: challengeId, password }),
  });
}

export function logout(): Promise<void> {
  return request<void>("/api/auth/logout", { method: "POST" });
}
