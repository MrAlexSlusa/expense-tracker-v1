# Expense Tracker

Log an expense by texting it, or from the app. Same backend, two front doors.

## What's built (v1)

v1 rebuilds `web/` against the "deep navy" design system — a five-tab mobile
app shell (Activity / Summary / Budget / Analytics / Accounts) with a
drill-down category view and three bottom sheets — replacing v0's amber
"Ink & Lamplight" screens. The backend is the same one, extended with
accounts and free date ranges to back the new screens. See
**[The app](#the-app)** below.

- `app/parser.py` — turns free text ("50 groceries", "spent 30 on lunch", "12,50 lei cafea") into an amount + category. 11 tests, all passing, including European comma-decimals.
- `app/webhook.py` — receives WhatsApp messages in Twilio's exact webhook format and replies with a confirmation.
- `app/api.py` — read endpoints: full expense list and a spend-by-category summary, per phone number; plus the app's auth/budget/quiz endpoints (see below).
- `app/auth.py` — email/password accounts with JWT tokens, plus OTP helpers (login 2FA, password reset). Separate identity path from the WhatsApp phone-number flow, same User/Expense tables.
- `app/oauth.py` — Google / Apple / GitHub sign-in as a third identity path onto the same User rows, matched on verified email. Server-side authorization-code flow, since a static frontend can't hold a client secret. Every provider is optional and self-configuring from environment variables — see setup below.
- `app/email_sender.py` — sends OTP codes via [Resend](https://resend.com); if `RESEND_API_KEY` isn't set, it logs the email (and code) to the console instead of failing, so the whole flow is testable locally with no account needed.
- `app/quiz.py` — the signup personality quiz: 4 questions map to tag-weighted scores over a category pool, picking 5 starting budget categories tailored to the answers instead of one generic fixed set.
- `app/models.py` / `app/database.py` — SQLite locally, Postgres in production via `DATABASE_URL`; nothing else changes between the two. `ensure_columns` in `database.py` adds columns a database created by an earlier deploy is missing, since `create_all` only ever creates whole tables and there's no Alembic setup here. The engine uses `pool_pre_ping` — see [Why the pool pings](#why-the-pool-pings) for the failure it prevents.
- `app/sheets.py` — mirrors each expense into a personal Google Sheet budget spreadsheet (see setup below). Optional — only used by the WhatsApp flow.
- `web/privacy.html` / `web/terms.html` — the privacy policy and terms, written against what the app actually does rather than boilerplate. Plain static pages sharing `style.css`, so they follow the app's chosen theme; linked from the foot of the login screen.
- `web/` — an installable PWA (no build step, plain HTML/CSS/JS) served by FastAPI at `/app`. Stepping stone to a native App Store/Play Store app — see below.
- 5 end-to-end tests simulating real Twilio-shaped requests through the full pipeline, plus unit tests for the category-matching logic.

## The app

`web/` is five tabs, a drill-down and three bottom sheets, all rendered from
one state object in a single pass — so adding or deleting an expense updates
the hero total, day-group totals, donut segments, percentage badges, budget
bars, goal split and the chart together, and nothing on screen can disagree
with anything else.

| Tab | What it shows |
| --- | --- |
| **Activity** | Period total and its change from the previous period, a spend-per-day bar chart with an average line, filter pills, and transactions grouped by day. The search pill filters live on name and category. |
| **Summary** | A donut of the period's spend, and the categories ranked by amount with their share as a percentage. Tapping one drills into a single-category ring. |
| **Budget** | Spend against `of $X planned · day N of M`, the Wants/Needs/Savings goal split, and a progress bar per category that turns red past its target. |
| **Analytics** | Spend over time as bars, with that range's transactions below it. Unlike the other tabs it starts with **no** period filter — all time, from the earliest expense to now — and keeps its own period selection, so narrowing Analytics doesn't move Activity or Budget with it. |
| **Accounts** | Profile, six stat cells from `/api/me/stats`, settings, the accounts you spend from, and log out. |

The floating **+** opens a keypad sheet that logs an expense; tapping a
transaction opens a sheet with its date, account and category, and a delete.

**Periods.** The period sheet offers Daily / Weekly / Monthly / Yearly /
Last 12 months, plus **All time** on Analytics, which is where that tab
starts. Anything that isn't a calendar month resolves to an explicit
`start`/`end` pair, which every read endpoint accepts alongside `period`.
Ranges longer than about two months draw one bar per month; shorter ones draw
one per day.

**Currency placement.** Most currencies are written symbol-first (`$9`), but
some belong after the amount in their own convention — RON renders as `9 lei`,
never `lei9`. `SUFFIX_CURRENCIES` in `web/app.js` is the list; everything that
prints an amount (totals, keypad, targets, transaction rows) goes through the
same `fmt()`/`withCurrency()` pair, so there's one place to add to.

**Staying logged in.** The "Save my login info" checkbox on the login screen
decides where the JWT is kept: `localStorage` when it's on (survives closing
the browser, which is the default and what the app always did) or
`sessionStorage` when it's off (gone when the tab closes). Reads check both,
so flipping it mid-session re-homes the live token rather than logging anyone
out, and turning it off also forgets the remembered email.

**Categories, income and profile** are edited from rows in Accounts →
Settings, since the design covers the five tabs but not the management
screens they need. **Theme** (dark/light/system) and **language** (EN/ES/FR/RO)
are local settings; **currency** and **two-factor** are stored on the account.

**Where this deviates from the design handoff**, deliberately:

- Spending *more* than the previous period shows the delta in red with an up
  arrow, not the design's green. The design only illustrates a decrease, and
  reusing its green for an increase would read as good news.
- Goal-split actuals are each tag's share of the period's **income**, not of
  its spend, which is what `GET /api/budget/goals` computes and what the
  source spreadsheets do (see the docstring there).
- The Summary list only shows categories with spend in the period — it's a
  spend ranking, and a category at zero has no donut segment. Categories with
  no spend still appear on Budget, where their target is the point.
- The `Income` toggle switches to Activity and lists that period's income
  rows. Income is month-keyed with no categories, so the donut and the daily
  chart have nothing to draw from it.
- Category colours are assigned client-side from the design's eight-colour
  palette rather than stored per category, keyed on the category's name and
  de-duplicated so no two categories share one.

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
- `GET /api/me` — current user, including `two_factor_enabled`, `onboarded`, `oauth_provider` and `has_password`.
- `GET /api/auth/providers` — which social sign-in buttons the login screen should draw. Empty until credentials are configured (see below).
- `GET /api/auth/oauth/{provider}/start?redirect_uri=...` → 302 to Google/Apple/GitHub; `GET|POST /api/auth/oauth/{provider}/callback` → 302 back to `redirect_uri` with the app JWT in the URL fragment (`#token=...`), or `#oauth_error=...`.
- `GET /api/quiz` — the onboarding quiz's questions/options (text only — the tag weights used for scoring stay server-side).
- `POST /api/onboarding/complete` — `{"answers": {"weekend": "food", ...}}`, replaces the signup-time placeholder category with the 5 quiz-picked ones and marks the account onboarded.
- `GET /api/budget` — this user's budget categories and running totals (the in-app version of the Google Sheet mirror — no Google Sheets setup required for the app to work).
- `GET/POST/PUT/DELETE /api/accounts` — the accounts money is spent from (name, type, last 4 digits, balance, emoji). Descriptive only: the balance is a number you maintain, not a ledger derived from expenses, since most of what moves through a real account never passes through this app. Expenses optionally carry an `account_id`; deleting an account leaves its expenses intact and unattributed.
- `GET /api/budget`, `GET /api/budget/goals` and `GET /api/expenses` also take `start` and `end` (`YYYY-MM-DD`, inclusive, given together) instead of `period`, for the ranges the app's period sheet offers that a single month can't express.
- `PUT /api/me/profile` — `{"display_name": ..., "avatar_url": ...}`, a small (<500KB) `data:image/...` URL for the profile picture.
- `GET /api/me/stats` — total spent, this month's total, monthly average, top category, current daily streak, member-since date — the numbers behind the Profile screen.
- `PUT /api/me/goals` / `GET /api/budget/goals` — the Wants/Needs/Savings target split (must sum to 100%) and, per period, the actual split computed from tagged categories' spend — the app's version of a spreadsheet's GOALS/ACTUAL block.
- `GET/POST/PUT/DELETE /api/income` — named income lines for a period (`?period=YYYY-MM`), mirroring a spreadsheet's INCOME column.
- `POST /api/import/spreadsheet` — upload (`multipart/form-data`) an `.xlsx`/`.csv` export shaped like a personal budget sheet (two parallel INCOME / SPENDINGS+tag tables, plus an optional GOALS block); populates categories (with Needs/Wants/Savings tags), that period's expenses, income rows, and the goal split in one call. Re-importing the same period replaces rather than duplicates. See `app/importer.py` for the parsing rules.

### Setting up social sign-in (optional)

Google, Apple and GitHub are a third way into the same accounts, alongside email/password and the WhatsApp phone number. Each is independent: a provider's button only appears once its credentials are in the environment, and a deploy with none of them configured behaves exactly as it did before.

The flow is server-side authorization code, not a browser-side implicit grant — the frontend is a static bundle on GitHub Pages and can't hold a client secret, so the backend does the exchange and hands back its own JWT. Accounts are matched on **verified** email, so signing in with Google to an address that already has a password gets that same account, not a second one. New social accounts get no password and still run the onboarding quiz.

Two environment variables apply to all providers:

- `OAUTH_ALLOWED_ORIGINS` — comma-separated origins allowed to receive a finished sign-in (e.g. `https://mralexslusa.github.io`). localhost is always allowed. This is a separate list from CORS on purpose: CORS governs who may *read* a response, while a redirect target receives the token in the URL, so an unvalidated one would be an open door.
- `OAUTH_CALLBACK_BASE_URL` — only needed if the backend sits behind a proxy that rewrites its own URL; otherwise the callback is derived from the incoming request.

Each provider needs this exact callback URL registered on its side:

```
<backend base URL>/api/auth/oauth/<provider>/callback
```

| Provider | Where to register | Environment variables |
| --- | --- | --- |
| Google | [console.cloud.google.com](https://console.cloud.google.com) → APIs & Services → Credentials → OAuth client ID (Web application) | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` |
| GitHub | [github.com/settings/developers](https://github.com/settings/developers) → New OAuth App | `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` |
| Apple | [developer.apple.com](https://developer.apple.com) → Certificates, IDs & Profiles → Services ID + Sign in with Apple key. Needs a **paid** Apple Developer account ($99/yr) | `APPLE_CLIENT_ID` (the Services ID, not the App ID), `APPLE_TEAM_ID`, `APPLE_KEY_ID`, `APPLE_PRIVATE_KEY` (the `.p8` contents, newlines as literal `\n`) |

Apple is the odd one out twice over: it has no static client secret (one is minted per request as an ES256 JWT signed with the `.p8` key), and it answers with `response_mode=form_post`, which is why its callback accepts POST as well as GET.

#### What's actually configured

| Provider | State |
| --- | --- |
| Google | **Live and verified end to end.** Client "Expense Tracker" in the `n8n keys` GCP project, with the Render and `localhost:8000` callbacks registered. |
| GitHub | **Live and verified end to end.** OAuth app "Expense Tracker", both callbacks on the one app — GitHub allows multiple redirect URIs, so unlike Google it needs only one app for prod and local. |
| Apple | **Not set up.** The code path is written and unit-tested; it needs a paid Apple Developer account before there are credentials to configure. |

Both live providers were tested by signing out and back in on the deployed
app: each lands on the **existing** account matched by email rather than
creating a second one, leaving expenses, currency, `onboarded` and a
user-set display name untouched. That matching is the part worth re-testing
if the flow is ever changed — getting it wrong silently orphans every
expense behind a duplicate account.

Two things about Google's consent screen are worth knowing before you touch it:

- **It's shared per GCP project, not per client.** The app name shown on the
  consent screen belongs to the project, so setting it here also changes what
  any other OAuth client in the same project displays. If that matters, give
  the tracker its own project instead.
- **Publishing to production is blocked on one remaining thing.** The consent
  screen is in **Testing**, which works for up to 100 hand-added test users
  and is the right setting for a personal tracker. Going to production needs
  an application home page, a privacy policy link and a terms of service link,
  all on a **Google-authorized domain**. The three pages now exist
  (`index.html`, `privacy.html`, `terms.html` on GitHub Pages), so the only
  outstanding piece is the domain: `github.io` is on the public suffix list,
  so Google generally won't accept Pages' hostname as an authorized domain.
  That needs a domain you own pointed at the same files — not a config toggle.
  While unverified, Google also shows the raw callback host
  (`expense-tracker-….onrender.com`) on the consent screen rather than the app
  name.

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

## Why the pool pings

`create_engine` in `app/database.py` sets `pool_pre_ping=True` and
`pool_recycle=300`. Without them, the first request after a quiet spell dies
with:

```
sqlalchemy.exc.OperationalError: (psycopg2.OperationalError)
SSL connection has been closed unexpectedly
```

The managed Postgres drops connections that have been idle a while, and the
pool has no way to know — it hands out a socket the server already closed and
the query fails instead of reconnecting. On a free-tier service that sits idle
between visits, that's a large share of its traffic, which makes it look
random and intermittent rather than reproducible. `pool_pre_ping` checks a
connection is alive before handing it out and transparently swaps in a fresh
one; `pool_recycle` retires connections before they get old enough to be
dropped. Neither does anything for SQLite locally, which is why this only ever
showed up in production.

## Run the test suite

```bash
python3 -m pytest tests/ -v
```

## What's NOT built yet (in order)

1. **Real Twilio connection** — needs a Twilio account + a public URL. ✅ done, if you've followed the deploy steps.
2. **Google Sheet mirror** — ✅ done, code-wise. See setup below to connect your own sheet.
3. **A visual frontend** — ✅ done; `web/` is the app described above.
4. **Filtering by account or category from the pills** — the `All accounts` and `All categories` pills navigate, as the design specifies; neither filters the data yet.
5. **Editing an expense in place** — the transaction sheet offers Close and Delete, per the design. `PUT /api/expenses/{id}` exists and is unused by the app.
6. **Loading and error states** — the design doesn't cover skeletons or error copy; failures currently surface as a message where one fits.
7. **Multi-currency handling** — the account has a currency, but amounts are stored as plain numbers with no per-expense currency or conversion.
8. **Apple sign-in** — the code path is written and unit-tested; it's waiting on a paid Apple Developer account. Google and GitHub are already live.
9. **A public consent screen for Google** — the privacy policy and terms pages now exist, so this is down to needing a custom domain; see [Setting up social sign-in](#setting-up-social-sign-in-optional). Testing mode covers a personal tracker fine.
10. **Self-service account deletion** — individual expenses, categories, accounts and income rows can be deleted, but there's no `DELETE /api/me`, so removing an account is a manual request. The privacy policy says so plainly rather than implying a button that isn't there. Worth building before any app-store submission, which requires it.
11. **Payments** — wire this in before polishing anything else.

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

## Importing your monthly budget spreadsheets

`POST /api/import/spreadsheet` (Accounts → Settings → Import spreadsheet in
the app) backfills a month from an export of the budget sheets described
above. This is how the app got its 2026 history: eight monthly sheets, Jan
through Aug, each exported as CSV and imported in order.

The source files live in Drive at **My Drive → Documents → [01] Spreadsheets
→ [01] Budgeting → `<year>`**, one per month named `<year> <Mon> Budget`.
Note the nesting is Spreadsheets *then* Budgeting, and both carry `[01]`
prefixes — looking for a plain "Budgeting" folder finds nothing.

Three things that will bite you if you don't know them:

- **The period comes from the filename, not the sheet.** `guess_period_from_filename`
  reads `2026 Aug Budget.csv` → `2026-08`. That's deliberate: the title cell
  *inside* several of these sheets is a stale copy from the month they were
  duplicated off (the Apr, Jun and Jul 2026 files all say "May Budget
  Tracker" internally). Keep the filename right and ignore the title, or pass
  `period` explicitly in the form.
- **Import oldest-first.** A month whose sheet has no GOALS block leaves the
  goal split at whatever the previous import set (Aug 2026 is one of these).
  Chronological order means the most recent month with goals wins, which is
  what you want.
- **`"X has no amount - skipped"` warnings are usually correct.** These
  spreadsheets are hand-edited and genuinely have blank amount cells
  (Parcari, Vodafone and Cadouri in various months). The importer skips the
  row and reports it rather than erroring on the whole file.

Re-importing the same period replaces that period's previous import rather
than doubling it, so a corrected sheet can just be uploaded again. Worth
checking after an import: each month's total in the app should equal its
sheet's own `TOTAL EXPENSES` / `TOTAL INCOME` cells.

## Deploying the frontend to GitHub Pages

GitHub Pages only serves static files, so it can host `web/` (the PWA) but
not the FastAPI backend — keep that running elsewhere (e.g. Render), with
Postgres/Neon as its database. The frontend and backend end up on different
origins, which is already accounted for:

1. Deploy `app/` (the backend) somewhere reachable, e.g. Render. Note its
   public URL — Render's free tier appends a random suffix, so it can't be
   guessed ahead of the first deploy.
2. Edit `web/config.js` and set `DEPLOYED_API_URL` to that URL, e.g.
   `"https://expense-tracker.onrender.com"`. Commit the change. `config.js`
   picks the base URL by where the page is served from: localhost talks to
   whatever is serving it (so local dev needs no edit), anything else talks
   to `DEPLOYED_API_URL`.
3. In the repo's **Settings → Pages**, set **Source** to **GitHub Actions**.
4. Push to `main` — [`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml)
   publishes `web/` on every push that touches it (or run it manually from
   the Actions tab).

CORS on the backend is already wide open (`app/main.py`), so it accepts
requests from the Pages origin with no extra config. All asset paths in
`web/` are relative, so the PWA works whether it's served at a domain root,
a GitHub Pages project path (`/expense-tracker/`), or mounted at `/app` by
the FastAPI app itself for local dev.

**Bump `CACHE` in `web/sw.js` on any release that touches a shell file.** The
service worker is network-first, which usually hides a stale cache — but a
page loaded *while* a deploy is propagating can take some files from the
network and others from the cache. That has happened in practice: a build ran
new `app.js` against old `i18n.js` and rendered raw translation keys
(`allTime` instead of "All time"). A new cache name makes the `activate`
handler drop the whole previous set at once, so a load is all-new or all-old
and never a mix. Anyone already running the PWA picks the new set up on their
next reload.

## Your move

Log a week of real expenses through the app and the WhatsApp webhook both,
then look at Budget at the end of it. Whichever number you don't trust is the
next thing to fix.
