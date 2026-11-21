import { chromium } from "playwright";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const FRONTEND_URL = process.env.E2E_FRONTEND_URL || "http://127.0.0.1:5173";

function findBrowserExecutable() {
  const candidates = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  ];
  const localApp = process.env.LOCALAPPDATA;
  if (localApp) {
    const pwDir = path.join(localApp, "ms-playwright");
    if (fs.existsSync(pwDir)) {
      for (const entry of fs.readdirSync(pwDir)) {
        if (entry.startsWith("chromium-")) {
          const exe = path.join(pwDir, entry, "chrome-win64", "chrome.exe");
          if (fs.existsSync(exe)) candidates.unshift(exe);
          const exe32 = path.join(pwDir, entry, "chrome-win", "chrome.exe");
          if (fs.existsSync(exe32)) candidates.unshift(exe32);
        }
      }
    }
  }
  return candidates.find((p) => fs.existsSync(p));
}

async function main() {
  const executablePath = findBrowserExecutable();
  const browser = await chromium.launch({
    headless: true,
    ...(executablePath ? { executablePath } : {}),
  });

  const errors = [];
  const attachErrorListeners = (page) => {
    page.on("pageerror", (e) => errors.push(`PageError: ${e.message}`));
    page.on("dialog", async (d) => {
      errors.push(`UnexpectedNativeDialog (${d.type()}): ${d.message()}`);
      await d.dismiss().catch(() => {});
    });
    page.on("response", (res) => {
      if (res.status() >= 500) {
        errors.push(`HTTP ${res.status()} on ${res.url()}`);
      }
    });
    page.on("console", (m) => {
      const locUrl = m.location()?.url || "";
      if (m.type() === "error" && !m.text().includes("favicon") && !locUrl.includes("favicon")) {
        errors.push(`ConsoleError (${locUrl}): ${m.text()}`);
      }
    });
  };

  try {
    // 0. Mobile App (PWA) Viewport, Manifest, Service Worker & /scan QR Scanner Check
    const pwaCtx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const pwaPage = await pwaCtx.newPage();
    attachErrorListeners(pwaPage);
    await pwaPage.goto(FRONTEND_URL, { waitUntil: "networkidle" });

    const manifestRes = await pwaCtx.request.get(`${FRONTEND_URL}/manifest.webmanifest`);
    assert.equal(manifestRes.status(), 200, "manifest.webmanifest should return 200");
    const manifestJson = await manifestRes.json();
    assert.equal(manifestJson.display, "standalone");
    assert.ok(Array.isArray(manifestJson.icons) && manifestJson.icons.length >= 2);

    const swRes = await pwaCtx.request.get(`${FRONTEND_URL}/sw.js`);
    assert.equal(swRes.status(), 200, "sw.js should return 200");

    const mobileNav = pwaPage.locator('nav[aria-label="Mobile Customer Navigation"]');
    await mobileNav.waitFor({ state: "visible", timeout: 10000 });
    await pwaPage.getByTitle("Install CollegeBites Mobile App").click();
    await pwaPage.getByText("Install CollegeBites Mobile App").waitFor({ timeout: 5000 });
    await pwaPage.keyboard.press("Escape").catch(() => {});
    await pwaPage.locator("button").filter({ has: pwaPage.locator("svg") }).first().click().catch(() => {});

    await pwaPage.goto(`${FRONTEND_URL}/scan`, { waitUntil: "networkidle" });
    await pwaPage.getByPlaceholder("e.g. CB-MAIN-T01").fill("CB-MAIN-T01");
    await pwaPage.getByRole("button", { name: "Open", exact: true }).click();
    await pwaPage.getByRole("heading", { name: "Main Canteen" }).waitFor({ timeout: 10000 });
    await pwaPage.getByRole("button", { name: /Open Menu & Order Now/i }).click();
    await pwaCtx.close();

    // 1. Customer / Guest QR Ordering Flow (Razorpay)
    const custCtx = await browser.newContext();
    const page = await custCtx.newPage();
    attachErrorListeners(page);

    await page.goto(`${FRONTEND_URL}/scan/CB-MAIN-T01`, { waitUntil: "networkidle" });
    await page.getByRole("heading", { name: "Main Canteen" }).waitFor({ timeout: 10000 });
    await page.getByRole("button", { name: /Open Menu & Order Now/i }).click();

    await page.getByPlaceholder("Search dishes, ingredients...").fill("Biryani");
    await page.waitForTimeout(500);
    await page.getByRole("button", { name: /Customize & Add/i }).first().click();
    await page.getByRole("button", { name: /Jumbo Pack/i }).click();
    await page.getByRole("button", { name: /Extra Spicy/i }).click();
    await page.getByRole("button", { name: /Add to Cart/i }).click();

    await page.getByRole("button", { name: /Proceed to Checkout/i }).click();
    await page.getByText("Guest Ordering Details").waitFor();

    await page.getByPlaceholder("Visitor / Student Name").fill("Browser E2E Guest");
    await page.getByPlaceholder("+919876543210").fill("+919800001122");
    await page.getByRole("button", { name: "Send OTP" }).click();

    const otpHint = await page.getByText(/Dev OTP:/).textContent({ timeout: 10000 });
    const otpCode = otpHint.match(/(\d{6})/)[1];
    await page.getByPlaceholder("123456").fill(otpCode);
    await page.getByRole("button", { name: "Verify" }).click();
    await page.getByText("Mobile verified for guest checkout").waitFor();

    await page.getByText("Stripe Checkout").waitFor();
    await page.getByText("Razorpay Online").waitFor();
    await page.locator('input[type="checkbox"]').check();
    await page.getByRole("button", { name: /Pay ₹/i }).click();
    await page.getByRole("button", { name: /Complete & Verify Payment/i }).click();

    await page.waitForURL(/\/orders\/CB-/, { timeout: 15000 });
    await page.getByText("Official Digital Token Slip & Payment Receipt").waitFor({ timeout: 10000 });
    await page.getByText("ACE ENGINEERING COLLEGE").first().waitFor();
    await page.getByText("Jumbo Pack").first().waitFor();

    const tokenText = await page.locator(".text-4xl.font-black").first().textContent();
    const pickupToken = tokenText.trim();
    assert.ok(pickupToken.startsWith("A"), `Expected pickup token starting with A, got: ${pickupToken}`);
    console.log("E2E_GUEST_TOKEN:", pickupToken);

    // 1b. Signed-in Student Stripe Checkout Flow
    const stripeCtx = await browser.newContext();
    const stripePage = await stripeCtx.newPage();
    attachErrorListeners(stripePage);
    await stripePage.goto(`${FRONTEND_URL}/login`, { waitUntil: "networkidle" });
    await stripePage.getByRole("button", { name: /Student \(Customer\)/i }).click();
    await stripePage.waitForURL(`${FRONTEND_URL}/`, { timeout: 10000 }).catch(() => {});
    await stripePage.getByPlaceholder("Search dishes, ingredients...").fill("Cold Coffee");
    await stripePage.waitForTimeout(500);
    await stripePage.getByRole("button", { name: /Customize & Add/i }).first().click();
    await stripePage.getByRole("button", { name: /Add to Cart/i }).click();
    await stripePage.getByRole("button", { name: /Proceed to Checkout/i }).click();
    await stripePage.getByRole("button", { name: /Stripe Checkout/i }).click();
    await stripePage.locator('input[type="checkbox"]').check();
    await stripePage.getByRole("button", { name: /Pay ₹/i }).click();
    await stripePage.getByText(/Stripe: cs_test_/).waitFor({ timeout: 10000 });
    await stripePage.getByRole("button", { name: /Complete & Verify Payment/i }).click();
    await stripePage.waitForURL(/\/orders\/CB-/, { timeout: 15000 });
    await stripePage.getByText("Official Digital Token Slip & Payment Receipt").waitFor({ timeout: 10000 });
    console.log("E2E_STRIPE_ORDER_URL:", stripePage.url());

    // 2. Digital Token Board check
    const boardPage = await custCtx.newPage();
    attachErrorListeners(boardPage);
    await boardPage.goto(`${FRONTEND_URL}/board`, { waitUntil: "networkidle" });
    await boardPage.getByText(pickupToken).first().waitFor({ timeout: 10000 });

    // 3. Kitchen Display Flow
    const kitCtx = await browser.newContext();
    const kitPage = await kitCtx.newPage();
    attachErrorListeners(kitPage);
    await kitPage.goto(`${FRONTEND_URL}/login`, { waitUntil: "networkidle" });
    await kitPage.getByRole("button", { name: /Kitchen Staff/i }).click();
    await kitPage.waitForURL(/\/kitchen/);
    await kitPage.getByText(pickupToken).first().waitFor({ timeout: 10000 });
    const cardWithBtn = (btnName) =>
      kitPage
        .locator("div")
        .filter({ hasText: pickupToken })
        .filter({ has: kitPage.getByRole("button", { name: btnName }) })
        .last();
    await cardWithBtn("Accept").getByRole("button", { name: "Accept" }).click();
    await cardWithBtn("Start Prep").getByRole("button", { name: "Start Prep" }).click();
    await cardWithBtn("Mark Ready").getByRole("button", { name: "Mark Ready" }).click();
    await kitPage.waitForTimeout(500);

    // Board updates to READY FOR PICKUP
    await boardPage.reload({ waitUntil: "networkidle" });
    await boardPage.getByText("READY FOR PICKUP").waitFor();
    await boardPage.locator("div").filter({ hasText: "READY FOR PICKUP" }).filter({ hasText: pickupToken }).last().waitFor({ timeout: 10000 });

    // 4. Pickup Scanner & Separate Atomic Handover
    const pickCtx = await browser.newContext();
    const pickPage = await pickCtx.newPage();
    attachErrorListeners(pickPage);
    await pickPage.goto(`${FRONTEND_URL}/login`, { waitUntil: "networkidle" });
    await pickPage.getByRole("button", { name: /Pickup Scanner/i }).click();
    await pickPage.waitForURL(/\/pickup/);
    await pickPage.getByPlaceholder("e.g. A001").fill(pickupToken);
    await pickPage.getByRole("button", { name: "Verify Order" }).click();
    await pickPage.getByText("VALID_ORDER").first().waitFor({ timeout: 10000 });
    await pickPage.getByRole("button", { name: /Confirm Food Handover/i }).click();
    await pickPage.getByText("COMPLETED").first().waitFor({ timeout: 10000 });

    // Second verify shows ALREADY_COLLECTED
    await pickPage.getByRole("button", { name: "Verify Order" }).click();
    await pickPage.getByText("ALREADY_COLLECTED").first().waitFor({ timeout: 10000 });

    // 4b. Cashier POS Walk-in & Receipt Slip Check
    const posCtx = await browser.newContext();
    const posPage = await posCtx.newPage();
    attachErrorListeners(posPage);
    await posPage.goto(`${FRONTEND_URL}/login`, { waitUntil: "networkidle" });
    await posPage.getByRole("button", { name: /Cashier POS/i }).click();
    await posPage.waitForURL(/\/cashier/);
    await posPage.getByPlaceholder("Quick search dishes...").waitFor({ timeout: 10000 });
    await posPage.locator("button").filter({ hasText: "₹" }).first().click();
    await posPage.getByRole("button", { name: /Accept Payment & Print Token/i }).click();
    await posPage.getByText("Official Digital Token Slip & Payment Receipt").waitFor({ timeout: 10000 });

    // 5. Admin Console All Tabs + Breakdowns Smoke Check
    const adminCtx = await browser.newContext();
    const adminPage = await adminCtx.newPage();
    attachErrorListeners(adminPage);
    await adminPage.goto(`${FRONTEND_URL}/login`, { waitUntil: "networkidle" });
    await adminPage.getByRole("button", { name: /College Admin/i }).click();
    await adminPage.waitForURL(/\/admin/);
    await adminPage.getByText("Category-wise Sales").waitFor({ timeout: 10000 });
    await adminPage.getByText("Counter-wise Sales").waitFor({ timeout: 10000 });
    await adminPage.getByText("Payment Breakdown").waitFor({ timeout: 10000 });
    await adminPage.getByText("Peak Hours").waitFor({ timeout: 10000 });

    for (const tabName of [
      "Orders & Users",
      "Locations, Counters & Hours",
      "Menus & CSV",
      "Location QR Codes",
      "Queue, Crowd & Slots",
      "Staff, Attendance & Tasks",
      "Announcements & Banners",
      "Support Tickets",
      "Settings, Reconcile & Audits",
    ]) {
      await adminPage.getByRole("button", { name: tabName }).click();
      if (tabName === "Orders & Users") {
        await adminPage.getByText(pickupToken).first().waitFor({ timeout: 10000 });
      }
      await adminPage.waitForTimeout(250);
    }

    // 6. KDS Ingredients Modal & Inventory Recipe Page Smoke Check
    await kitPage.getByRole("button", { name: /Ingredient \/ Item Availability/i }).click();
    await kitPage.getByRole("button", { name: /^Ingredients \(/i }).click();
    await kitPage.waitForTimeout(300);

    await adminPage.goto(`${FRONTEND_URL}/inventory`, { waitUntil: "networkidle" });
    await adminPage.getByText("Inventory Manager Portal").waitFor({ timeout: 10000 });
    await adminPage.getByText("All Inventory Items").first().waitFor({ timeout: 10000 });
    await adminPage.getByText("Price Management & Selling Price Approvals").waitFor({ timeout: 10000 });
    await adminPage.getByText("Link Dish Recipe (Auto Stock Deduction)").waitFor({ timeout: 10000 });
    await adminPage.getByText("Manual Stock Adjustment").waitFor({ timeout: 10000 });

    assert.equal(errors.length, 0, `Browser errors occurred:\n${errors.join("\n")}`);
    console.log("PLAYWRIGHT_E2E_SUCCESS");
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
