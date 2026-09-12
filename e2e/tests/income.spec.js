const { test, expect } = require("@playwright/test");
const { signUp } = require("./helpers");

/*
 * Logging income from the + keypad - the half of the sheet that adds to the
 * month instead of subtracting from it.
 *
 * The amounts themselves are backend-tested; what only a browser can prove is
 * that the toggle reaches the income shape at all, that the name survives the
 * keypad taps that rebuild the sheet around it, and that a line written to a
 * month other than the one on screen is still shown after saving.
 */

async function typeAmount(page, digits) {
  for (const key of String(digits).split("")) {
    await page.locator(`.key[data-value="${key}"]`).click();
  }
}

async function openIncomeKeypad(page) {
  await page.locator('[data-action="open-add"]').click();
  await page.locator('[data-action="set-add-kind"][data-value="Income"]').click();
}

test("the income mode swaps categories for a name and a month", async ({ page }) => {
  await signUp(page);
  await openIncomeKeypad(page);

  // Income is a named line on a month, not a categorised transaction: the
  // category pills and the currency chips have no meaning here.
  await expect(page.locator(".cat-pill")).toHaveCount(0);
  await expect(page.locator(".cur-chip")).toHaveCount(0);
  await expect(page.locator("#income-keypad-name")).toBeVisible();

  // The month opens on the one being viewed, which on a fresh account is this one.
  const thisMonth = new Date().toISOString().slice(0, 7);
  await expect(page.locator("#income-keypad-period")).toHaveValue(thisMonth);

  // The amount reads as an addition, so the sign is never in doubt.
  await typeAmount(page, "1200");
  await expect(page.locator(".keypad-amount")).toContainText("+");
});

test("an income line survives the keypad and lands on the income list", async ({ page }) => {
  await signUp(page);
  await openIncomeKeypad(page);

  // Typed before the digits on purpose: every key press rebuilds the sheet, so
  // this is the assertion that the name isn't rebuilt away.
  await page.locator("#income-keypad-name").fill("Salary");
  await typeAmount(page, "3000");
  await expect(page.locator("#income-keypad-name")).toHaveValue("Salary");

  await page.locator('[data-action="save-add"]').click();
  await expect(page.locator(".sheet")).toHaveCount(0);

  // Saving lands on the Income list rather than leaving the row out of sight.
  await expect(page.locator('.pill[data-action="toggle-kind"]')).toHaveText("Income");
  const row = page.locator(".tx-row").first();
  await expect(row).toContainText("Salary");
  await expect(row).toContainText("3,000");
});

test("an income line can be logged against an earlier month", async ({ page }) => {
  await signUp(page);
  await openIncomeKeypad(page);

  const now = new Date();
  const previous = new Date(now.getFullYear(), now.getMonth() - 1, 1);
  const period = `${previous.getFullYear()}-${String(previous.getMonth() + 1).padStart(2, "0")}`;

  await page.locator("#income-keypad-name").fill("Last month");
  await page.locator("#income-keypad-period").fill(period);
  await typeAmount(page, "500");
  await page.locator('[data-action="save-add"]').click();
  await expect(page.locator(".sheet")).toHaveCount(0);

  // Activity follows the line to the month it was written to - otherwise the
  // save would look like it did nothing at all.
  await expect(page.locator(".tx-row").first()).toContainText("Last month");
});
