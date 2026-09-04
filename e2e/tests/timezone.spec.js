const { test, expect } = require("@playwright/test");
const { signUp } = require("./helpers");

/*
 * The timezone picker, and the thing it exists to fix: which calendar day an
 * expense is counted under. The backend tests cover the conversion itself; this
 * covers that the setting is reachable, saves, and visibly re-files an expense.
 */

const settingsRow = (page, label) =>
  page.locator(".settings-row", { hasText: label });

async function openTimeZoneSheet(page) {
  await page.locator('[data-action="go-accounts"]').first().click();
  await page.locator('[data-action="open-timezone"]').click();
  await expect(page.locator(".sheet-title")).toHaveText("Time zone");
}

test("the setting starts at UTC and offers this device's zone", async ({ page }) => {
  await signUp(page);
  await page.locator('[data-action="go-accounts"]').first().click();
  await expect(settingsRow(page, "Time zone")).toContainText("UTC (default)");

  await page.locator('[data-action="open-timezone"]').click();
  // The browser knows hundreds of zones; the list must not be a stub.
  const options = page.locator("#timezone-select option");
  expect(await options.count()).toBeGreaterThan(50);
  await expect(page.locator('[data-action="set-timezone"]')).toContainText("Use this device:");
});

test("picking a zone from the list saves it and shows it in settings", async ({ page }) => {
  await signUp(page);
  await openTimeZoneSheet(page);

  await page.locator("#timezone-select").selectOption("Asia/Tokyo");
  await page.locator('[data-action="save-timezone"]').click();

  await expect(settingsRow(page, "Time zone")).toContainText("Asia/Tokyo");
  // Reopening reflects the saved value rather than resetting to UTC.
  await page.locator('[data-action="open-timezone"]').click();
  await expect(page.locator("#timezone-select")).toHaveValue("Asia/Tokyo");
});

test("the zone survives a reload", async ({ page }) => {
  await signUp(page);
  await openTimeZoneSheet(page);
  await page.locator("#timezone-select").selectOption("America/New_York");
  await page.locator('[data-action="save-timezone"]').click();
  await expect(settingsRow(page, "Time zone")).toContainText("America/New_York");

  await page.reload();
  await page.locator('[data-action="go-accounts"]').first().click();
  await expect(settingsRow(page, "Time zone")).toContainText("America/New_York");
});

test("switching zone re-files an expense onto a different day", async ({ page }) => {
  await signUp(page);

  // 23:30 UTC: still the 10th in London, already the 11th in Tokyo.
  const dates = await page.evaluate(async () => {
    const h = { "Content-Type": "application/json",
                Authorization: "Bearer " + localStorage.getItem("expense_tracker_token") };
    const api = window.API_BASE_URL;
    const cats = await (await fetch(api + "/api/budget", { headers: h })).json();
    await fetch(api + "/api/expenses", { method: "POST", headers: h,
      body: JSON.stringify({ amount: 12, category_id: cats[0].id, date: "2026-04-10", note: "boundary" }) });

    const dayIn = async (zone) => {
      await fetch(api + "/api/me/timezone", { method: "PUT", headers: h,
        body: JSON.stringify({ timezone: zone }) });
      const rows = await (await fetch(api + "/api/expenses?start=2026-04-01&end=2026-04-30",
        { headers: h })).json();
      return rows[0].date;
    };
    return { utc: await dayIn("UTC"), kiritimati: await dayIn("Pacific/Kiritimati") };
  });

  // Stored at noon UTC, so +14 pushes it past midnight into the next day.
  expect(dates.utc).toBe("2026-04-10");
  expect(dates.kiritimati).toBe("2026-04-11");
});

test("an impossible zone is refused and the previous one is kept", async ({ page }) => {
  await signUp(page);
  await openTimeZoneSheet(page);
  await page.locator("#timezone-select").selectOption("Europe/Bucharest");
  await page.locator('[data-action="save-timezone"]').click();
  await expect(settingsRow(page, "Time zone")).toContainText("Europe/Bucharest");

  const status = await page.evaluate(async () => {
    const r = await fetch(window.API_BASE_URL + "/api/me/timezone", {
      method: "PUT",
      headers: { "Content-Type": "application/json",
                 Authorization: "Bearer " + localStorage.getItem("expense_tracker_token") },
      body: JSON.stringify({ timezone: "Mars/Olympus_Mons" }) });
    return r.status;
  });
  expect(status).toBe(400);

  await page.reload();
  await page.locator('[data-action="go-accounts"]').first().click();
  await expect(settingsRow(page, "Time zone")).toContainText("Europe/Bucharest");
});
