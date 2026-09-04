const { test, expect } = require("@playwright/test");
const { signUp, storage, PASSWORD } = require("./helpers");

/*
 * The flow this suite exists for. A wrong password here used to clear the token
 * and bounce the user to the login screen with "Session expired" - apiFetch
 * treated every authenticated 401 as a dead session. No unit test can see that:
 * it only appears when the real request meets the real error handler.
 */
async function openDeleteSheet(page) {
  await page.locator('[data-action="go-accounts"]').first().click();
  await page.locator('[data-action="open-delete-account"]').click();
  await expect(page.locator(".sheet-title")).toHaveText("Delete account");
}

test("a wrong password is refused without ending the session", async ({ page }) => {
  await signUp(page);
  await openDeleteSheet(page);

  await page.locator("#delete-password").fill("definitely-not-it");
  await page.locator('[data-action="confirm-delete-account"]').click();

  await expect(page.locator(".sheet-scrim .error")).toHaveText("Incorrect password");
  // Still signed in, still on the app, sheet still open to try again.
  await expect(page.locator("#app-screen")).toBeVisible();
  await expect(page.locator(".sheet-title")).toBeVisible();
  expect(await storage(page, "localStorage", "expense_tracker_token")).not.toBeNull();
});

test("an empty password is refused before any request is made", async ({ page }) => {
  await signUp(page);
  await openDeleteSheet(page);

  let deleteAttempted = false;
  page.on("request", (r) => { if (r.method() === "DELETE") deleteAttempted = true; });
  await page.locator('[data-action="confirm-delete-account"]').click();

  await expect(page.locator(".sheet-scrim .error")).toContainText("password");
  expect(deleteAttempted).toBe(false);
  await expect(page.locator("#app-screen")).toBeVisible();
});

test("the right password erases the account and returns to the login screen", async ({ page }) => {
  const { email } = await signUp(page);
  await openDeleteSheet(page);

  await page.locator("#delete-password").fill(PASSWORD);
  await page.locator('[data-action="confirm-delete-account"]').click();

  await expect(page.locator("#auth-screen")).toBeVisible();
  expect(await storage(page, "localStorage", "expense_tracker_token")).toBeNull();
  expect(await storage(page, "sessionStorage", "expense_tracker_token")).toBeNull();
  expect(await storage(page, "localStorage", "expense_tracker_remembered_email")).toBeNull();
  await expect(page.locator("#sheet-root")).toBeEmpty();

  // The account really is gone, not merely signed out of.
  const status = await page.evaluate(async (creds) => {
    const r = await fetch(window.API_BASE_URL + "/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(creds) });
    return r.status;
  }, { email, password: PASSWORD });
  expect(status).toBe(401);
});

test("deleting one account leaves another signed-in account untouched", async ({ browser }) => {
  const keeperCtx = await browser.newContext();
  const keeper = await keeperCtx.newPage();
  const kept = await signUp(keeper);

  const doomedCtx = await browser.newContext();
  const doomed = await doomedCtx.newPage();
  await signUp(doomed);
  await doomed.locator('[data-action="go-accounts"]').first().click();
  await doomed.locator('[data-action="open-delete-account"]').click();
  await doomed.locator("#delete-password").fill(PASSWORD);
  await doomed.locator('[data-action="confirm-delete-account"]').click();
  await expect(doomed.locator("#auth-screen")).toBeVisible();

  await keeper.reload();
  await expect(keeper.locator("#app-screen")).toBeVisible();
  const me = await keeper.evaluate(async () => {
    const r = await fetch(window.API_BASE_URL + "/api/me", {
      headers: { Authorization: "Bearer " + localStorage.getItem("expense_tracker_token") } });
    return r.json();
  });
  expect(me.email).toBe(kept.email);

  await keeperCtx.close();
  await doomedCtx.close();
});
