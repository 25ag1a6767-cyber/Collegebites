import { describe, expect, it } from "vitest";
import { buildWsUrl, getApiError } from "../api/client";
import { crowdBadgeTone } from "../components/ui/Primitives";

describe("CollegeBites Web Utilities", () => {
  it("maps crowd levels to semantic badge tones", () => {
    expect(crowdBadgeTone("LOW")).toBe("green");
    expect(crowdBadgeTone("MODERATE")).toBe("amber");
    expect(crowdBadgeTone("HIGH")).toBe("red");
    expect(crowdBadgeTone("VERY_HIGH")).toBe("red");
    expect(crowdBadgeTone("TEMPORARILY_UNAVAILABLE")).toBe("slate");
  });

  it("extracts readable errors from API responses and fallbacks", () => {
    expect(getApiError(new Error("boom"), "Fallback msg")).toBe("Fallback msg");
    expect(
      getApiError({ isAxiosError: true, response: { data: { detail: "Slot full" } } }, "Fallback")
    ).toBe("Slot full");
    expect(
      getApiError({ isAxiosError: true, response: { data: { detail: [{ msg: "Field required" }] } } }, "Fallback")
    ).toBe("Field required");
  });

  it("builds authenticated WebSocket URLs when window is available", () => {
    const prevWin = (globalThis as any).window;
    (globalThis as any).window = { location: { protocol: "https:", host: "collegebites-alpha.vercel.app" } };
    try {
      expect(buildWsUrl("/ws/orders/123", { token: "jwt-1" })).toBe(
        "wss://collegebites-alpha.vercel.app/api/v1/ws/orders/123?token=jwt-1"
      );
      expect(buildWsUrl("/ws/orders/123", { guestToken: "CBG.abc" })).toBe(
        "wss://collegebites-alpha.vercel.app/api/v1/ws/orders/123?guest_token=CBG.abc"
      );
    } finally {
      (globalThis as any).window = prevWin;
    }
  });
});
