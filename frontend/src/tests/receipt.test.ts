import { describe, expect, it } from "vitest";
import { buildWsUrl, getApiError } from "../api/client";
import { crowdBadgeTone } from "../components/ui/Primitives";
import { buildRazorpayOptions } from "../utils/razorpay";

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

  it("configures Razorpay checkout strictly in locked-amount UPI-only mode", () => {
    const options = buildRazorpayOptions({
      order: {
        id: "ord-1",
        order_number: "CB-20261122-000001",
        canteen_id: "can-1",
        counter_id: "cnt-1",
        order_type: "pickup",
        order_channel: "web",
        status: "PAYMENT_PENDING",
        payment_status: "PENDING",
        payment_method: "razorpay",
        subtotal_amount: "80.00",
        tax_amount: "4.00",
        discount_amount: "0.00",
        total_amount: "84.00",
        estimated_prep_minutes: 10,
        delayed_minutes: 0,
        is_guest: false,
        razorpay_order_id: "order_test_123",
        razorpay_key_id: "rzp_test_key",
        created_at: "2026-11-22T12:00:00Z",
        items: [],
        status_history: [],
      },
      onVerified: () => {},
      onError: () => {},
    });

    expect(options.amount).toBe(8400);
    expect(options.currency).toBe("INR");
    expect(options.order_id).toBe("order_test_123");
    expect(options.config.display.sequence).toEqual(["block.upi"]);
    expect(options.config.display.blocks.upi.instruments).toEqual([{ method: "upi" }]);
    expect(options.config.display.preferences.show_default_blocks).toBe(false);
  });
});
