import http from "k6/http";
import { check, group, sleep } from "k6";
import { Trend } from "k6/metrics";

/**
 * CollegeBites — Module-by-Module API Benchmark (Section 5)
 * Covers Health, Auth, Menu, Inventory, Orders/Carts, Payments, QR/Tokens,
 * Pickup Verification, and Admin/Operations Control Center endpoints.
 */

const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8010";
const ADMIN_TOKEN = __ENV.ADMIN_TOKEN || "";
const STUDENT_TOKEN = __ENV.STUDENT_TOKEN || "";
const CANTEEN_ID = __ENV.CANTEEN_ID || "";

export const moduleDuration = new Trend("module_duration_ms", true);

export const options = {
  vus: parseInt(__ENV.TARGET_VUS || "10", 10),
  duration: __ENV.DURATION || "15s",
};

export default function () {
  const adminHeaders = ADMIN_TOKEN ? { Authorization: `Bearer ${ADMIN_TOKEN}`, "Content-Type": "application/json" } : {};
  const studentHeaders = STUDENT_TOKEN ? { Authorization: `Bearer ${STUDENT_TOKEN}`, "Content-Type": "application/json" } : {};

  group("B1_Health", () => {
    const r = http.get(`${BASE_URL}/health`, { tags: { module: "health" } });
    moduleDuration.add(r.timings.duration, { module: "health" });
    check(r, { "health 200": (res) => res.status === 200 });
  });

  group("B2_Menu_APIs", () => {
    const r1 = http.get(`${BASE_URL}/api/v1/canteens`, { tags: { module: "menu" } });
    moduleDuration.add(r1.timings.duration, { module: "menu" });
    if (CANTEEN_ID) {
      const r2 = http.get(`${BASE_URL}/api/v1/menus/canteens/${CANTEEN_ID}/items`, { tags: { module: "menu" } });
      moduleDuration.add(r2.timings.duration, { module: "menu" });
      check(r2, { "menu items 200": (res) => res.status === 200 });
    }
  });

  group("B3_Pickup_And_Token_Board", () => {
    const r = http.get(`${BASE_URL}/api/v1/pickup/board`, { tags: { module: "pickup_board" } });
    moduleDuration.add(r.timings.duration, { module: "pickup_board" });
    check(r, { "pickup board 200": (res) => res.status === 200 });
  });

  if (STUDENT_TOKEN && CANTEEN_ID) {
    group("B4_Customer_Order_And_Cart", () => {
      const r1 = http.get(`${BASE_URL}/api/v1/carts?canteen_id=${CANTEEN_ID}`, { headers: studentHeaders, tags: { module: "cart" } });
      const r2 = http.get(`${BASE_URL}/api/v1/orders/my`, { headers: studentHeaders, tags: { module: "orders" } });
      moduleDuration.add(r1.timings.duration, { module: "cart" });
      moduleDuration.add(r2.timings.duration, { module: "orders" });
      check(r2, { "my orders 200": (res) => res.status === 200 });
    });
  }

  if (ADMIN_TOKEN && CANTEEN_ID) {
    group("B5_Inventory_And_Admin", () => {
      const r1 = http.get(`${BASE_URL}/api/v1/inventory/items?canteen_id=${CANTEEN_ID}`, { headers: adminHeaders, tags: { module: "inventory" } });
      const r2 = http.get(`${BASE_URL}/api/v1/admin/orders?limit=50`, { headers: adminHeaders, tags: { module: "admin_orders" } });
      const r3 = http.get(`${BASE_URL}/api/v1/reports/operations-control-center`, { headers: adminHeaders, tags: { module: "control_center" } });
      const r4 = http.get(`${BASE_URL}/api/v1/reports/dashboard?preset=last_30_days`, { headers: adminHeaders, tags: { module: "analytics_report" } });
      moduleDuration.add(r1.timings.duration, { module: "inventory" });
      moduleDuration.add(r2.timings.duration, { module: "admin_orders" });
      moduleDuration.add(r3.timings.duration, { module: "control_center" });
      moduleDuration.add(r4.timings.duration, { module: "analytics_report" });
      check(r3, { "control center 200": (res) => res.status === 200 });
    });
  }

  sleep(0.1);
}
