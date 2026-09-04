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

/** Signs up and completes the onboarding quiz, landing on the app screen. */
async function signUp(page, email = freshEmail()) {
  await page.goto("./");
  await expect(page.locator("#auth-screen")).toBeVisible();

  await page.locator("#switch-link").click();
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.locator("#auth-submit").click();

  // The quiz appears for every new account; answer each question's first option.
  await expect(page.locator("#quiz-screen")).toBeVisible();
  const questions = page.locator(".quiz-question");
  for (let i = 0; i < (await questions.count()); i++) {
    await questions.nth(i).locator(".quiz-option").first().click();
  }
  await page.locator("#quiz-submit-btn").click();
  await expect(page.locator("#app-screen")).toBeVisible();
  return { email, password: PASSWORD };
}

/** Reads a value from the page's own storage. */
function storage(page, area, key) {
  return page.evaluate(([a, k]) => window[a].getItem(k), [area, key]);
}

const openAccountsTab = (page) => page.locator('[data-action="go-accounts"]').first().click();

module.exports = { freshEmail, signUp, storage, openAccountsTab, PASSWORD };
