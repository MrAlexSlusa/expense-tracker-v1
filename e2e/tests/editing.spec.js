const { test, expect } = require("@playwright/test");
const { signUp, openProfileTab } = require("./helpers");

/*
 * Correcting what is already logged, and choosing a category's icon.
 *
 * Both are things you can only really check in a browser: the amount sheet has
 * to come back prefilled with what you typed the first time, and the icon
 * picker has to find an icon by name and keep it through a save.
 */

async function logExpense(page, digits) {
  await page.locator('.fab').click();
  for (const key of String(digits).split("")) {
    await page.locator(`.key[data-value="${key}"]`).click();
  }
  await page.locator('[data-action="save-expense"]').click();
  await expect(page.locator(".sheet")).toHaveCount(0);
}

test("a logged expense can be corrected, and the row follows the correction", async ({ page }) => {
  await signUp(page);
  await logExpense(page, "40");

  const row = page.locator(".tx-row").first();
  await expect(row.locator(".tx-amount")).toHaveText("$40");
  const originalCategory = (await row.locator(".tx-name").innerText()).trim();

  await row.click();
  await page.locator('[data-action="edit-expense"]').click();

  // The sheet comes back holding the amount that was saved, not an empty one.
  await expect(page.locator(".keypad-amount")).toHaveText("$40");

  for (let i = 0; i < 2; i++) await page.locator('.key[data-value="⌫"]').click();
  for (const key of ["5", "5"]) await page.locator(`.key[data-value="${key}"]`).click();

  // Move it to a different category than the one it landed in.
  const otherPill = page.locator(".cat-pill:not(.is-selected)").first();
  const otherName = (await otherPill.innerText()).trim();
  await otherPill.click();

  await page.locator('[data-action="save-expense"]').click();
  await expect(page.locator(".sheet")).toHaveCount(0);

  await expect(row.locator(".tx-amount")).toHaveText("$55");
  // The row's title is the category's name, so it has to move with it rather
  // than keep announcing the category the expense used to be in.
  await expect(row.locator(".tx-name")).not.toContainText(originalCategory);
  await expect(row.locator(".tx-name")).toContainText(otherName.replace(/^\S+\s/, ""));
});

test("the date of a logged expense can be moved to another day", async ({ page }) => {
  await signUp(page);
  await logExpense(page, "20");

  await page.locator(".tx-row").first().click();
  await page.locator('[data-action="edit-expense"]').click();

  const field = page.locator("#add-date");
  const today = await field.inputValue();
  const earlier = new Date(today);
  earlier.setDate(earlier.getDate() - 3);
  const target = earlier.toISOString().slice(0, 10);

  await field.fill(target);
  await page.locator('[data-action="save-expense"]').click();
  await expect(page.locator(".sheet")).toHaveCount(0);

  // The day headers group by date, so the row moving day is visible in them.
  await expect(page.locator(".day-header").first()).not.toContainText("Today");
});

test("a category icon is picked by name and survives the save", async ({ page }) => {
  await signUp(page);

  await openProfileTab(page);
  await page.locator('[data-action="open-categories"]').click();
  await page.locator('[data-action="edit-category"]').first().click();

  // The panel is closed until the icon itself is pressed - that is the point
  // of it, the form isn't carrying two dozen emoji in the middle of it.
  await expect(page.locator("#emoji-pop")).toBeHidden();
  await page.locator("#cat-emoji").click();
  await expect(page.locator("#emoji-pop")).toBeVisible();

  await page.locator("#emoji-search").fill("coffee");
  const visible = page.locator("#emoji-grid .emoji-swatch:visible");
  await expect(visible).toHaveCount(1);
  await expect(visible.first()).toHaveText("☕");

  await visible.first().click();
  await expect(page.locator("#emoji-pop")).toBeHidden();
  await expect(page.locator("#cat-emoji")).toHaveText("☕");

  await page.locator('[data-action="save-category"]').click();
  await expect(page.locator(".card-row .tile-cat").first()).toBeVisible();
  await expect(page.locator('[data-action="edit-category"]').first()).toContainText("☕");
});

test("a search that finds nothing says so without emptying the screen", async ({ page }) => {
  await signUp(page);
  await logExpense(page, "30");

  await page.locator('[data-action="open-search"]').click();
  await page.locator("#search-input").fill("nothing-matches-this");
  await expect(page.locator(".empty-note")).toBeVisible();

  // The field is still there, still focused, still holding what was typed -
  // typing must not rebuild it.
  await expect(page.locator("#search-input")).toHaveValue("nothing-matches-this");
  await expect(page.locator("#search-input")).toBeFocused();
});
