import http from "k6/http";
import { check, sleep } from "k6";
import { Trend, Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8015";
const CANTEEN_ID = __ENV.CANTEEN_ID || "";
const FOOD_ITEM_ID = __ENV.FOOD_ITEM_ID || "";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "";
const ADMIN_TOKEN = __ENV.ADMIN_TOKEN || "";

const reqLatency = new Trend("cb_req_latency_ms");
const reqErrorRate = new Rate("cb_req_error_rate");

export const options = {
  scenarios: {
    progressive_enterprise_load: {
      executor: "ramping-vus",
      startVUs: 1,
      stages: [
        { duration: "6s", target: 5 },
        { duration: "6s", target: 10 },
        { duration: "8s", target: 25 },
        { duration: "8s", target: 50 },
        { duration: "10s", target: 100 },
        { duration: "8s", target: 250 },
        { duration: "6s", target: 0 },
      ],
      gracefulRampDown: "3s",
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.15"],
  },
};

export default function () {
  const roll = Math.random();
  let res;

  if (roll < 0.30) {
    res = http.get(`${BASE_URL}/api/v1/canteens`);
  } else if (roll < 0.55 && CANTEEN_ID) {
    res = http.get(`${BASE_URL}/api/v1/menus/canteens/${CANTEEN_ID}/items`);
  } else if (roll < 0.72 && CANTEEN_ID) {
    res = http.get(`${BASE_URL}/api/v1/queue/canteens/${CANTEEN_ID}`);
  } else if (roll < 0.85 && CANTEEN_ID) {
    res = http.get(`${BASE_URL}/api/v1/pickup/board/${CANTEEN_ID}`);
  } else if (roll < 0.93 && ADMIN_TOKEN && CANTEEN_ID) {
    res = http.get(`${BASE_URL}/api/v1/food-safety/dashboard?canteen_id=${CANTEEN_ID}`, {
      headers: { Authorization: `Bearer ${ADMIN_TOKEN}` },
    });
  } else if (AUTH_TOKEN && CANTEEN_ID && FOOD_ITEM_ID) {
    res = http.post(
      `${BASE_URL}/api/v1/orders/checkout`,
      JSON.stringify({
        canteen_id: CANTEEN_ID,
        payment_method: "razorpay",
        use_cart: false,
        direct_items: [{ food_item_id: FOOD_ITEM_ID, quantity: 1 }],
      }),
      {
        headers: {
          Authorization: `Bearer ${AUTH_TOKEN}`,
          "Content-Type": "application/json",
        },
      }
    );
  } else {
    res = http.get(`${BASE_URL}/health`);
  }

  reqLatency.add(res.timings.duration);
  const ok = check(res, {
    "status is 2xx or 429": (r) => (r.status >= 200 && r.status < 300) || r.status === 429,
  });
  reqErrorRate.add(!ok);
  sleep(0.05);
}
