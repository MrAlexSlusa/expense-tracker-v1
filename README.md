# Expense Tracker

Log an expense by texting it, or from the app. Same backend, two front doors.

## What's built (v0)

- `app/parser.py` — turns free text ("50 groceries", "spent 30 on lunch", "12,50 lei cafea") into an amount + category. 11 tests, all passing, including European comma-decimals.
- `app/webhook.py` — receives WhatsApp messages in Twilio's exact webhook format and replies with a confirmation.
- `app/api.py` — read endpoints: full expense list and a spend-by-category summary, per phone number; plus the app's auth/budget/quiz endpoints (see below).
- `app/auth.py` — email/password accounts with JWT tokens, plus OTP helpers (login 2FA, password reset). Separate identity path from the WhatsApp phone-number flow, same User/Expense tables.
- `app/email_sender.py` — sends OTP codes via [Resend](https://resend.com); if `RESEND_API_KEY` isn't set, it logs the email (and code) to the console instead of failing, so the whole flow is testable locally with no account needed.
- `app/quiz.py` — the signup personality quiz: 4 questions map to tag-weighted scores over a category pool, picking 5 starting budget categories tailored to the answers instead of one generic fixed set.
- `app/models.py` / `app/database.py` — SQLite for now; one line to swap to Postgres later.
- `app/sheets.py` — mirrors each expense into a personal Google Sheet budget spreadsheet (see setup below). Optional — only used by the WhatsApp flow.
- `web/` — an installable PWA (no build step, plain HTML/CSS/JS) served by FastAPI at `/app`: sign up, take the onboarding quiz, log expenses, and see a live budget-by-category view. Stepping stone to a native App Store/Play Store app — see below.
- 5 end-to-end tests simulating real Twilio-shaped requests through the full pipeline, plus unit tests for the category-matching logic.

## Run it locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then visit `http://localhost:8000` — you should see `{"status": "running"}`.

Visit `http://localhost:8000/app/` for the PWA: sign up, answer the 4-question onboarding quiz, and you land on a budget already set up with categories that fit you.

On a phone, open that same URL in the browser and use "Add to Home Screen" (Safari) or the install prompt (Chrome) to install it like an app.

### App account endpoints

- `POST /api/auth/signup` / `POST /api/auth/login` — `{"email": ..., "password": ...}`. Login returns either a JWT directly, or `{"requires_otp": true}` if the account has 2FA on (see below).
- `POST /api/auth/verify-otp` — `{"email": ..., "code": ...}`, exchanges a login OTP for a JWT.
- `POST /api/auth/forgot-password` — `{"email": ...}`, emails a reset code. Always returns `{"sent": true}` regardless of whether the email exists, so this can't be used to check who has an account.
- `POST /api/auth/reset-password` — `{"email": ..., "code": ..., "new_password": ...}`.
- `PUT /api/me/two-factor` — `{"enabled": true|false}` (needs `Authorization: Bearer <token>`). When on, every login emails a 6-digit code that has to be verified before a JWT is issued.
- `GET /api/me` — current user, including `two_factor_enabled` and `onboarded`.
- `GET /api/quiz` — the onboarding quiz's questions/options (text only — the tag weights used for scoring stay server-side).
- `POST /api/onboarding/complete` — `{"answers": {"weekend": "food", ...}}`, replaces the signup-time placeholder category with the 5 quiz-picked ones and marks the account onboarded.
- `GET /api/budget` — this user's budget categories and running totals (the in-app version of the Google Sheet mirror — no Google Sheets setup required for the app to work).
- `PUT /api/me/profile` — `{"display_name": ..., "avatar_url": ...}`, a small (<500KB) `data:image/...` URL for the profile picture.
- `GET /api/me/stats` — total spent, this month's total, monthly average, top category, current daily streak, member-since date — the numbers behind the Profile screen.
- `PUT /api/me/goals` / `GET /api/budget/goals` — the Wants/Needs/Savings target split (must sum to 100%) and, per period, the actual split computed from tagged categories' spend — the app's version of a spreadsheet's GOALS/ACTUAL block.
- `GET/POST/PUT/DELETE /api/income` — named income lines for a period (`?period=YYYY-MM`), mirroring a spreadsheet's INCOME column.
- `POST /api/import/spreadsheet` — upload (`multipart/form-data`) an `.xlsx`/`.csv` export shaped like a personal budget sheet (two parallel INCOME / SPENDINGS+tag tables, plus an optional GOALS block); populates categories (with Needs/Wants/Savings tags), that period's expenses, income rows, and the goal split in one call. Re-importing the same period replaces rather than duplicates. See `app/importer.py` for the parsing rules.

### Setting up real OTP emails (optional)

Without any configuration, OTP codes for login/reset just get printed to the server console — enough to test the whole flow locally. To actually email them:

1. Create a free account at [resend.com](https://resend.com) and grab an API key.
2. Set `RESEND_API_KEY` in your environment (Render: service → **Environment** tab).
3. Optionally set `RESEND_FROM_EMAIL` to a verified sender; otherwise it sends from `onboarding@resend.dev`, which works without verifying your own domain.

### Path to a real App Store / Google Play app

The PWA is deliberately framework-free so nothing here is wasted work: wrapping it in [Capacitor](https://capacitorjs.com/) later gets you a real iOS/Android binary from the same HTML/CSS/JS, calling the same JSON API. Bigger changes than styling — offline queueing, push notifications for spend alerts, App Store review requirements (privacy policy, account deletion) — are easier to reason about once the wrapping step happens, not before.

## Test it without a real Twilio account yet

```bash
curl -X POST http://localhost:8000/webhook/whatsapp \
  -d "From=whatsapp:+40712345678" \
  -d "Body=50 groceries"
```

Then check the summary:

```bash
curl http://localhost:8000/api/users/whatsapp:+40712345678/summary
```

## Run the test suite

```bash
python3 -m pytest tests/ -v
```

## What's NOT built yet (in order)

1. **Real Twilio connection** — needs a Twilio account + a public URL. ✅ done, if you've followed the deploy steps.
2. **Google Sheet mirror** — ✅ done, code-wise. See setup below to connect your own sheet.
3. **A simple dashboard** — the API returns JSON; there's no visual frontend yet.
4. **Multi-currency handling** — amounts are just numbers with no currency tracking yet.
5. **Payments** — wire this in before polishing the dashboard, not after.

## Setting up the Google Sheet (one-time)

This syncs to a personal budget sheet with a fixed set of category rows and a
running total per category (e.g. `Supermarket | 859,96 lei`) — texting an
expense doesn't add a new row, it adds the amount to the matching category's
total. Each month is its own spreadsheet **file** (e.g. "2026 Aug Budget"),
not a tab within one ongoing file — the app always writes to whichever
file's Sheet ID is set as `GOOGLE_SHEET_ID`, on that file's first tab.

This uses a service account — a robot Google identity, separate from your
personal login — because the server needs to write to the sheet with nobody
around to click "Allow."

1. Go to [console.cloud.google.com](https://console.cloud.google.com), create a project (any name).
2. In the search bar, find **Google Sheets API** and click Enable.
3. Go to **IAM & Admin → Service Accounts → Create Service Account**. Any name works. Skip the optional permission steps, click Done.
4. Click into the service account you just made → **Keys** tab → **Add Key → Create new key → JSON**. This downloads a `.json` file — keep it private, it's a credential.
5. Open that JSON file, find the `"client_email"` field (looks like `something@your-project.iam.gserviceaccount.com`).
6. In your budget spreadsheet's first tab, make sure category names are in column C starting at row 6, with their running totals in column D — same layout as the existing sheet.
7. Click **Share** on that spreadsheet, paste in the service account's email from step 5, give it **Editor** access.
8. Copy the Sheet ID from the URL — the long string between `/d/` and `/edit`.
9. On Render: go to your service → **Environment** tab → add two variables:
   - `GOOGLE_SERVICE_ACCOUNT_JSON` — paste the *entire contents* of the JSON file as the value.
   - `GOOGLE_SHEET_ID` — paste the ID from step 8.
10. Render will redeploy automatically. Text something like `supermarket 50` and check the sheet — the Supermarket total should go up within a couple seconds.

Text the **category name** (typos are fine — `supermrket` still matches), not a merchant name — `auchan 50` won't guess it means Supermarket, it'll fall back to `Altele` on purpose rather than risk updating the wrong category.

At the start of a new month: create that month's new budget file, share it with the same service account email (step 7), copy its Sheet ID, and update `GOOGLE_SHEET_ID` on Render to that new ID — the app always points at whichever file that variable names.

If a row doesn't update, check Render's Logs tab — the app prints exactly why (missing env vars, wrong permissions, sheet not shared, etc.) instead of failing silently.

## Deploying the frontend to GitHub Pages

GitHub Pages only serves static files, so it can host `web/` (the PWA) but
not the FastAPI backend — keep that running elsewhere (e.g. Render), with
Postgres/Neon as its database. The frontend and backend end up on different
origins, which is already accounted for:

1. Deploy `app/` (the backend) somewhere reachable, e.g. Render. Note its
   public URL.
2. Edit `web/config.js` and set `window.API_BASE_URL` to that URL, e.g.
   `"https://expense-tracker.onrender.com"`. Commit the change.
3. In the repo's **Settings → Pages**, set **Source** to **GitHub Actions**.
4. Push to `main` — [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml)
   publishes `web/` on every push that touches it (or run it manually from
   the Actions tab).

CORS on the backend is already wide open (`app/main.py`), so it accepts
requests from the Pages origin with no extra config. All asset paths in
`web/` are relative, so the PWA works whether it's served at a domain root,
a GitHub Pages project path (`/expense-tracker/`), or mounted at `/app` by
the FastAPI app itself for local dev.

## Your move

Test the parser against messages you'd *actually* send yourself — typos, weird phrasing, whatever. If it breaks on something real, that's the next thing to fix before building the dashboard on top of it.
