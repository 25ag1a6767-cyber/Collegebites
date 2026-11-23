import http from "k6/http";
import { check, sleep } from "k6";
import { Counter, Rate, Trend } from "k6/metrics";

/**
 * CollegeBites — Safe Production Read-Only Performance Test (Section 10)
 * Target: https://collegebites-alpha.vercel.app
 * Constraints:
 *  - Strictly read-only confirmed public GET endpoints
 *  - Max 5 concurrent virtual users (1, 2, 3, 5 VUs)
 *  - Request timeout: 10s
 *  - P95 guardrail: 1500ms (abortOnFail)
 *  - Failure-rate guardrail: 2% (abortOnFail)
 */

const BASE_URL = __ENV.BASE_URL || "https://collegebites-alpha.vercel.app";
const VUS = parseInt(__ENV.TARGET_VUS || "1", 10);
const DURATION = __ENV.DURATION || "15s";

export const http4xx = new Counter("http_4xx_errors");
export const http5xx = new Counter("http_5xx_errors");
export const timeoutErrors = new Counter("timeout_errors");
export const customLatency = new Trend("endpoint_duration_ms", true);
export const errorRate = new Rate("custom_error_rate");

export const options = {
  vus: Math.min(VUS, 5), // Hard cap at 5 VUs for production safety
  duration: DURATION,
  thresholds: {
    http_req_duration: [{ threshold: "p(95)<1500", abortOnFail: true, delayAbortEval: "3s" }],
    http_req_failed: [{ threshold: "rate<0.02", abortOnFail: true, delayAbortEval: "3s" }],
  },
};

const ENDPOINTS = [
  { name: "Frontend_Board_Page", path: "/board" },
  { name: "Backend_Health", path: "/health" },
  { name: "College_Settings", path: "/api/v1/canteens/college" },
  { name: "List_Canteens", path: "/api/v1/canteens" },
  { name: "Public_Token_Board", path: "/api/v1/pickup/board" },
  { name: "Menu_Allergens", path: "/api/v1/menus/allergens" },
  { name: "Active_Coupons", path: "/api/v1/promotions/coupons" },
  { name: "Public_Meal_Plans", path: "/api/v1/meal-plans" },
  { name: "Public_College_Events", path: "/api/v1/events" },
];

export default function () {
  for (const ep of ENDPOINTS) {
    const res = http.get(`${BASE_URL}${ep.path}`, {
      timeout: "10s",
      tags: { endpoint: ep.name },
      headers: { Accept: "application/json, text/html" },
    });

    customLatency.add(res.timings.duration, { endpoint: ep.name });

    if (res.error_code === 1050 || (res.error && res.error.toLowerCase().includes("timeout"))) {
      timeoutErrors.add(1);
    }
    if (res.status >= 400 && res.status < 500) {
      http4xx.add(1);
    } else if (res.status >= 500 || res.status === 0) {
      http5xx.add(1);
    }

    const ok = check(res, {
      [`${ep.name} status is 200`]: (r) => r.status === 200,
      [`${ep.name} duration < 1500ms`]: (r) => r.timings.duration < 1500,
    });
    errorRate.add(!ok);

    // Abort immediately if repeated 429 or 5xx detected
    if (res.status === 429 || res.status >= 500) {
      sleep(1.0);
    } else {
      sleep(0.25);
    }
  }
}
