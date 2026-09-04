// @ts-check
const { defineConfig, devices } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const PORT = 8123;  // deliberately not 8000, so a dev server can stay running
const ROOT = path.join(__dirname, "..");
const TMP = path.join(__dirname, ".tmp");

// Prepared here rather than in globalSetup, because Playwright starts webServer
// before globalSetup and the server cannot open a database in a directory that
// does not exist yet.
//
// Nothing here may delete a database, because this file is re-evaluated in every
// worker process while the server is running. Windows refuses to unlink an open
// file, which merely looked like a nuisance; Linux allows it, and a worker
// deleting the file out from under the server left SQLite writing to an unlinked
// inode - "attempt to write a readonly database", every test failing in CI while
// passing locally. So each run gets its own filename and old ones are swept up
// later, when nothing can still hold them open.
fs.mkdirSync(TMP, { recursive: true });

const DB_FILE = `e2e-${process.pid}-${Date.now()}.db`;

const DAY_MS = 24 * 60 * 60 * 1000;
for (const name of fs.readdirSync(TMP)) {
  const file = path.join(TMP, name);
  try {
    if (Date.now() - fs.statSync(file).mtimeMs > DAY_MS) fs.rmSync(file, { force: true });
  } catch {
    // A file that vanished or is held open is not this run's problem.
  }
}

/*
 * Starts the real FastAPI app against a throwaway SQLite file and drives the
 * real PWA it serves at /app. Nothing here mocks the backend: these tests exist
 * to catch the wiring between the two, which is exactly what unit tests can't
 * see and what was previously only ever checked by hand.
 *
 * DATABASE_URL points at e2e/.tmp so a run can never touch expenses.db, and
 * JWT_SECRET_KEY is pinned because app/auth.py otherwise generates a random one
 * per process - fine in production, but it would invalidate tokens if the
 * server restarted mid-run.
 */
module.exports = defineConfig({
  testDir: "./tests",
  fullyParallel: false,       // one SQLite file, one writer
  workers: 1,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  timeout: 30_000,
  use: {
    baseURL: `http://127.0.0.1:${PORT}/app/`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `python -m uvicorn app.main:app --host 127.0.0.1 --port ${PORT}`,
    cwd: ROOT,
    url: `http://127.0.0.1:${PORT}/`,
    reuseExistingServer: false,
    stdout: "pipe",
    stderr: "pipe",
    timeout: 60_000,
    env: {
      DATABASE_URL: `sqlite:///./e2e/.tmp/${DB_FILE}`,
      JWT_SECRET_KEY: "e2e-fixed-secret-not-used-anywhere-real",
    },
  },
});
