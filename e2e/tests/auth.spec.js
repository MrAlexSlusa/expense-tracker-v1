const { test, expect } = require("@playwright/test");
const { signUp, storage, freshEmail, PASSWORD } = require("./helpers");

test.describe("signing in", () => {
  test("a new account goes through the quiz and into the app", async ({ page }) => {
    const { email } = await signUp(page);
    await expect(page.locator("#app-screen")).toBeVisible();
    // The account it created is the one we asked for.
    const me = await page.evaluate(async () => {
      const r = await fetch(window.API_BASE_URL + "/api/me", {
        headers: { Authorization: "Bearer " + localStorage.getItem("expense_tracker_token") } });
      return r.json();
    });
    expect(me.email).toBe(email);
    expect(me.onboarded).toBe(true);
  });

  test("wrong credentials are refused without signing anyone in", async ({ page }) => {
    await page.goto("./");
    await page.locator("#email").fill("nobody@example.com");
    await page.locator("#password").fill("not-the-password");
    await page.locator("#auth-submit").click();

    await expect(page.locator("#auth-error")).not.toBeEmpty();
    await expect(page.locator("#auth-screen")).toBeVisible();
    expect(await storage(page, "localStorage", "expense_tracker_token")).toBeNull();
  });
});

test.describe("save my login info", () => {
  test("checked, the token persists in localStorage and the email is prefilled", async ({ page }) => {
    const { email } = await signUp(page);

    expect(await storage(page, "localStorage", "expense_tracker_token")).not.toBeNull();
    expect(await storage(page, "sessionStorage", "expense_tracker_token")).toBeNull();

    // Log out, and the login form should remember who was here.
    await page.locator('[data-action="go-accounts"]').first().click();
    await page.locator('[data-action="logout"]').click();
    await expect(page.locator("#auth-screen")).toBeVisible();
    await expect(page.locator("#email")).toHaveValue(email);
  });

  test("unchecked, the token lives only for the session and the email is forgotten", async ({ page }) => {
    await page.goto("./");
    await page.locator("#switch-link").click();          // signup mode
    await page.locator("#remember-me").uncheck();
    await page.locator("#email").fill(freshEmail());
    await page.locator("#password").fill(PASSWORD);
    await page.locator("#auth-submit").click();
    await expect(page.locator("#quiz-screen")).toBeVisible();

    expect(await storage(page, "sessionStorage", "expense_tracker_token")).not.toBeNull();
    expect(await storage(page, "localStorage", "expense_tracker_token")).toBeNull();
    expect(await storage(page, "localStorage", "expense_tracker_remembered_email")).toBeNull();
  });

  test("a remembered session survives a reload, an unremembered one survives too until the tab closes",
    async ({ page, context }) => {
      await signUp(page);
      await page.reload();
      await expect(page.locator("#app-screen")).toBeVisible();

      // A brand-new tab in the same context shares localStorage, so a remembered
      // login is still signed in there - which is the point of the setting.
      const second = await context.newPage();
      await second.goto("./");
      await expect(second.locator("#app-screen")).toBeVisible();
      await second.close();
    });
});
