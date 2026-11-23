import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

/**
 * CollegeBites — Progressive Load Test Suite (Section 4)
 * Target VUs: 1, 5, 10, 25, 50, 100, 250, 500, 1000
 * Designed for isolated local staging / test database execution.
 */

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8010";
const VUS = parseInt(__ENV.TARGET_VUS || "10", 10);
const DURATION = __ENV.DURATION || "12s";
const CANTEEN_ID = __ENV.CANTEEN_ID || "";

export const http4xx = new Counter("http_4xx_errors");
export const http5xx = new Counter("http_5xx_errors");
export const timeoutErrors = new Counter("timeout_errors");
export const failRate = new Rate("failed_requests");
export const latencyTrend = new Trend("response_time_ms", true);

export const options = {
  vus: VUS,
  duration: DURATION,
  thresholds: {
    http_req_duration: ["p(95)<2500"],
  },
};

export default function () {
  const routes = [
    "/health",
    "/api/v1/canteens/college",
    "/api/v1/canteens",
    "/api/v1/pickup/board",
    "/api/v1/menus/allergens",
    "/api/v1/promotions/coupons",
    "/api/v1/meal-plans",
    "/api/v1/events",
  ];
  if (CANTEEN_ID) {
    routes.push(`/api/v1/menus/canteens/${CANTEEN_ID}/categories`);
    routes.push(`/api/v1/menus/canteens/${CANTEEN_ID}/items`);
    routes.push(`/api/v1/queue/canteens/${CANTEEN_ID}`);
  }

  const path = routes[Math.floor(Math.random() * routes.length)];
  const res = http.get(`${BASE_URL}${path}`, {
    timeout: "10s",
    tags: { path },
  });

  latencyTrend.add(res.timings.duration);
  if (res.error_code === 1050 || (res.error && res.error.toLowerCase().includes("timeout"))) {
    timeoutErrors.add(1);
  }
  if (res.status >= 400 && res.status < 500) {
    http4xx.add(1);
  } else if (res.status >= 500 || res.status === 0) {
    http5xx.add(1);
  }

  const ok = check(res, {
    "status is 200": (r) => r.status === 200,
  });
  failRate.add(!ok);
  sleep(0.05);
}
