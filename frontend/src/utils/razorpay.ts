import { api } from "../api/client";
import type { Order } from "../types";

interface RazorpayInstance {
  open: () => void;
  on?: (event: "payment.failed", handler: (response: { error?: { description?: string; reason?: string; code?: string } }) => void) => void;
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, any>) => RazorpayInstance;
  }
}

export function loadRazorpayCheckoutScript(): Promise<boolean> {
  if (typeof window === "undefined") return Promise.resolve(false);
  if (window.Razorpay) return Promise.resolve(true);
  return new Promise((resolve) => {
    const existing = document.querySelector<HTMLScriptElement>(
      'script[src="https://checkout.razorpay.com/v1/checkout.js"]'
    );
    if (existing) {
      existing.addEventListener("load", () => resolve(Boolean(window.Razorpay)), { once: true });
      existing.addEventListener("error", () => resolve(false), { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = () => resolve(Boolean(window.Razorpay));
    script.onerror = () => resolve(false);
    document.body.appendChild(script);
  });
}

export interface RazorpayModalOptions {
  order: Order;
  prefill?: { name?: string; email?: string; contact?: string };
  description?: string;
  onVerified: (verified: Order) => void;
  onError: (err: unknown) => void;
  onDismiss?: () => void;
}

export function getPublicRazorpayKeyId(order?: Order | null): string | null {
  return order?.razorpay_key_id || import.meta.env.VITE_RAZORPAY_KEY_ID || null;
}

export function buildRazorpayOptions(opts: RazorpayModalOptions): Record<string, any> {
  const { order } = opts;
  return {
    key: getPublicRazorpayKeyId(order),
    amount: Math.round(Number(order.total_amount) * 100),
    currency: "INR",
    name: "CollegeBites",
    description: opts.description || `Order ${order.order_number}`,
    order_id: order.razorpay_order_id,
    prefill: opts.prefill,
    // Force Razorpay Standard Checkout into direct UPI-only mode (UPI Intent on mobile + locked QR on desktop)
    config: {
      display: {
        blocks: {
          upi: {
            name: "Pay directly with UPI App or QR",
            instruments: [{ method: "upi" }],
          },
        },
        sequence: ["block.upi"],
        preferences: {
          show_default_blocks: false,
        },
      },
    },
    retry: { enabled: true },
    theme: { color: "#ea580c" },
    handler: async (response: {
      razorpay_order_id: string;
      razorpay_payment_id: string;
      razorpay_signature: string;
    }) => {
      try {
        const verified = await api.post<Order>("/payments/razorpay/verify", {
          order_id: order.id,
          razorpay_order_id: response.razorpay_order_id,
          razorpay_payment_id: response.razorpay_payment_id,
          razorpay_signature: response.razorpay_signature,
          payment_method: "upi",
        });
        opts.onVerified(verified.data);
      } catch (err) {
        opts.onError(err);
      }
    },
    modal: {
      ondismiss: () => opts.onDismiss?.(),
    },
  };
}

export async function openRazorpayModal(opts: RazorpayModalOptions): Promise<boolean> {
  const { order } = opts;
  const publicKey = getPublicRazorpayKeyId(order);
  if (!order.razorpay_order_id || !publicKey) {
    return false;
  }
  const loaded = await loadRazorpayCheckoutScript();
  if (!loaded || !window.Razorpay) {
    return false;
  }
  const rzp = new window.Razorpay(buildRazorpayOptions(opts));
  rzp.on?.("payment.failed", async (resp) => {
    const reason =
      resp?.error?.description || resp?.error?.reason || "Payment failed on Razorpay";
    try {
      const gTok = order.guest_access_token
        ? `?guest_token=${encodeURIComponent(order.guest_access_token)}`
        : "";
      await api.post(`/payments/razorpay/fail${gTok}`, {
        order_id: order.id,
        razorpay_order_id: order.razorpay_order_id,
        reason: reason.slice(0, 255),
      });
    } catch {
      // Failure recording is best-effort; still surface gateway error cleanly
    }
    opts.onError(new Error(reason));
  });
  rzp.open();
  return true;
}
