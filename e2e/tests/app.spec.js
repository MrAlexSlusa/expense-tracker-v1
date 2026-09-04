const { test, expect } = require("@playwright/test");
const { signUp } = require("./helpers");

/** Sets the currency and adds one expense straight through the API, then reloads. */
async function seed(page, { currency, amount }) {
  await page.evaluate(async ([cur, amt]) => {
    const h = { "Content-Type": "application/json",
                Authorization: "Bearer " + localStorage.getItem("expense_tracker_token") };
    await fetch(window.API_BASE_URL + "/api/me/currency", {
      method: "PUT", headers: h, body: JSON.stringify({ currency: cur }) });
    const cats = await (await fetch(window.API_BASE_URL + "/api/budget", { headers: h })).json();
    await fetch(window.API_BASE_URL + "/api/expenses", {
      method: "POST", headers: h,
      body: JSON.stringify({ amount: amt, category_id: cats[0].id, note: "e2e" }) });
  }, [currency, amount]);
  await page.reload();
  await expect(page.locator("#app-screen")).toBeVisible();
}

test("RON amounts render with lei after the number", async ({ page }) => {
  await signUp(page);
  await seed(page, { currency: "RON", amount: 9 });

  await expect(page.locator(".tx-amount").first()).toHaveText("9 lei");
  // The hero total must agree - formatting them differently is the real risk.
  await expect(page.locator(".hero-amount, .hero-amount-sm").first()).toContainText("lei");
});

test("USD keeps the symbol in front", async ({ page }) => {
  await signUp(page);
  await seed(page, { currency: "USD", amount: 9 });
  await expect(page.locator(".tx-amount").first()).toHaveText("$9");
});

test("Analytics opens on All time, not a preselected twelve months", async ({ page }) => {
  await signUp(page);
  await seed(page, { currency: "USD", amount: 25 });

  await page.locator('[data-action="set-view"][data-value="analytics"]').click();
  await expect(page.locator(".chart-bar").first()).toBeVisible();

  await expect(page.locator(".hero div").first()).toHaveText("All time");
  await expect(page.locator('.pill[data-action="open-period"]')).toHaveText("All time");
  // No clear-affordance, because there is no filter applied to clear.
  await expect(page.locator(".pill-outline-x")).toHaveCount(0);
});

test("picking a period on Analytics leaves the other tabs alone", async ({ page }) => {
  await signUp(page);
  await seed(page, { currency: "USD", amount: 25 });

  await page.locator('[data-action="set-view"][data-value="analytics"]').click();
  // Scoped to the pill: the hero also carries an open-period button.
  await page.locator('.pill[data-action="open-period"]').click();
  await page.locator('[data-action="set-period"][data-value="Yearly"]').click();
  await page.locator('[data-action="close-sheet"]').last().click();
  await expect(page.locator('.pill[data-action="open-period"]')).toContainText("Yearly");

  // Activity still shows its own, separate default.
  await page.locator('[data-action="set-view"][data-value="activity"]').click();
  await expect(page.locator('.pill[data-action="open-period"]')).toHaveText("Monthly");
});

test("the privacy policy and terms are reachable from the login screen", async ({ page }) => {
  await page.goto("./");
  await page.locator(".auth-legal a", { hasText: "Privacy Policy" }).click();
  await expect(page).toHaveURL(/privacy\.html$/);
  await expect(page.locator("h1")).toHaveText("Privacy Policy");

  await page.locator("a", { hasText: "Terms of Service" }).first().click();
  await expect(page).toHaveURL(/terms\.html$/);
  await expect(page.locator("h1")).toHaveText("Terms of Service");

  // The back link returns to the app rather than dead-ending.
  await page.locator(".legal-back").click();
  await expect(page.locator("#auth-screen")).toBeVisible();
});
