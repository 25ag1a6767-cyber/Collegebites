import http from "k6/http";
import { check, sleep } from "k6";

/**
 * CollegeBites — Stress & Spike Test Suite (Sections 6 & 7)
 * Modes (via __ENV.MODE):
 *  - "stress": progressive ramp 10 -> 50 -> 100 -> 250 -> 500 -> 1000 -> cooldown 10
 *  - "spike_5_50": 5 VUs -> instant spike to 50 VUs -> recovery to 5 VUs
 *  - "spike_10_100": 10 VUs -> instant spike to 100 VUs -> recovery to 10 VUs
 *  - "spike_25_250": 25 VUs -> instant spike to 250 VUs -> recovery to 25 VUs
 */

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8010";
const MODE = __ENV.MODE || "spike_10_100";
const CANTEEN_ID = __ENV.CANTEEN_ID || "";

const STAGES_MAP = {
  stress: [
    { duration: "10s", target: 25 },
    { duration: "10s", target: 100 },
    { duration: "10s", target: 250 },
    { duration: "10s", target: 500 },
    { duration: "10s", target: 1000 },
    { duration: "10s", target: 10 },
  ],
  spike_5_50: [
    { duration: "5s", target: 5 },
    { duration: "2s", target: 50 },
    { duration: "10s", target: 50 },
    { duration: "3s", target: 5 },
    { duration: "5s", target: 5 },
  ],
  spike_10_100: [
    { duration: "5s", target: 10 },
    { duration: "2s", target: 100 },
    { duration: "10s", target: 100 },
    { duration: "3s", target: 10 },
    { duration: "5s", target: 10 },
  ],
  spike_25_250: [
    { duration: "5s", target: 25 },
    { duration: "2s", target: 250 },
    { duration: "10s", target: 250 },
    { duration: "3s", target: 25 },
    { duration: "5s", target: 25 },
  ],
};

export const options = {
  stages: STAGES_MAP[MODE] || STAGES_MAP.spike_10_100,
};

export default function () {
  const endpoints = [
    "/health",
    "/api/v1/canteens",
    "/api/v1/pickup/board",
    "/api/v1/promotions/coupons",
    "/api/v1/meal-plans",
  ];
  if (CANTEEN_ID) {
    endpoints.push(`/api/v1/menus/canteens/${CANTEEN_ID}/items`);
  }
  const ep = endpoints[Math.floor(Math.random() * endpoints.length)];
  const res = http.get(`${BASE_URL}${ep}`, { timeout: "10s" });
  check(res, { "status is 200": (r) => r.status === 200 });
  sleep(0.05);
}
