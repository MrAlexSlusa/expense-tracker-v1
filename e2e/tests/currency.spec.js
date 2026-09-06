const { test, expect } = require("@playwright/test");
const { signUp } = require("./helpers");

/*
 * Logging an expense in a currency that isn't the account's, and the page that
 * shows where the rates come from.
 *
 * The conversion arithmetic is covered by the backend tests; this covers the
 * parts only a browser can prove - that the currency is reachable from the
 * keypad, that the preview and the saved row agree, and that the total on
 * screen counts the converted amount rather than the typed one.
 *
 * Rates come from whatever the scheduled automation last left in cursuri_bnr/,
 * so nothing here asserts a specific rate: it asserts the relationships, which
 * hold whatever this week's number happens to be.
 */

const RON_ACCOUNT = "RON";

async function setCurrency(page, code) {
  await page.locator('[data-action="go-accounts"]').first().click();
  await page.locator('[data-action="open-currency"]').click();
  await page.locator(`[data-action="set-currency"][data-value="${code}"]`).click();
  await expect(page.locator(".sheet")).toHaveCount(0);
  // The picker lives on Accounts; go back to the list the expense will land in.
  await page.locator('[data-action="set-view"][data-value="activity"]').click();
}

async function typeAmount(page, digits) {
  for (const key of String(digits).split("")) {
    await page.locator(`.key[data-value="${key}"]`).click();
  }
}

test("the keypad offers the account's currency plus the ones BNR quotes", async ({ page }) => {
  await signUp(page);
  await setCurrency(page, RON_ACCOUNT);

  await page.locator('[data-action="open-add"]').click();
  const chips = page.locator(".cur-chip");
  await expect(chips).toHaveText([RON_ACCOUNT, "EUR", "USD", "GBP"]);

  // The account's own currency leads and starts selected - that is the state
  // in which nothing is converted at all.
  await expect(chips.first()).toHaveClass(/is-selected/);
});

test("picking a currency previews the converted amount before saving", async ({ page }) => {
  await signUp(page);
  await setCurrency(page, RON_ACCOUNT);

  await page.locator('[data-action="open-add"]').click();
  await typeAmount(page, "100");
  // In the account's own currency there is nothing to preview.
  await expect(page.locator(".keypad-converted")).toHaveCount(0);

  await page.locator('.cur-chip[data-value="EUR"]').click();
  await expect(page.locator(".keypad-amount")).toHaveText("€100");

  const preview = page.locator(".keypad-converted");
  await expect(preview).toBeVisible();
  // 100 euro is worth several hundred lei at any rate this app will ever see.
  await expect(preview).toContainText("lei");
  const previewed = Number((await preview.innerText()).replace(/[^\d.]/g, ""));
  expect(previewed).toBeGreaterThan(100);
});

test("a euro expense is stored in lei and counted in the month's total", async ({ page }) => {
  await signUp(page);
  await setCurrency(page, RON_ACCOUNT);

  await page.locator('[data-action="open-add"]').click();
  await typeAmount(page, "100");
  await page.locator('.cur-chip[data-value="EUR"]').click();

  const previewed = Number((await page.locator(".keypad-converted").innerText()).replace(/[^\d.]/g, ""));
  await page.locator('[data-action="save-expense"]').click();
  await expect(page.locator(".sheet")).toHaveCount(0);

  // The row keeps both numbers: lei in the column that adds up, euro underneath.
  const row = page.locator(".tx-row").first();
  await expect(row).toContainText("lei");
  await expect(row.locator(".tx-sub")).toContainText("€100");

  // What was previewed is what was saved - a preview that disagreed with the
  // stored amount would be worse than no preview at all.
  const saved = Number((await row.locator(".tx-amount").innerText()).replace(/[^\d.]/g, ""));
  expect(Math.abs(saved - previewed)).toBeLessThan(0.02);

  // And the total counts the lei, not the 100 that was typed.
  const total = Number((await page.locator(".hero-amount, .hero-amount-sm").first().innerText()).replace(/[^\d.]/g, ""));
  expect(Math.abs(total - saved)).toBeLessThan(0.02);
});

test("the transaction sheet explains the conversion it made", async ({ page }) => {
  await signUp(page);
  await setCurrency(page, RON_ACCOUNT);

  await page.locator('[data-action="open-add"]').click();
  await typeAmount(page, "50");
  await page.locator('.cur-chip[data-value="USD"]').click();
  await page.locator('[data-action="save-expense"]').click();

  await page.locator(".tx-row").first().click();
  const sheet = page.locator(".sheet");
  await expect(sheet).toContainText("Amount paid");
  await expect(sheet).toContainText("$50");
  // The rate is shown to four decimals, because two would round it into
  // something that no longer explains the amount beside it.
  await expect(sheet).toContainText(/1 USD = [\d,]+\.\d{4} lei/);
});

test("the rates page lists all five currencies and names each source", async ({ page }) => {
  await signUp(page);
  await page.locator('[data-action="go-accounts"]').first().click();
  await page.locator('[data-action="open-rates"]').click();

  const rows = page.locator(".rate-row");
  await expect(rows).toHaveCount(5);
  await expect(rows.nth(0)).toContainText("EUR");
  await expect(rows.nth(3)).toContainText("BTC");

  // BNR publishes no crypto rate, and the page has to say so rather than
  // letting the central bank appear to price bitcoin.
  await expect(rows.nth(0)).toContainText("National Bank of Romania");
  await expect(rows.nth(3)).not.toContainText("National Bank of Romania");
  await expect(page.locator(".rates-note")).toContainText("does not publish crypto rates");
});

test("the converter on the rates page follows what you type", async ({ page }) => {
  await signUp(page);
  await page.locator('[data-action="go-accounts"]').first().click();
  await page.locator('[data-action="open-rates"]').click();

  await page.locator("#conv-amount").fill("250");
  const result = page.locator(".conv-result");
  await expect(result).toContainText("lei");
  const inLei = Number((await result.innerText()).replace(/[^\d.]/g, ""));
  expect(inLei).toBeGreaterThan(250); // 250 euro is worth more than 250 lei

  // Changing the target re-renders the page; the amount has to survive it,
  // or every switch would mean retyping.
  await page.locator("#conv-to").selectOption("USD");
  await expect(page.locator("#conv-amount")).toHaveValue("250");
  await expect(result).toContainText("$");
});
