import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, apiRequest } from "./client";

describe("apiRequest", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns JSON from a successful response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ status: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiRequest<{ status: string }>("/api/health")).resolves.toEqual({
      status: "ok",
    });
  });

  it("preserves the safe API error code and message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ code: "origin_forbidden", message: "Источник не разрешён." }),
          { status: 403, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const error = await apiRequest("/api/auth/logout", { method: "POST" }).catch(
      (caught: unknown) => caught,
    );
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 403,
      code: "origin_forbidden",
      message: "Источник не разрешён.",
    });
  });
});
