import { describe, expect, it } from "vitest";
import { api, buildWsUrl, getApiError } from "../api/client";
import { crowdBadgeTone } from "../components/ui/Primitives";
import { buildRazorpayOptions, openRazorpayModal } from "../utils/razorpay";

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

  it("wires payment.failed and modal dismiss handlers cleanly", async () => {
    const prevWin = (globalThis as any).window;
    const prevPost = api.post;
    const listeners: Record<string, (p: any) => void> = {};
    const postCalls: Array<{ url: string; body: any }> = [];
    let opened = false;
    let dismissed = false;
    let failedMsg = "";

    (api as any).post = async (url: string, body: any) => {
      postCalls.push({ url, body });
      return { data: {} };
    };
    (globalThis as any).window = {
      Razorpay: class {
        private opts: any;
        constructor(opts: any) {
          this.opts = opts;
        }
        on(event: string, cb: (p: any) => void) {
          listeners[event] = cb;
        }
        open() {
          opened = true;
          this.opts.modal?.ondismiss?.();
        }
      },
    };

    try {
      const ok = await openRazorpayModal({
        order: {
          id: "ord-2",
          order_number: "CB-20261122-000002",
          canteen_id: "can-1",
          counter_id: "cnt-1",
          order_type: "pickup",
          order_channel: "web",
          status: "PAYMENT_PENDING",
          payment_status: "PENDING",
          payment_method: "razorpay",
          subtotal_amount: "50.00",
          tax_amount: "2.50",
          discount_amount: "0.00",
          total_amount: "52.50",
          estimated_prep_minutes: 10,
          delayed_minutes: 0,
          is_guest: true,
          guest_access_token: "CBG.tok",
          razorpay_order_id: "order_real_abc",
          razorpay_key_id: "rzp_test_U3DFJ3eDbjdjRn",
          created_at: "2026-11-22T12:00:00Z",
          items: [],
          status_history: [],
        },
        onVerified: () => {},
        onError: (err) => {
          failedMsg = err instanceof Error ? err.message : String(err);
        },
        onDismiss: () => {
          dismissed = true;
        },
      });
      expect(ok).toBe(true);
      expect(opened).toBe(true);
      expect(dismissed).toBe(true);
      await listeners["payment.failed"]?.({ error: { description: "UPI PIN declined" } });
      expect(failedMsg).toBe("UPI PIN declined");
      expect(postCalls[0].url).toBe("/payments/razorpay/fail?guest_token=CBG.tok");
      expect(postCalls[0].body.reason).toBe("UPI PIN declined");
    } finally {
      (globalThis as any).window = prevWin;
      (api as any).post = prevPost;
    }
  });
});
