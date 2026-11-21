import { api } from "../api/client";
import type { Order } from "../types";

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, any>) => { open: () => void };
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

export async function openRazorpayModal(opts: {
  order: Order;
  prefill?: { name?: string; email?: string; contact?: string };
  description?: string;
  onVerified: (verified: Order) => void;
  onError: (err: unknown) => void;
  onDismiss?: () => void;
}): Promise<boolean> {
  const { order } = opts;
  if (!order.razorpay_order_id || !order.razorpay_key_id) {
    return false;
  }
  const loaded = await loadRazorpayCheckoutScript();
  if (!loaded || !window.Razorpay) {
    return false;
  }
  const rzp = new window.Razorpay({
    key: order.razorpay_key_id,
    amount: Math.round(Number(order.total_amount) * 100),
    currency: "INR",
    name: "CollegeBites",
    description: opts.description || `Order ${order.order_number}`,
    order_id: order.razorpay_order_id,
    prefill: opts.prefill,
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
  });
  rzp.open();
  return true;
}
