import http from "k6/http";
import { check, sleep } from "k6";

const BASE_URL = __ENV.BASE_URL;
const CANTEEN_ID = __ENV.CANTEEN_ID;
const FOOD_ITEM_ID = __ENV.FOOD_ITEM_ID;
const AUTH_TOKEN = __ENV.AUTH_TOKEN;
const ADMIN_TOKEN = __ENV.ADMIN_TOKEN;
const VUS = Number(__ENV.VUS || "10");
const DUR = __ENV.DUR || "8s";

export const options = {
  vus: VUS,
  duration: DUR,
  summaryTrendStats: ["avg", "min", "med", "p(90)", "p(95)", "p(99)", "max"],
};

export default function () {
  const roll = Math.random();
  let res;
  if (roll < 0.35) {
    res = http.get(`${BASE_URL}/api/v1/canteens`);
  } else if (roll < 0.62) {
    res = http.get(`${BASE_URL}/api/v1/menus/canteens/${CANTEEN_ID}/items`);
  } else if (roll < 0.78) {
    res = http.get(`${BASE_URL}/api/v1/queue/canteens/${CANTEEN_ID}`);
  } else if (roll < 0.88) {
    res = http.get(`${BASE_URL}/api/v1/pickup/board/${CANTEEN_ID}`);
  } else if (roll < 0.95) {
    res = http.get(`${BASE_URL}/api/v1/food-safety/dashboard?canteen_id=${CANTEEN_ID}`, {
      headers: { Authorization: `Bearer ${ADMIN_TOKEN}` },
    });
  } else {
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
  }
  check(res, { "status 2xx": (r) => r.status >= 200 && r.status < 300 });
  sleep(0.05);
}
