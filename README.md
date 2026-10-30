# Expense Tracker

Log an expense from the app: a PWA frontend on a FastAPI + SQL backend.

## What's built (v1)

v1 rebuilds `web/` against the "deep navy" design system — a five-tab mobile
app shell (Activity / Summary / Budget / Analytics / Profile) with a
drill-down category view and three bottom sheets — replacing v0's amber
"Ink & Lamplight" screens. The backend is the same one, extended with
free date ranges to back the new screens. See
**[The app](#the-app)** below.

- `app/api.py` — the app's auth, expense and budget endpoints (see below).
- `app/auth.py` — email/password accounts with JWT tokens, plus the OTP helpers behind password reset.
- `app/oauth.py` — Google / Apple / GitHub sign-in as a second identity path onto the same User rows, matched on verified email. Server-side authorization-code flow, since a static frontend can't hold a client secret. Every provider is optional and self-configuring from environment variables — see setup below.
- `app/email_sender.py` — sends OTP codes via [Resend](https://resend.com); if `RESEND_API_KEY` isn't set, it logs the email (and code) to the console instead of failing, so the whole flow is testable locally with no account needed.
- `app/starter.py` — the categories a new account opens with, worded in the signup language. This replaced a four-question personality quiz: it was answered once, by someone who had not seen the app yet, to decide something they can change in two taps.
- `app/gocardless.py` — client for GoCardless Bank Account Data, the open-banking (PSD2) provider the Revolut import runs on. Token minting, the consent round trip, accounts and transactions. Optional: with no credentials set, the bank panel stays hidden and everything else behaves exactly as before.
- `app/categorizer.py` — turns a noisy bank description ("CARD PAYMENT TO LIDL 0412 BUCURESTI") into a merchant key, then into one of *your* categories, via learned rules first, a built-in table of Romanian merchants second, and the card network's MCC last. Returns nothing rather than guessing.
- `app/bank_sync.py` — the sync loop: dedupe, drop money coming in and the bank's own transfers, convert currencies, file what it is sure of and park the rest in a confirm inbox.
- `app/bank_api.py` — the bank endpoints, including the one the bank's own redirect lands on.
- `app/models.py` / `app/database.py` — SQLite locally, Postgres in production via `DATABASE_URL`; nothing else changes between the two. `ensure_columns` in `database.py` adds columns a database created by an earlier deploy is missing, since `create_all` only ever creates whole tables and there's no Alembic setup here. The engine uses `pool_pre_ping` — see [Why the pool pings](#why-the-pool-pings) for the failure it prevents.
- `web/privacy.html` / `web/terms.html` — the privacy policy and terms, written against what the app actually does rather than boilerplate. Plain static pages sharing `style.css`, so they follow the app's chosen theme; linked from the foot of the login screen.
- `web/` — an installable PWA (no build step, plain HTML/CSS/JS) served by FastAPI at `/app`. Stepping stone to a native App Store/Play Store app — see below.
- Unit and API tests over the whole pipeline: parsing, category matching, auth, budgets, currency conversion and account deletion.

## The app

`web/` is five tabs, a drill-down and three bottom sheets, all rendered from
one state object in a single pass — so adding or deleting an expense updates
the hero total, day-group totals, donut segments, percentage badges, budget
bars and the chart together, and nothing on screen can disagree
with anything else.

| Tab | What it shows |
| --- | --- |
| **Activity** | Period total and its change from the previous period, a spend-per-day bar chart with an average line, filter pills, and transactions grouped by day. The search pill filters live on name and category. |
| **Summary** | A donut of the period's spend, and the categories ranked by amount with their share as a percentage. Tapping one drills into a single-category ring. |
| **Budget** | Spend against `of $X planned · day N of M`, and a progress bar per category that turns red past its target. |
| **Analytics** | Spend over time as bars, with that range's transactions below it. Unlike the other tabs it starts with **no** period filter — all time, from the earliest expense to now — and keeps its own period selection, so narrowing Analytics doesn't move Activity or Budget with it. |
| **Profile** | Your identity, four stat cells from `/api/me/stats`, settings, and log out. |

The floating **+** opens a keypad sheet that logs an expense; tapping a
transaction opens a sheet with its date and category, and a delete.

**Periods.** The period sheet offers Daily / Weekly / Monthly / Yearly /
Last 12 months, plus **All time** on Analytics, which is where that tab
starts. Anything that isn't a calendar month resolves to an explicit
`start`/`end` pair, which every read endpoint accepts alongside `period`.
Ranges longer than about two months draw one bar per month; shorter ones draw
one per day.

**Time zones.** Every expense is stored as a UTC instant and always has been.
What changed is that the *day* it counts under is now measured in the user's
own zone, set from Profile → Settings → Time zone (which offers the browser's
detected zone in one tap). Unset means UTC.

This matters more than it sounds. The app previously mixed two clocks: expenses
were stamped with `datetime.utcnow()` while "this month" and default
periods used `date.today()` — the *server's* local date. Those agree only when
the server and the user are both on UTC. For a user at UTC+3, everything logged
between midnight and 03:00 was filed to the previous day, so an expense
added just after midnight on the 1st landed in the previous month. `app/api.py` now has no bare
`date.today()`: `today_for(user)`, `local_date()` and `_utc_window()` do the
conversion, the last one because a calendar day in a user's zone is a UTC window
shifted by the offset, which is what the queries actually filter on. A stale or
misspelled zone degrades to UTC rather than erroring.

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

**Deleting an account** is Profile → Delete account, which asks for the
password again (or, for a social-only account with no password, for the word
DELETE typed out) before calling `DELETE /api/me`. A 401 there means a wrong
password, not an expired session, so `apiFetch` takes a `credentialCheck` flag
that suppresses its usual log-out-and-bounce behaviour — without it a typo
threw the user out of the app.

**Categories and profile** are edited from rows in Profile → Settings,
since the design covers the five tabs but not the management screens they
need. **Theme** (dark/light/system) and **language** (EN/ES/FR/RO) are local
settings; **currency** is stored on the account.

**Where this deviates from the design handoff**, deliberately:

- Spending *more* than the previous period shows the delta in red with an up
  arrow, not the design's green. The design only illustrates a decrease, and
  reusing its green for an increase would read as good news.
- The Summary list only shows categories with spend in the period — it's a
  spend ranking, and a category at zero has no donut segment. Categories with
  no spend still appear on Budget, where their target is the point.
- Category colours are assigned client-side from the design's eight-colour
  palette rather than stored per category, keyed on the category's name and
  de-duplicated so no two categories share one.

## Run it locally

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Then visit `http://localhost:8000` — you should see `{"status": "running"}`.

Visit `http://localhost:8000/app/` for the PWA: sign up and you land straight on a budget, with a starter set of categories already there to rename, retarget or delete.

On a phone, open that same URL in the browser and use "Add to Home Screen" (Safari) or the install prompt (Chrome) to install it like an app.

### App account endpoints

- `POST /api/auth/signup` / `POST /api/auth/login` — `{"email": ..., "password": ...}`, returning a JWT. Signup also takes `lang`, which decides the wording of the starter categories it creates. The address is matched and stored case-insensitively, so one address is always one account.
- `POST /api/auth/forgot-password` — `{"email": ...}`, emails a reset code. Always returns `{"sent": true}` regardless of whether the email exists, so this can't be used to check who has an account.
- `POST /api/auth/reset-password` — `{"email": ..., "code": ..., "new_password": ...}`.
- `GET /api/me` — current user, including `oauth_provider` and `has_password`. Takes an optional `lang`, used only to top up an account left half-set-up by the signup quiz this replaced.
- `DELETE /api/me` — erases the account and everything belonging to it (expenses, categories, OTP codes), in one transaction. An account with a password must re-send it in the body: a 30-day bearer token sitting in browser storage is too weak a proof for something irreversible. A social-only account has no password to ask for and deletes on the token alone.
- `GET /api/auth/providers` — which social sign-in buttons the login screen should draw. Empty until credentials are configured (see below).
- `GET /api/auth/oauth/{provider}/start?redirect_uri=...` → 302 to Google/Apple/GitHub; `GET|POST /api/auth/oauth/{provider}/callback` → 302 back to `redirect_uri` with the app JWT in the URL fragment (`#token=...`), or `#oauth_error=...`.
- `GET /api/budget` — this user's budget categories and running totals for the period.
- `GET /api/budget` and `GET /api/expenses` also take `start` and `end` (`YYYY-MM-DD`, inclusive, given together) instead of `period`, for the ranges the app's period sheet offers that a single month can't express.
- `PUT /api/me/timezone` — `{"timezone": "Europe/Bucharest"}`, an IANA name, or `""` for UTC. Validated against the system zone database; an unknown name is a 400.
- `PUT /api/me/profile` — `{"display_name": ..., "avatar_url": ...}`, a small (<500KB) `data:image/...` URL for the profile picture.
- `GET /api/me/stats` — total spent, this month's total, monthly average, top category, member-since date — the numbers behind the Profile screen.
- `POST /api/import/spreadsheet` — upload (`multipart/form-data`) an `.xlsx`/`.csv` export shaped like a personal budget sheet (two parallel INCOME / SPENDINGS+tag tables, plus an optional GOALS block); populates categories (with Needs/Wants/Savings tags) and that period's expenses. The sheet's income column and GOALS block are recognised and stepped over rather than imported — recognising them is what keeps their rows from being read as spending. Re-importing the same period replaces rather than duplicates. See `app/importer.py` for the parsing rules.

### Setting up social sign-in (optional)

Google, Apple and GitHub are a second way into the same accounts, alongside email/password. Each is independent: a provider's button only appears once its credentials are in the environment, and a deploy with none of them configured behaves exactly as it did before.

The flow is server-side authorization code, not a browser-side implicit grant — the frontend is a static bundle on GitHub Pages and can't hold a client secret, so the backend does the exchange and hands back its own JWT. Accounts are matched on **verified** email, so signing in with Google to an address that already has a password gets that same account, not a second one. New social accounts get no password and land in the app with the English starter categories, which can be renamed like any other.

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
| Google | **Live, verified end to end, and published to production** — open to any Google account, not just test users. Client "Expense Tracker" in the `n8n keys` GCP project, with the Render and `localhost:8000` callbacks registered. |
| GitHub | **Live and verified end to end.** OAuth app "Expense Tracker", both callbacks on the one app — GitHub allows multiple redirect URIs, so unlike Google it needs only one app for prod and local. |
| Apple | **Not set up.** The code path is written and unit-tested; it needs a paid Apple Developer account before there are credentials to configure. |

Both live providers were tested by signing out and back in on the deployed
app: each lands on the **existing** account matched by email rather than
creating a second one, leaving expenses, currency and a user-set display
name untouched. That matching is the part worth re-testing
if the flow is ever changed — getting it wrong silently orphans every
expense behind a duplicate account.

Two things about Google's consent screen are worth knowing before you touch it:

- **It's shared per GCP project, not per client.** The app name shown on the
  consent screen belongs to the project, so setting it here also changes what
  any other OAuth client in the same project displays. If that matters, give
  the tracker its own project instead.
- **It is published, and a GitHub Pages domain was enough.** Going to
  production needed three things on the Branding page — an application home
  page, a privacy policy link and a terms of service link — plus their host
  registered under **Authorized domains**. All three point at the Pages site,
  and **`mralexslusa.github.io` was accepted as an authorized domain without
  complaint**. No custom domain, and no verification review: Google requires
  that only for more than 10 domains, an uploaded logo, or sensitive scopes,
  and this app has two domains, no logo, and only `openid email profile`.

  Worth recording because the opposite was assumed at first: `github.io` is on
  the public suffix list, which suggested Google would reject it. It did not.
  If publishing ever needs redoing, fill the three URL fields and add the host
  under Authorized domains — don't go buying a domain on the assumption that
  Pages won't work.

  Two consequences of being published: the consent screen now links the
  privacy policy and terms, and any Google account can sign in. To pull that
  back, **Back to testing** on the Audience page returns it to a test-user
  allowlist.

### Setting up real OTP emails (optional)

Without any configuration, OTP codes for login/reset just get printed to the server console — enough to test the whole flow locally. To actually email them:

1. Create a free account at [resend.com](https://resend.com) and grab an API key.
2. Set `RESEND_API_KEY` in your environment (Render: service → **Environment** tab).
3. Optionally set `RESEND_FROM_EMAIL` to a verified sender; otherwise it sends from `onboarding@resend.dev`, which works without verifying your own domain.

### Path to a real App Store / Google Play app

The PWA is deliberately framework-free so nothing here is wasted work: wrapping it in [Capacitor](https://capacitorjs.com/) later gets you a real iOS/Android binary from the same HTML/CSS/JS, calling the same JSON API. Bigger changes than styling — offline queueing, push notifications for spend alerts, App Store review requirements (privacy policy, account deletion) — are easier to reason about once the wrapping step happens, not before.

## Clearing out the accounts feature

The "accounts you spend from" feature was removed. The code no longer knows
about it, but a database created before the removal still has the `accounts`
table and the `expenses.account_id` column: `create_all` only ever creates
tables and `ensure_columns` only ever adds columns, so nothing drops them on
its own. They are inert - no query touches them - so this is tidiness rather
than a fix.

```bash
python scripts/drop_account_tables.py        # show the plan
python scripts/drop_account_tables.py --yes  # apply it
```

It reads `DATABASE_URL` exactly as the app does, so point that at production to
clean production. `--yes` is required rather than a prompt, because an
accidental run against a live database should do nothing. The expenses
themselves are untouched - only which account paid for them goes, along with
the accounts and their balances. Running it twice is safe; the second run says
there is nothing to do.

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

That covers `web/` as well as the backend. `tests/test_web_units.py` runs the
real `web/i18n.js` and `web/app.js` through `tests/js_harness.js`, which loads
them in Node against a stub DOM - so the pure logic (money formatting, date
ranges, chart bucketing, token storage, escaping, the translation tables) is
checked by the same one command, with no test framework in the browser, no
`node_modules`, and no build step. Those tests skip themselves if Node isn't
installed.

`tests/test_bank_sync.py` covers the Revolut import without ever calling the
aggregator: the three GoCardless read functions are stubbed, so what gets
tested is the filing decision - normalisation, the rule/keyword/MCC order,
dedupe across re-runs, income never becoming an expense, and the confirm
inbox - rather than httpx. A test that needs a live PSD2 consent is a test
nobody runs.

Anything needing a real DOM - rendering, sheets, event wiring - is covered by
the end-to-end suite instead.

### End to end

```bash
cd e2e && npm install && npx playwright install chromium
npx playwright test
```

[Playwright](https://playwright.dev) drives a real browser against the real
FastAPI app, which serves the real PWA at `/app` - nothing is mocked, because
the point is to catch the wiring between the two. It covers signup straight
into the app, wrong credentials, both settings of "Save my login info",
`9 lei` versus `$9`, Analytics opening on All time and keeping its period
separate from the other tabs, the privacy and terms links, and the whole
delete-account flow including that a wrong password does **not** end the
session.

The server runs on port 8123 against a throwaway SQLite file in `e2e/.tmp/`,
so a run can never touch `expenses.db` and never needs the dev server stopped.
`JWT_SECRET_KEY` is pinned there because `app/auth.py` otherwise generates a
random one per process, which would invalidate tokens if the server restarted
mid-run.

`e2e/` is the only part of this repo with npm dependencies; `web/` itself stays
dependency-free and keeps its no-build-step property. Both suites run in CI on
every push - see [`.github/workflows/tests.yml`](.github/workflows/tests.yml).

One caveat worth knowing: e2e tests assert on user-visible English strings
("Incorrect password", "All time"). Rewording those means updating the tests,
which is the intended trade - it is the same coupling that makes them able to
catch a regression a unit test cannot see.

## Automatic Revolut import

Card payments show up in the budget on their own, under the right category,
without anyone typing them in.

**Why open banking and not Revolut's API.** Revolut publishes an API for
Revolut *Business* only — a personal account has no API at all. The way in
is PSD2: a licensed account information service reads the account with your
consent. This uses [GoCardless Bank Account
Data](https://bankaccountdata.gocardless.com/) (the former Nordigen), which
is free, covers Revolut in Romania, and means the app never sees a Revolut
password. The same machinery works for any other PSD2 bank, so the picker
lists them all with Revolut first.

**How a transaction becomes an expense.**

1. The sync pulls booked transactions (pending ones are skipped — their ids
   change when they settle, which would either duplicate the expense or
   strand it).
2. Incoming money, top-ups and vault moves are recorded and dropped: they
   are not spending.
3. The merchant is normalised — `CARD PAYMENT TO LIDL 0412 BUCURESTI` →
   `lidl bucuresti` — so one rule covers every branch and every spelling.
4. The category is decided by, in order: a rule you wrote by filing that
   merchant yourself, a built-in table of merchants common on a Romanian
   card, then the card network's MCC.
5. If none of those resolves, the transaction waits in **To confirm** rather
   than being guessed at. Filing it there writes the rule, so that merchant
   never asks again.

Amounts in another currency are converted with the same BNR rates the rest
of the app uses, and keep the original (`€25 (131.31 lei)`). If rates are
unavailable the transaction waits instead of being filed at a made-up rate.

### Setting it up

1. Sign up at <https://bankaccountdata.gocardless.com/> (free, no card) and
   create a secret pair under **Developers → User secrets**.
2. Set `GOCARDLESS_SECRET_ID` and `GOCARDLESS_SECRET_KEY` on the backend
   (Render → Environment, or `.env` locally). Until both are set the bank
   row does not appear in the app at all.
3. Make sure `OAUTH_ALLOWED_ORIGINS` contains wherever the frontend is
   served from — the bank redirects the browser back there, and the same
   allowlist that guards social sign-in guards this.
4. In the app: **Profile → Bank sync → Connect a bank → Revolut**, then
   authenticate in Revolut. You come back to a filled-in budget: the first
   90 days are imported straight away.

### Keeping it automatic

`POST /api/bank/sync-all` syncs every linked connection. It is authenticated
with a shared secret header rather than a user token (there is no user on a
scheduled run) and 404s unless `CRON_SECRET` is set, so a deployment that
never configured one has no endpoint sitting open.

`.github/workflows/sync-banks.yml` calls it once a day. It needs two things
on the repository: a `CRON_SECRET` **secret** matching the backend's, and an
`API_URL` **variable** pointing at the backend. Without them the workflow
exits quietly instead of failing every morning.

Once a day is deliberate — banks book card payments once a day, and
GoCardless caps transaction calls per account per day, so a tighter schedule
buys nothing and risks the cap. A Render cron job is the alternative if you
ever move off the free plan: `python -m scripts.sync_banks` does the same
work in-process.

### The 90-day consent

PSD2 caps consent at 90 days. After that every call for that connection
fails until you re-authenticate — there is no way around it, for anyone.
The app shows the countdown on the bank page and flips the connection to
**Consent expired** when it runs out; reconnecting is the same flow as the
first time, and already-imported expenses are untouched.

Disconnecting a bank removes the connection and its transaction records but
keeps the expenses: those are your spending history, not a cache of the
bank's.

## What's NOT built yet (in order)

1. **A visual frontend** — ✅ done; `web/` is the app described above.
2. **Filtering by category from the pills** — the `All categories` pill navigates, as the design specifies; it doesn't filter the data yet.
3. **Editing an expense in place** — the transaction sheet offers Close and Delete, per the design. `PUT /api/expenses/{id}` exists and is unused by the app.
4. **Loading and error states** — the design doesn't cover skeletons or error copy; failures currently surface as a message where one fits.
5. **Apple sign-in** — the code path is written and unit-tested; it's waiting on a paid Apple Developer account. Google and GitHub are already live.
6. **Payments** — wire this in before polishing anything else.
7. **A second bank** — the connection model and the picker already handle more than one; only the Revolut path has been exercised end to end.

## Importing your monthly budget spreadsheets

`POST /api/import/spreadsheet` (Profile → Settings → Import spreadsheet in
the app) backfills a month from an export of a monthly budget spreadsheet.
This is how the app got its 2026 history: eight monthly sheets, Jan
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
- **`"X has no amount - skipped"` warnings are usually correct.** These
  spreadsheets are hand-edited and genuinely have blank amount cells
  (Parcari, Vodafone and Cadouri in various months). The importer skips the
  row and reports it rather than erroring on the whole file.

Re-importing the same period replaces that period's previous import rather
than doubling it, so a corrected sheet can just be uploaded again. Worth
checking after an import: each month's total in the app should equal its
sheet's own `TOTAL EXPENSES` cell.

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

Log a week of real expenses through the app, then look at Budget at the end
of it. Whichever number you don't trust is the
next thing to fix.
