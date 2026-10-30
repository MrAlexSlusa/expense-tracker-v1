const { expect } = require("@playwright/test");

let counter = 0;

/**
 * A unique address per call, so tests never collide on the unique email column.
 * example.com, not example.test: Pydantic's EmailStr rejects the reserved
 * special-use TLDs (.test, .invalid, .localhost) with a 422.
 */
function freshEmail() {
  counter += 1;
  return `e2e-${Date.now()}-${counter}@example.com`;
}

const PASSWORD = "e2e-password-2026";

/** Signs up, landing straight on the app screen. */
async function signUp(page, email = freshEmail()) {
  await page.goto("./");
  await expect(page.locator("#auth-screen")).toBeVisible();

  await page.locator("#switch-link").click();
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#auth-submit").click();

  // Nothing stands between signing up and the app: the account is created
  // with a starter set of categories already in place.
  await expect(page.locator("#app-screen")).toBeVisible();
  return { email, password: PASSWORD };
}

/** Reads a value from the page's own storage. */
function storage(page, area, key) {
  return page.evaluate(([a, k]) => window[a].getItem(k), [area, key]);
}

const openProfileTab = (page) => page.locator('[data-action="go-profile"]').first().click();

module.exports = { freshEmail, signUp, storage, openProfileTab, PASSWORD };
