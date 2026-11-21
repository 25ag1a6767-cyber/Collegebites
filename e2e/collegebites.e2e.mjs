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
    page.on("console", (m) => {
      const locUrl = m.location()?.url || "";
      if (m.type() === "error" && !m.text().includes("favicon") && !locUrl.includes("favicon")) {
        errors.push(`ConsoleError (${locUrl}): ${m.text()}`);
      }
    });
  };

  try {
    // 1. Customer / Guest QR Ordering Flow
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

    // 5. Admin Console All Tabs Smoke Check
    const adminCtx = await browser.newContext();
    const adminPage = await adminCtx.newPage();
    attachErrorListeners(adminPage);
    await adminPage.goto(`${FRONTEND_URL}/login`, { waitUntil: "networkidle" });
    await adminPage.getByRole("button", { name: /College Admin/i }).click();
    await adminPage.waitForURL(/\/admin/);
    for (const tabName of [
      "Orders & Users",
      "Locations, Counters & Hours",
      "Menus & CSV",
      "Location QR Codes",
      "Queue, Crowd & Slots",
      "Staff, Attendance & Tasks",
      "Coupons & Announcements",
      "Support Tickets",
      "Settings, Reconcile & Audits",
    ]) {
      await adminPage.getByRole("button", { name: tabName }).click();
      if (tabName === "Orders & Users") {
        await adminPage.getByText(pickupToken).first().waitFor({ timeout: 10000 });
      }
      await adminPage.waitForTimeout(250);
    }

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
