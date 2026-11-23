import http from "k6/http";
import { check, sleep } from "k6";

/**
 * CollegeBites — Endurance / Soak Testing Script (Section 8)
 * Configurable duration via __ENV.DURATION (e.g. 5m, 15m, 30m, 1h, 6h, 24h).
 * Tracks response-time drift, database connection stability, and error accumulation.
 */

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8010";
const VUS = parseInt(__ENV.TARGET_VUS || "25", 10);
const DURATION = __ENV.DURATION || "5m";
const CANTEEN_ID = __ENV.CANTEEN_ID || "";

export const options = {
  vus: VUS,
  duration: DURATION,
  thresholds: {
    http_req_failed: ["rate<0.01"],
    http_req_duration: ["p(95)<1000"],
  },
};

export default function () {
  const endpoints = [
    "/health",
    "/api/v1/canteens/college",
    "/api/v1/canteens",
    "/api/v1/pickup/board",
    "/api/v1/meal-plans",
    "/api/v1/events",
  ];
  if (CANTEEN_ID) {
    endpoints.push(`/api/v1/menus/canteens/${CANTEEN_ID}/items`);
    endpoints.push(`/api/v1/queue/canteens/${CANTEEN_ID}`);
  }
  const ep = endpoints[Math.floor(Math.random() * endpoints.length)];
  const res = http.get(`${BASE_URL}${ep}`, { timeout: "10s" });
  check(res, { "endurance status 200": (r) => r.status === 200 });
  sleep(0.2);
}
