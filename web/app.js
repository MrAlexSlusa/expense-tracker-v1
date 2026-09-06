// The app behind the login is rendered from one state object in a single
// pass, the way the design prototype is: any change - adding an expense,
// deleting one, switching period - updates state, refetches, and re-renders
// every total, chart, donut segment and progress bar together, so nothing on
// screen can disagree with anything else.
//
// Translation strings and t()/setLang() come from i18n.js, loaded first.

const TOKEN_KEY = "expense_tracker_token";
const SETTINGS_KEY = "expense_tracker_settings";
// "Save my login info": whether the session survives closing the browser, and
// the email to prefill next time. Both live in localStorage even when the
// answer is "no" - the preference itself has to outlive the session it turns off.
const REMEMBER_KEY = "expense_tracker_remember";
const REMEMBERED_EMAIL_KEY = "expense_tracker_remembered_email";

const CURRENCIES = [
  ["USD", "$"], ["EUR", "€"], ["GBP", "£"], ["RON", "lei"], ["JPY", "¥"],
  ["AED", "AED"], ["CHF", "Fr"], ["CAD", "$"], ["AUD", "$"], ["CNY", "¥"], ["INR", "₹"],
  ["BRL", "R$"], ["MXN", "$"], ["SEK", "kr"], ["NOK", "kr"], ["PLN", "zł"], ["TRY", "₺"],
];

// Most of the list above is written symbol-first ("$9"), but a few are
// written after the amount in their own convention - "9 lei", never "lei9".
const SUFFIX_CURRENCIES = new Set(["RON"]);

// The currencies you can log an expense in, whatever your account default is.
// Kept to the ones BNR quotes daily and people here actually hold - the point
// is a fast tap while adding, not a second full currency list.
const ENTRY_CURRENCIES = ["RON", "EUR", "USD", "GBP"];

// Crypto has no place in the entry picker (you don't buy groceries in ETH),
// but the rates page shows it, so it needs symbols of its own.
const RATE_SYMBOLS = { EUR: "€", USD: "$", GBP: "£", BTC: "₿", ETH: "Ξ", RON: "lei" };
const RATE_NAMES = { EUR: "Euro", USD: "US Dollar", GBP: "British Pound", BTC: "Bitcoin", ETH: "Ethereum" };

const LANGUAGES = [["en", "English"], ["es", "Español"], ["fr", "Français"], ["ro", "Română"]];

// The eight category colours from the design, keyed by the names the
// onboarding quiz can produce. Anything else falls back to the same palette
// picked by a hash of the name, so a category's colour is stable across
// reloads without needing a column in the database for it.
const PALETTE = ["#4353ff", "#f2295b", "#2f6bff", "#f5c542", "#ff4f8b", "#8b5cf6", "#ff8a3d", "#22c8c8"];
const CATEGORY_COLORS = {
  housing: "#4353ff", rent: "#4353ff", "rent & utilities": "#4353ff",
  groceries: "#f2295b",
  food: "#2f6bff", "dining out": "#2f6bff", "coffee & snacks": "#2f6bff",
  utilities: "#f5c542", "family & kids": "#f5c542", education: "#f5c542",
  shopping: "#ff4f8b", "gadgets & tech": "#ff4f8b",
  transport: "#8b5cf6", transportation: "#8b5cf6", travel: "#8b5cf6",
  health: "#ff8a3d", "fitness & health": "#ff8a3d", pets: "#ff8a3d",
  entertainment: "#22c8c8", subscriptions: "#22c8c8", "nightlife & fun": "#22c8c8",
  "savings & investing": "#32d583", "gifts & donations": "#32d583",
};

// A previous iteration of this app stored shape names in Category.icon
// instead of emoji. Those rows still exist, so they get an emoji picked from
// the category's name rather than rendering the literal word "square".
const LEGACY_SHAPE_ICONS = ["square", "circle", "diamond", "bar", "dashed"];
const EMOJI_BY_KEYWORD = [
  [["hous", "rent", "home", "chirie"], "🏠"],
  [["grocer", "supermarket", "market"], "🛒"],
  [["food", "dining", "restaurant", "lunch", "dinner"], "🍽️"],
  [["coffee", "cafe", "snack"], "☕"],
  [["util", "electric", "water", "internet"], "💡"],
  [["shop", "clothes"], "🛍️"],
  [["transport", "metro", "bus", "car", "fuel"], "🚇"],
  [["health", "pharm", "medic", "fitness", "gym"], "💊"],
  [["entertain", "movie", "cinema", "fun", "night"], "🎬"],
  [["subscription", "netflix", "stream"], "📺"],
  [["travel", "flight", "trip"], "✈️"],
  [["saving", "invest"], "💹"],
  [["gift", "donation"], "🎁"],
  [["pet", "dog", "cat"], "🐶"],
  [["education", "school", "course", "book"], "📚"],
  [["family", "kid", "child", "baby"], "👶"],
  [["tech", "gadget", "laptop"], "💻"],
];
const EMOJI_CHOICES = [
  "🏠", "🛒", "🍽️", "☕", "💡", "🛍️",
  "🚇", "⛽", "💊", "🏋️", "🎬", "📺",
  "✈️", "💹", "🎁", "🐶", "📚", "👶",
  "💻", "🏦", "💳", "💵", "💰",
];
const ACCOUNT_EMOJI_CHOICES = ["🏦", "💳", "💵", "💰", "📱", "🪙"];

const GOAL_COLORS = { Wants: "#f5c542", Needs: "#4353ff", Savings: "#32d583" };
const OVER_BUDGET_COLOR = "#f2295b";
const RING_DIM = "#2b3350";
const DONUT_RADIUS = 118;
const DONUT_CIRCUMFERENCE = 2 * Math.PI * DONUT_RADIUS;
const CHART_HEIGHT = 184;
const CHART_BASE = 26; // px from the block's bottom to the zero line

const PERIODS = ["Daily", "Weekly", "Monthly", "Yearly", "Last 12 months"];
const TAB_DEFS = [
  ["activity", "tabActivity", "M7 3h10a1 1 0 011 1v16l-3-2-3 2-3-2-3 2V4a1 1 0 011-1zM9 8h6M9 12h6"],
  ["summary", "tabSummary", "M12 3a9 9 0 109 9h-9V3z"],
  ["budget", "tabBudget", "M3 8a2 2 0 012-2h14a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V8zm13 4h3M3 10h18"],
  ["analytics", "tabAnalytics", "M5 20V10M12 20V4M19 20v-7"],
  ["accounts", "tabAccounts", "M3 10l9-6 9 6M5 10v9h14v-9M9 19v-5h6v5"],
];

// --- state ---------------------------------------------------------------

const state = {
  view: "activity",
  period: "Monthly",
  // Analytics keeps its own period, and starts with none: no preselected
  // window, just everything logged so far. The other tabs are month-shaped
  // by nature; Analytics is the one that's meant to look across all of it.
  analyticsPeriod: null,
  anchor: new Date(), // the day/week/month/year the chosen period is centred on
  kind: "Expenses",
  selCat: null, // category id driving the detail ring
  sheet: null,
  searchOpen: false,
  q: "",
  amount: "", // keypad buffer
  addCatId: null,
  addCurrency: null, // null = the account's own currency; otherwise an ENTRY_CURRENCIES code
  convAmount: "", // the rates page's converter
  convFrom: "EUR",
  convTo: "RON",
  txId: null,
  editingCategoryId: null,
  editingAccountId: null,
  busy: false,
  error: "",
};

const data = {
  me: null,
  stats: null,
  categories: [],
  expenses: [],
  income: [],
  goals: [],
  accounts: [],
  prevTotal: null, // same-length previous range, for the "x% from ..." delta
  analyticsBuckets: null, // lazily loaded, only the Analytics tab needs it
  analyticsExpenses: null, // the rows behind those buckets, for Analytics' own list
  rates: null, // the exchange-rates page payload, loaded only when that page is opened
};

let currentCurrency = "USD";

// --- small helpers -------------------------------------------------------

function esc(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function currencySymbol(code) {
  const found = CURRENCIES.find(([c]) => c === code);
  return found ? found[1] : code;
}

// Puts the currency on whichever side it belongs on for the active currency,
// so every amount on screen - totals, keypad, targets - agrees.
function withCurrency(text, code = currentCurrency) {
  const symbol = currencySymbol(code);
  return SUFFIX_CURRENCIES.has(code) ? `${text} ${symbol}` : symbol + text;
}

// Whole amounts lose the ".00" so the design's big numerals read as designed;
// anything with cents keeps them rather than silently rounding real money.
function fmt(amount) {
  const n = Number(amount) || 0;
  const decimals = Math.abs(n % 1) < 0.005 ? 0 : 2;
  return withCurrency(n.toLocaleString(localeForLang(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }));
}

// Puts a symbol on a string that is not a finished number - the keypad buffer,
// where "12." has to stay "12." while you are still typing it.
function withCurrencyIn(text, code) {
  const symbol = RATE_SYMBOLS[code] || currencySymbol(code);
  return SUFFIX_CURRENCIES.has(code) ? `${text} ${symbol}` : symbol + text;
}

// Same shape as fmt(), but for a currency that isn't the account's - used
// wherever an expense shows what was actually paid next to what it converted to.
function fmtIn(amount, code) {
  const n = Number(amount) || 0;
  const decimals = Math.abs(n % 1) < 0.005 ? 0 : 2;
  return withCurrencyIn(
    n.toLocaleString(localeForLang(), { minimumFractionDigits: decimals, maximumFractionDigits: decimals }),
    code,
  );
}

// The currency an expense is being entered in right now: the picked one, or
// the account's own when nothing has been picked.
function entryCurrency() {
  return state.addCurrency || currentCurrency;
}

function fmtK(n) {
  return (n / 1000).toFixed(1).replace(/\.0$/, "") + "k";
}

function tintOf(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return `rgba(${r},${g},${b},.16)`;
}

function preferredColor(category) {
  const named = CATEGORY_COLORS[(category.name || "").trim().toLowerCase()];
  if (named) return named;
  let hash = 0;
  for (const ch of category.name || "") hash = (hash * 31 + ch.charCodeAt(0)) % 100000;
  return PALETTE[hash % PALETTE.length];
}

// Two categories sharing a colour makes the donut unreadable, so a colour is
// only handed out once: each category takes the one its name asks for if it's
// still free, otherwise the next unused palette entry. Assignment walks the
// categories in id order so a category keeps its colour as spend changes the
// order they're displayed in.
function assignColors(categories) {
  const taken = new Set();
  const colors = new Map();

  [...categories].sort((a, b) => a.id - b.id).forEach((c) => {
    const wanted = preferredColor(c);
    let color = taken.has(wanted) ? PALETTE.find((p) => !taken.has(p)) : wanted;
    if (!color) color = PALETTE[colors.size % PALETTE.length]; // more categories than colours
    taken.add(color);
    colors.set(c.id, color);
  });
  return colors;
}

function emojiForCategory(category) {
  const icon = (category.icon || "").trim();
  if (icon && !LEGACY_SHAPE_ICONS.includes(icon)) return icon;
  const name = (category.name || "").toLowerCase();
  const match = EMOJI_BY_KEYWORD.find(([keywords]) => keywords.some((k) => name.includes(k)));
  return match ? match[1] : "💰";
}

function pad2(n) {
  return String(n).padStart(2, "0");
}

function isoDate(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

function periodOf(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

// Dates arrive as "YYYY-MM-DD"; parsing them with the Date constructor would
// read them as UTC and shift the day backwards west of Greenwich.
function parseDate(iso) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function addMonths(date, delta) {
  const d = new Date(date.getFullYear(), date.getMonth() + delta, 1);
  return d;
}

function daysBetween(a, b) {
  return Math.round((b - a) / 86400000) + 1;
}

// The token lands in localStorage when "save my login info" is on (survives
// closing the browser) and sessionStorage when it's off (dies with the tab).
// Reads check both, so flipping the switch never strands a live session in a
// store nothing looks at. Default is on, which is what this app always did.
function rememberMe() { return localStorage.getItem(REMEMBER_KEY) !== "0"; }

function setRememberMe(on) {
  localStorage.setItem(REMEMBER_KEY, on ? "1" : "0");
  const token = getToken();
  clearToken();
  if (token) setToken(token);  // re-home the current session into the right store
  if (!on) localStorage.removeItem(REMEMBERED_EMAIL_KEY);
}

function getToken() { return localStorage.getItem(TOKEN_KEY) || sessionStorage.getItem(TOKEN_KEY); }

function setToken(value) {
  clearToken();
  (rememberMe() ? localStorage : sessionStorage).setItem(TOKEN_KEY, value);
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(TOKEN_KEY);
}

function rememberedEmail() { return rememberMe() ? localStorage.getItem(REMEMBERED_EMAIL_KEY) || "" : ""; }

function rememberEmail(email) {
  if (rememberMe()) localStorage.setItem(REMEMBERED_EMAIL_KEY, email);
}

// --- the selected range --------------------------------------------------

// Every read endpoint takes either a "YYYY-MM" period or an explicit
// start/end pair, so the period sheet's ranges that aren't a calendar month
// (a week, a year, the trailing twelve months) all resolve to a pair here.
function rangeFor(period, anchor) {
  const y = anchor.getFullYear();
  const m = anchor.getMonth();
  const d = anchor.getDate();

  if (period === "Daily") {
    const day = new Date(y, m, d);
    return { start: day, end: day, prevOffsetDays: 1 };
  }
  if (period === "Weekly") {
    const weekday = (anchor.getDay() + 6) % 7; // Monday-first
    const start = new Date(y, m, d - weekday);
    const end = new Date(y, m, d - weekday + 6);
    return { start, end, prevOffsetDays: 7 };
  }
  if (period === "Yearly") {
    return { start: new Date(y, 0, 1), end: new Date(y, 11, 31), prevMonths: 12 };
  }
  if (period === "Last 12 months") {
    return { start: new Date(y, m - 11, 1), end: new Date(y, m + 1, 0), prevMonths: 12 };
  }
  return { start: new Date(y, m, 1), end: new Date(y, m + 1, 0), prevMonths: 1 };
}

function previousRange(range) {
  if (range.prevMonths) {
    return {
      start: addMonths(range.start, -range.prevMonths),
      end: new Date(range.end.getFullYear(), range.end.getMonth() - range.prevMonths + 1, 0),
    };
  }
  const days = range.prevOffsetDays;
  return {
    start: new Date(range.start.getFullYear(), range.start.getMonth(), range.start.getDate() - days),
    end: new Date(range.end.getFullYear(), range.end.getMonth(), range.end.getDate() - days),
  };
}

function rangeQuery(range) {
  return `start=${isoDate(range.start)}&end=${isoDate(range.end)}`;
}

function monthName(date, style) {
  return date.toLocaleDateString(localeForLang(), { month: style || "long" });
}

function rangeLabel(period, range) {
  if (period === "Daily") {
    return range.start.toLocaleDateString(localeForLang(), { day: "numeric", month: "short" });
  }
  if (period === "Weekly") {
    const from = range.start.toLocaleDateString(localeForLang(), { day: "numeric" });
    const to = range.end.toLocaleDateString(localeForLang(), { day: "numeric", month: "short" });
    return `${from}–${to}`;
  }
  if (period === "Yearly") return String(range.start.getFullYear());
  if (period === "Last 12 months") return t("last12Months");
  return monthName(range.start);
}

function previousLabel(period, prev) {
  if (period === "Daily" || period === "Weekly") {
    return prev.start.toLocaleDateString(localeForLang(), { day: "numeric", month: "short" });
  }
  if (period === "Yearly") return String(prev.start.getFullYear());
  if (period === "Last 12 months") return t("thePrior12Months");
  return monthName(prev.start, "short");
}

function currentRange() {
  return rangeFor(state.period, state.anchor);
}

// No period chosen on Analytics means no lower bound at all. The upper bound
// is the end of the current month so a range query is still well-formed.
function analyticsRange() {
  if (state.analyticsPeriod) return rangeFor(state.analyticsPeriod, state.anchor);
  const today = new Date();
  return { start: new Date(1970, 0, 1), end: new Date(today.getFullYear(), today.getMonth() + 1, 0) };
}

// --- API -----------------------------------------------------------------

// Render's free tier spins the backend down after inactivity; the request
// that wakes it back up can take 30-60s and often drops instead of resolving,
// which surfaces to fetch() as a generic network error. Retrying with backoff
// rides that out instead of failing the first thing the user does.
async function fetchWithWakeupRetry(url, options, attempts = 4) {
  for (let i = 0; i < attempts; i++) {
    try {
      return await fetch(url, options);
    } catch (err) {
      if (i === attempts - 1) throw err;
      await new Promise((r) => setTimeout(r, 1500 * (i + 1)));
    }
  }
}

async function apiFetch(path, options = {}) {
  // Endpoints that re-check a password (deleting the account) answer 401 for a
  // wrong password, not a dead session. Without this they'd trip the logout
  // below and throw the user out for a typo.
  const { credentialCheck = false, ...fetchOptions } = options;
  options = fetchOptions;
  const token = getToken();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res;
  try {
    res = await fetchWithWakeupRetry(window.API_BASE_URL + path, { ...options, headers });
  } catch {
    throw new Error(t("errServerWakingUp"));
  }
  if (res.status === 401 && token && !credentialCheck) {
    // Only an authenticated request's 401 means the session is dead - public
    // endpoints like OTP verification also 401 on a plain wrong code, and so
    // does a re-checked password, neither of which is a reason to log anyone out.
    clearToken();
    showAuthScreen();
    throw new Error(t("errSessionExpired"));
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ? translateError(body.detail) : t("errGeneric"));
  }
  return res.status === 204 ? null : res.json();
}

// --- local settings (theme + language) -----------------------------------

function loadSettings() {
  try {
    return { theme: "dark", lang: "en", ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") };
  } catch {
    return { theme: "dark", lang: "en" };
  }
}

function saveSettings(settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function resolvedTheme(settings) {
  if (settings.theme !== "system") return settings.theme;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

function applySettings(settings) {
  const theme = resolvedTheme(settings);
  document.documentElement.dataset.theme = theme;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", theme === "light" ? "#f4f5fa" : "#05070f");
  setLang(settings.lang);
  applyStaticI18n();
}

let settings = loadSettings();

// --- derived views over the loaded data ----------------------------------

function decoratedCategories() {
  const colors = assignColors(data.categories);
  return data.categories
    .map((c) => ({
      ...c,
      color: colors.get(c.id),
      emoji: emojiForCategory(c),
      count: data.expenses.filter((e) => e.category_id === c.id).length,
    }))
    .sort((a, b) => b.total - a.total);
}

function rangeTotal() {
  return data.expenses.reduce((sum, e) => sum + e.amount, 0);
}

function incomeTotal() {
  return data.income.reduce((sum, i) => sum + i.amount, 0);
}

function deltaInfo() {
  const previous = data.prevTotal;
  if (previous == null || previous <= 0) return null;
  const current = rangeTotal();
  const pct = ((current - previous) / previous) * 100;
  if (Math.abs(pct) < 0.5) return null;
  return {
    up: pct > 0,
    label: `${Math.abs(Math.round(pct))}% ${t("fromPeriod", { period: previousLabel(state.period, previousRange(currentRange())) })}`,
  };
}

function donutSegments(dimExceptId) {
  const cats = decoratedCategories().filter((c) => c.total > 0);
  const total = cats.reduce((sum, c) => sum + c.total, 0) || 1;
  let travelled = 0;
  return cats.map((c) => {
    const share = c.total / total;
    const length = Math.max(share * DONUT_CIRCUMFERENCE - 5, 2);
    const offset = -travelled;
    travelled += share * DONUT_CIRCUMFERENCE;
    return {
      color: dimExceptId == null ? c.color : c.id === dimExceptId ? c.color : RING_DIM,
      dash: `${length.toFixed(1)} ${(DONUT_CIRCUMFERENCE - length).toFixed(1)}`,
      offset: offset.toFixed(1),
    };
  });
}

function dayLabel(iso) {
  const date = parseDate(iso);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const diff = Math.round((today - date) / 86400000);
  if (diff === 0) return t("today");
  if (diff === 1) return t("yesterday");
  return date.toLocaleDateString(localeForLang(), { weekday: "long", day: "numeric", month: "short" });
}

function matchesQuery(expense) {
  const q = state.q.trim().toLowerCase();
  if (!q) return true;
  return (expense.note || "").toLowerCase().includes(q)
    || (expense.category_name || "").toLowerCase().includes(q);
}

// Day headers and transactions end up in one flat list of rows: the grouping
// is presentational, so each row just carries its own corner radius and
// divider rather than being nested in a per-day wrapper.
function visibleExpenses() {
  return state.view === "analytics" && data.analyticsExpenses ? data.analyticsExpenses : data.expenses;
}

function transactionRows() {
  const visible = visibleExpenses().filter(matchesQuery);
  const byDay = new Map();
  visible.forEach((e) => {
    if (!byDay.has(e.date)) byDay.set(e.date, []);
    byDay.get(e.date).push(e);
  });

  const days = [...byDay.keys()].sort().reverse();
  const rows = [];
  days.forEach((day, dayIndex) => {
    const items = byDay.get(day);
    rows.push({
      kind: "header",
      first: dayIndex === 0,
      label: dayLabel(day),
      total: fmt(items.reduce((sum, e) => sum + e.amount, 0)),
    });
    items.forEach((expense, i) => {
      rows.push({
        kind: "tx",
        expense,
        radius: items.length === 1 ? "r-single" : i === 0 ? "r-first" : i === items.length - 1 ? "r-last" : "r-mid",
        divider: i > 0,
      });
    });
  });
  return rows;
}

function incomeRows() {
  return data.income
    .filter((i) => !state.q.trim() || i.name.toLowerCase().includes(state.q.trim().toLowerCase()))
    .map((i, index, all) => ({
      income: i,
      radius: all.length === 1 ? "r-single" : index === 0 ? "r-first" : index === all.length - 1 ? "r-last" : "r-mid",
      divider: index > 0,
    }));
}

// One bar per day while the range is short enough to read; longer ranges
// (a year, the trailing twelve months) bucket by month instead, so the block
// never tries to draw 365 three-pixel bars.
function seriesFor(range, expenses) {
  const span = daysBetween(range.start, range.end);
  const byMonth = span > 62;

  const buckets = [];
  if (byMonth) {
    let cursor = new Date(range.start.getFullYear(), range.start.getMonth(), 1);
    while (cursor <= range.end) {
      buckets.push({ key: periodOf(cursor), label: monthName(cursor, "short"), value: 0 });
      cursor = addMonths(cursor, 1);
    }
  } else {
    for (let i = 0; i < span; i++) {
      const day = new Date(range.start.getFullYear(), range.start.getMonth(), range.start.getDate() + i);
      buckets.push({ key: isoDate(day), label: String(day.getDate()), value: 0 });
    }
  }

  const index = new Map(buckets.map((b, i) => [b.key, i]));
  expenses.forEach((e) => {
    const key = byMonth ? e.date.slice(0, 7) : e.date;
    if (index.has(key)) buckets[index.get(key)].value += e.amount;
  });

  return { buckets, byMonth };
}

function spendSeries() {
  return seriesFor(currentRange(), data.expenses);
}

// Five evenly spaced labels along the x axis, matching the design's 1/9/16/24/31.
function axisLabels(buckets) {
  if (buckets.length <= 6) return buckets.map((b) => b.label);
  const wanted = 5;
  const step = (buckets.length - 1) / (wanted - 1);
  return Array.from({ length: wanted }, (_, i) => buckets[Math.round(i * step)].label);
}

function chartBlock(series, opts) {
  const values = series.buckets.map((b) => b.value);
  const max = Math.max(...values, 1);
  const scaleMax = opts.roundScale ? Math.max(Math.ceil((max * 1.13) / 500) * 500, 500) : max;
  const total = values.reduce((a, b) => a + b, 0);
  const average = values.length ? total / values.length : 0;
  const avgY = CHART_BASE + (average / scaleMax) * CHART_HEIGHT;
  const format = opts.k ? fmtK : (n) => Math.round(n).toLocaleString(localeForLang());

  const bars = series.buckets
    .map((b) => `<div class="chart-bar" style="height:${((b.value / scaleMax) * 100).toFixed(1)}%"></div>`)
    .join("");
  const labels = axisLabels(series.buckets).map((l) => `<span>${esc(l)}</span>`).join("");

  return `
    <div class="chart ${opts.months ? "chart-months" : ""}">
      <div class="chart-axis-top">${esc(format(scaleMax))}</div>
      ${avgY - CHART_BASE > 16 ? '<div class="chart-axis-zero">0</div>' : ""}
      <div class="chart-avg-line" style="bottom:${avgY.toFixed(0)}px"></div>
      <div class="chart-axis-avg" style="bottom:${(avgY - 9).toFixed(0)}px">${esc(format(average))}</div>
      <div class="chart-bars">${bars}</div>
      <div class="chart-labels">${labels}</div>
    </div>`;
}

// --- exchange rates ------------------------------------------------------
// The rates page and the add sheet's live preview read the same payload. The
// backend converts independently when the expense is saved, so this is only
// ever a preview - it can be missing (rates not loaded yet) without blocking
// anything, which is why every caller checks ratesReady() first.

function ratesReady() {
  return !!(data.rates && data.rates.rates && data.rates.rates.length);
}

function ronPerUnit(code) {
  if (code === "RON") return 1;
  const row = (data.rates.rates || []).find((r) => r.currency === code);
  return row ? row.ron : null;
}

function convertWithRates(amount, source, target) {
  const from = ronPerUnit(source);
  const to = ronPerUnit(target);
  if (!from || !to) return null;
  return amount * (from / to);
}

// --- shared view fragments ----------------------------------------------

function deltaHtml(extraClass) {
  const delta = deltaInfo();
  if (!delta) return "";
  return `<div class="delta ${extraClass || ""} ${delta.up ? "is-up" : ""}">
    <span class="delta-arrow">${delta.up ? "↑" : "↓"}</span>${esc(delta.label)}</div>`;
}

function pillsHtml(options) {
  const parts = [];

  if (options.search) {
    parts.push(state.searchOpen
      ? `<div class="search-field"><span></span>
           <input id="search-input" value="${esc(state.q)}" placeholder="${esc(t("searchTransactions"))}" />
           <button data-action="close-search" aria-label="${esc(t("cancel"))}">✕</button>
         </div>`
      : `<button class="pill pill-icon" data-action="open-search" aria-label="${esc(t("search"))}"><span></span></button>`);
  }

  parts.push(`<button class="pill" data-action="toggle-kind">${esc(t(state.kind === "Income" ? "income" : "expenses"))}</button>`);

  if (options.fixedPeriodLabel) {
    // A period that can be cleared back off carries the ✕; the unfiltered
    // default (Analytics' "All time") is just a plain pill with nothing to clear.
    parts.push(`<button class="pill pill-outline" data-action="open-period">${esc(options.fixedPeriodLabel)}
      <span class="pill-outline-x" data-action="clear-period">✕</span></button>`);
  } else {
    parts.push(`<button class="pill" data-action="open-period">${esc(options.periodLabel || t(periodKey(state.period)))}</button>`);
  }

  parts.push(`<button class="pill" data-action="go-accounts">${esc(t("allAccounts"))}</button>`);

  if (options.activeCategory) {
    parts.push(`<button class="pill pill-active" data-action="clear-category">${esc(options.activeCategory)}
      <span class="pill-active-x">✕</span></button>`);
  } else if (options.categories) {
    parts.push(`<button class="pill" data-action="go-summary">${esc(t("allCategories"))}</button>`);
  }

  return `<div class="pill-row ${options.tight ? "pill-row-tight" : ""}">${parts.join("")}</div>`;
}

function periodKey(period) {
  return {
    Daily: "periodDaily",
    Weekly: "periodWeekly",
    Monthly: "periodMonthly",
    Yearly: "periodYearly",
    "Last 12 months": "last12Months",
  }[period];
}

function txRowHtml(row) {
  const e = row.expense;
  const category = data.categories.find((c) => c.id === e.category_id);
  const emoji = category ? emojiForCategory(category) : "💰";
  // A converted expense shows what was actually paid under the note - the
  // headline stays in the account's currency so the column still adds up.
  const paid = e.original_currency
    ? `<span class="tx-sub">${esc(t("paidIn", { amount: fmtIn(e.original_amount, e.original_currency) }))}</span>`
    : "";
  return `<button class="tx-row ${row.radius} ${row.divider ? "has-divider" : ""}" data-action="open-tx" data-id="${e.id}">
      <span class="tile">${esc(emoji)}</span>
      <span class="tx-name">${esc(e.note || (e.category_name || t("expense")))}${paid}</span>
      <span class="tx-amount">${esc(fmt(e.amount))}</span>
    </button>`;
}

function transactionListHtml() {
  if (state.kind === "Income") {
    const rows = incomeRows();
    if (!rows.length) {
      return `<div class="list-region"><p class="empty-note">${esc(t("noIncomeYet"))}</p></div>`;
    }
    return `<div class="list-region"><div style="margin-top:18px"></div>${rows.map((row) => `
      <button class="tx-row ${row.radius} ${row.divider ? "has-divider" : ""}" data-action="open-income" data-id="${row.income.id}">
        <span class="tile">💵</span>
        <span class="tx-name">${esc(row.income.name)}</span>
        <span class="tx-amount">${esc(fmt(row.income.amount))}</span>
      </button>`).join("")}</div>`;
  }

  const rows = transactionRows();
  if (!rows.length) {
    const message = state.q.trim() ? t("noMatches", { query: state.q.trim() }) : t("noExpensesInPeriod");
    return `<div class="list-region"><p class="empty-note">${esc(message)}</p></div>`;
  }

  const html = rows.map((row) => (row.kind === "header"
    ? `<div class="day-header ${row.first ? "is-first" : ""}"><span>${esc(row.label)}</span><span>${esc(row.total)}</span></div>`
    : txRowHtml(row))).join("");
  return `<div class="list-region">${html}</div>`;
}

// --- the six screens -----------------------------------------------------

function activityView() {
  const total = state.kind === "Income" ? incomeTotal() : rangeTotal();
  return `
    <div class="view">
      <div class="hero">
        <button class="hero-period-btn" data-action="open-period">${esc(rangeLabel(state.period, currentRange()))} ⌄</button>
        <div class="hero-amount">${esc(fmt(total))}</div>
        ${state.kind === "Income" ? "" : deltaHtml()}
      </div>
      ${state.kind === "Income" ? "" : chartBlock(spendSeries(), { roundScale: false })}
      ${pillsHtml({ search: true, categories: true })}
      ${transactionListHtml()}
    </div>`;
}

function donutHtml(dimExceptId) {
  const segments = donutSegments(dimExceptId).map((s) => `
    <circle cx="136" cy="136" r="${DONUT_RADIUS}" fill="none" stroke-width="19" stroke-linecap="butt"
      stroke="${esc(s.color)}" stroke-dasharray="${esc(s.dash)}" stroke-dashoffset="${esc(s.offset)}"></circle>`).join("");
  return `<svg width="272" height="272" viewBox="0 0 272 272" aria-hidden="true">${segments}</svg>`;
}

function summaryView() {
  const cats = decoratedCategories().filter((c) => c.total > 0);
  const total = rangeTotal();
  const rows = cats.map((c) => `
    <button class="card-row" data-action="open-category" data-id="${c.id}">
      <span class="tile tile-cat" style="--cat:${esc(c.color)};--tint:${esc(tintOf(c.color))}">${esc(c.emoji)}</span>
      <span class="cat-name-wrap">
        <span class="cat-name">${esc(c.name)}</span>
        <span class="cat-count">${c.count}</span>
      </span>
      <span class="cat-right">
        <span class="cat-amount">${esc(fmt(c.total))}</span>
        <span class="cat-pct">${total ? ((c.total / total) * 100).toFixed(2) : "0.00"}%</span>
      </span>
    </button>`).join("");

  return `
    <div class="view">
      <div class="donut-wrap">
        ${donutHtml(null)}
        <div class="donut-center">
          <button class="hero-period-btn" data-action="open-period">${esc(rangeLabel(state.period, currentRange()))} ⌄</button>
          <div class="hero-amount-sm">${esc(fmt(total))}</div>
          ${deltaHtml("delta-sm")}
        </div>
      </div>
      ${pillsHtml({ categories: true, tight: true })}
      <div class="list-region" style="padding-top:14px">
        ${cats.length ? `<div class="card">${rows}</div>` : `<p class="empty-note">${esc(t("noExpensesInPeriod"))}</p>`}
      </div>
    </div>`;
}

function detailView() {
  const category = decoratedCategories().find((c) => c.id === state.selCat);
  if (!category) return summaryView();

  const expenses = data.expenses.filter((e) => e.category_id === category.id);
  const rows = expenses.map((e, i) => `
    <button class="card-row" data-action="open-tx" data-id="${e.id}" style="padding:13px 14px">
      <span class="tile">${esc(category.emoji)}</span>
      <span class="tx-name">${esc(e.note || category.name)}
        <span class="tx-sub">${esc(parseDate(e.date).toLocaleDateString(localeForLang(), { weekday: "short", day: "numeric", month: "short" }))}</span>
      </span>
      <span class="tx-amount">${esc(fmt(e.amount))}</span>
    </button>`).join("");

  return `
    <div class="view">
      <button class="back-pill" data-action="clear-category">← ${esc(t("back"))}</button>
      <div class="donut-wrap donut-wrap-detail">
        ${donutHtml(category.id)}
        <div class="donut-center">
          <div style="color:var(--text-muted);font-size:15px">${esc(category.name)}</div>
          <div class="hero-amount-sm">${esc(fmt(category.total))}</div>
          ${category.target ? `<div class="hero-caption">${esc(t("ofTarget", { target: fmt(category.target) }))}</div>` : ""}
        </div>
      </div>
      ${pillsHtml({ activeCategory: category.name })}
      <div class="list-region" style="padding-top:14px">
        ${expenses.length ? `<div class="card">${rows}</div>` : `<p class="empty-note">${esc(t("noExpensesInPeriod"))}</p>`}
      </div>
    </div>`;
}

function budgetView() {
  const cats = decoratedCategories();
  const total = rangeTotal();
  const planned = data.categories.reduce((sum, c) => sum + (c.target || 0), 0);
  const range = currentRange();
  const span = daysBetween(range.start, range.end);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const elapsed = Math.min(Math.max(daysBetween(range.start, today), 1), span);

  const goals = ["Wants", "Needs", "Savings"].map((tag) => {
    const goal = data.goals.find((g) => g.tag === tag) || { target_pct: 0, actual_pct: 0 };
    return `
      <div>
        <div class="goal-head">
          <span>${esc(t(tag.toLowerCase()))}</span>
          <span>${esc(t("ofTargetPct", { actual: Math.round(goal.actual_pct), target: Math.round(goal.target_pct) }))}</span>
        </div>
        <div class="track"><i style="width:${Math.min(goal.actual_pct, 100).toFixed(1)}%;background:${GOAL_COLORS[tag]}"></i></div>
      </div>`;
  }).join("");

  const rows = cats.map((c) => {
    const target = c.target || 0;
    const over = target > 0 && c.total > target;
    const width = target > 0 ? Math.min((c.total / target) * 100, 100) : 0;
    return `
      <div class="budget-row">
        <div class="budget-row-head">
          <span class="tile tile-cat" style="--cat:${esc(c.color)};--tint:${esc(tintOf(c.color))};width:34px;height:34px;border-radius:10px;font-size:16px">${esc(c.emoji)}</span>
          <span class="budget-row-name">${esc(c.name)}</span>
          <span class="budget-row-nums">${esc(fmt(c.total))} / ${esc(target ? fmt(target) : t("noLimit"))}</span>
        </div>
        <div class="track track-sm"><i style="width:${width.toFixed(1)}%;background:${over ? OVER_BUDGET_COLOR : c.color}"></i></div>
      </div>`;
  }).join("");

  return `
    <div class="view budget-view">
      <div class="budget-hero">
        <button class="hero-period-btn" data-action="open-period">${esc(rangeLabel(state.period, range))} ⌄</button>
        <div class="hero-amount-sm">${esc(fmt(total))}</div>
        <div class="hero-caption">${esc(t("plannedAndDay", { planned: fmt(planned), day: elapsed, days: span }))}</div>
      </div>

      <div class="goal-card">
        <span class="caption">${esc(t("goalSplit"))}</span>
        <div class="goal-list">${goals}</div>
      </div>

      ${cats.length ? `<div class="card">${rows}</div>` : `<p class="empty-note">${esc(t("noCategoriesYet"))}</p>`}
    </div>`;
}

function analyticsView() {
  if (!data.analyticsBuckets) {
    return `<div class="view"><p class="empty-note">${esc(t("loading"))}</p></div>`;
  }
  const series = data.analyticsBuckets;
  const total = series.buckets.reduce((sum, b) => sum + b.value, 0);
  const label = state.analyticsPeriod ? t(periodKey(state.analyticsPeriod)) : t("allTime");

  return `
    <div class="view">
      <div class="hero">
        <div style="color:var(--text-muted);font-size:15px">${esc(label)}</div>
        <div class="hero-amount-sm">${esc(fmt(total))}</div>
      </div>
      ${chartBlock(series, { months: series.byMonth, roundScale: true, k: true })}
      ${pillsHtml({ search: true, fixedPeriodLabel: state.analyticsPeriod ? label : null, periodLabel: label })}
      ${transactionListHtml()}
    </div>`;
}

function accountsView() {
  const me = data.me || {};
  const stats = data.stats || {};
  const name = me.display_name || (me.email || "").split("@")[0] || t("you");
  const since = stats.member_since || me.created_at;
  const sinceLabel = since
    ? parseDate(since.slice(0, 10)).toLocaleDateString(localeForLang(), { month: "short", year: "numeric" })
    : "";

  const statCells = [
    [fmt(stats.total_all_time || 0), t("statTotalAllTime")],
    [fmt(stats.total_this_month || 0), t("statThisMonth")],
    [fmt(stats.monthly_average || 0), t("statMonthlyAverage")],
    [stats.top_category || "—", t("statTopCategory")],
    [t("nDays", { n: stats.current_streak_days || 0 }), t("statStreak")],
    [String(stats.linked_accounts || 0), t("statLinkedAccounts")],
  ].map(([value, label]) => `
    <div class="stat-cell">
      <div class="stat-value">${esc(value)}</div>
      <div class="stat-label">${esc(label)}</div>
    </div>`).join("");

  const langName = (LANGUAGES.find(([code]) => code === settings.lang) || LANGUAGES[0])[1];
  const settingsRows = [
    ["open-currency", t("currency"), me.currency || "USD"],
    ["open-language", t("language"), langName],
    ["open-timezone", t("timeZone"), me.timezone || t("timeZoneUtc")],
    ["open-theme", t("theme"), t(settings.theme)],
    ["open-twofactor", t("twoFactor"), t(me.two_factor_enabled ? "on" : "off")],
    ["open-categories", t("categories"), String(data.categories.length)],
    ["open-income", t("income"), periodOf(currentRange().start)],
    ["open-import", t("importSpreadsheet"), ".xlsx / .csv"],
    ["open-whatsapp", t("whatsappLogging"), me.phone_number || t("notLinked")],
    ["open-rates", t("exchangeRates"), "EUR · USD · GBP · BTC · ETH"],
  ].map(([action, label, value]) => `
    <button class="card-row settings-row" data-action="${action}">
      <span class="settings-row-label">${esc(label)}</span>
      <span class="settings-row-value">${esc(value)}</span>
      <span class="chevron">›</span>
    </button>`).join("");

  const accountRows = data.accounts.map((a) => `
    <button class="card-row account-row" data-action="edit-account" data-id="${a.id}">
      <span class="tile">${esc(a.icon)}</span>
      <span class="tx-name">${esc(a.name)}
        <span class="tx-sub">${esc([a.kind, a.last4 ? `·${a.last4}` : ""].filter(Boolean).join(" "))}</span>
      </span>
      <span class="tx-amount">${esc(fmt(a.balance))}</span>
    </button>`).join("");

  return `
    <div class="view accounts-view">
      <button class="identity" data-action="open-profile">
        <span class="identity-avatar">${me.avatar_url ? `<img src="${esc(me.avatar_url)}" alt="" />` : esc(name.charAt(0).toUpperCase())}</span>
        <span class="identity-lines">
          <span class="identity-name">${esc(name)}</span>
          <span class="identity-email">${esc(me.email || "")}</span>
          ${sinceLabel ? `<span class="identity-since">${esc(t("memberSince", { date: sinceLabel }))}</span>` : ""}
        </span>
      </button>

      <div class="stats-grid">${statCells}</div>

      <span class="caption section-caption">${esc(t("settings"))}</span>
      <div class="card" style="margin-bottom:18px">${settingsRows}</div>

      <span class="caption section-caption">${esc(t("accounts"))}</span>
      <div class="card" style="margin-bottom:20px">
        ${accountRows}
        <button class="card-row settings-row" data-action="add-account">
          <span class="settings-row-label" style="color:var(--text-muted)">+ ${esc(t("addAccount"))}</span>
        </button>
      </div>

      <button class="danger-btn" data-action="logout">${esc(t("logout"))}</button>
      <button class="danger-btn danger-btn-quiet" data-action="open-delete-account">${esc(t("deleteAccount"))}</button>
    </div>`;
}

// A page rather than a sheet: five rates, where each came from, and a small
// converter so the numbers are usable rather than just readable. Reached from
// the Accounts tab; it isn't a sixth tab because the tab bar is already full
// and this isn't something you check several times a day.
function ratesView() {
  const rates = data.rates;

  if (!rates) {
    return `
      <div class="view">
        <button class="back-pill" data-action="go-accounts">← ${esc(t("back"))}</button>
        <p class="empty-note">${esc(t("loading"))}</p>
      </div>`;
  }

  if (!rates.rates.length) {
    return `
      <div class="view">
        <button class="back-pill" data-action="go-accounts">← ${esc(t("back"))}</button>
        <p class="empty-note">${esc(t("ratesUnavailable"))}</p>
      </div>`;
  }

  const published = rates.date
    ? parseDate(rates.date).toLocaleDateString(localeForLang(), { day: "numeric", month: "long", year: "numeric" })
    : "";

  const rows = rates.rates.map((r) => {
    // Crypto is worth six figures in lei, so it gets no decimals; a fiat
    // reference rate is meaningless without its four.
    const value = r.kind === "crypto"
      ? Number(r.ron).toLocaleString(localeForLang(), { maximumFractionDigits: 0 })
      : Number(r.ron).toLocaleString(localeForLang(), { minimumFractionDigits: 4, maximumFractionDigits: 4 });

    return `
      <div class="card-row rate-row">
        <span class="tile">${esc(RATE_SYMBOLS[r.currency] || r.currency)}</span>
        <span class="tx-name">${esc(r.currency)}
          <span class="tx-sub">${esc(RATE_NAMES[r.currency] || "")} · ${esc(t(r.source === "bnr" ? "sourceBnr" : "sourceCrypto"))}</span>
        </span>
        <span class="tx-amount">${esc(value)} <span class="rate-unit">${esc(t("lei"))}</span></span>
      </div>`;
  }).join("");

  const options = ["RON", ...rates.rates.map((r) => r.currency)];
  const from = state.convFrom || "EUR";
  const to = state.convTo || "RON";
  const typed = parseFloat(state.convAmount);
  const result = typed && ratesReady() ? convertWithRates(typed, from, to) : null;

  const select = (id, selected) => `<select id="${id}">${options
    .map((c) => `<option value="${esc(c)}"${c === selected ? " selected" : ""}>${esc(c)}</option>`)
    .join("")}</select>`;

  return `
    <div class="view">
      <button class="back-pill" data-action="go-accounts">← ${esc(t("back"))}</button>

      <div class="rates-head">
        <div class="caption">${esc(t("exchangeRates"))}</div>
        <div class="rates-date">${esc(published ? t("bnrRatesFor", { date: published }) : "")}</div>
        ${rates.stale ? `<div class="rates-stale">${esc(t("ratesStale", { days: rates.age_days || 0 }))}</div>` : ""}
      </div>

      <div class="card" style="margin-bottom:20px">${rows}</div>

      <span class="caption section-caption">${esc(t("converter"))}</span>
      <div class="card card-16" style="margin-bottom:18px">
        <div class="conv-row">
          <input id="conv-amount" type="text" inputmode="decimal" value="${esc(state.convAmount || "")}"
            placeholder="0" />
          ${select("conv-from", from)}
          <span class="conv-arrow">→</span>
          ${select("conv-to", to)}
        </div>
        <div class="conv-result">${esc(result == null ? "—" : fmtIn(result, to))}</div>
      </div>

      <p class="rates-note">${esc(t("ratesSourceNote"))}</p>
    </div>`;
}

// --- sheets --------------------------------------------------------------

function sheetShell(inner, opts = {}) {
  return `<div class="sheet-scrim ${opts.add ? "is-add" : ""}" data-action="${opts.persistent ? "" : "close-sheet"}">
      <div class="sheet">
        <div class="grab"></div>
        ${inner}
      </div>
    </div>`;
}

function optionCard(options) {
  return `<div class="card card-16" style="margin-bottom:18px">${options.map((o) => `
    <button class="card-row" data-action="${o.action}" data-value="${esc(o.value)}">
      <span style="flex:1;color:${o.selected ? "var(--text)" : "var(--text-soft)"}">${esc(o.label)}</span>
      <span class="sheet-check">${o.selected ? "✓" : ""}</span>
    </button>`).join("")}</div>`;
}

function periodSheet() {
  // On Analytics the list gains "All time" at the top - that tab's default is
  // no period at all, so it needs a way back to it once one has been picked.
  const analytics = state.view === "analytics";
  const options = analytics
    ? [{ action: "set-period", value: "", label: t("allTime"), selected: !state.analyticsPeriod }]
    : [];
  const active = analytics ? state.analyticsPeriod : state.period;
  options.push(...PERIODS.map((p) => ({
    action: "set-period", value: p, label: t(periodKey(p)), selected: active === p,
  })));

  return sheetShell(`
    <div class="sheet-title">${esc(t("groupByPeriod"))}</div>
    ${optionCard(options)}
    <button class="btn-primary" style="width:100%" data-action="close-sheet">${esc(t("done"))}</button>`);
}

function addSheet() {
  const cats = decoratedCategories();
  const pills = cats.map((c) => {
    const selected = state.addCatId === c.id;
    return `<button class="cat-pill ${selected ? "is-selected" : ""}" data-action="set-add-category" data-id="${c.id}"
      style="--cat:${esc(c.color)};--tint:${esc(tintOf(c.color))}">${esc(c.emoji)} ${esc(c.name)}</button>`;
  }).join("");

  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", ".", "0", "⌫"]
    .map((k) => `<button class="key" data-action="key" data-value="${esc(k)}">${esc(k)}</button>`).join("");

  // The account's own currency always sits first and is always present, even
  // if it isn't one of the four - picking it is how you get back to no
  // conversion at all.
  const codes = [currentCurrency, ...ENTRY_CURRENCIES.filter((c) => c !== currentCurrency)];
  const active = entryCurrency();
  const currencyChips = codes.map((code) => `
    <button class="cur-chip ${code === active ? "is-selected" : ""}" data-action="set-add-currency" data-value="${esc(code)}">
      ${esc(code)}
    </button>`).join("");

  // Converted preview, so you commit to a number rather than discovering it
  // after saving. Rates come from the same snapshot the backend converts with.
  const typed = parseFloat(state.amount);
  const converted = active !== currentCurrency && typed && ratesReady()
    ? `<div class="keypad-converted">≈ ${esc(fmt(convertWithRates(typed, active, currentCurrency)))}</div>`
    : "";

  return sheetShell(`
    <div class="sheet-caption">${esc(t("enterAmount"))}</div>
    <div class="keypad-amount ${state.amount ? "" : "is-empty"}">${esc(withCurrencyIn(state.amount || "0", active))}</div>
    ${converted}
    <div class="cur-chip-row">${currencyChips}</div>
    <div class="cat-pill-row">${pills || `<span class="note">${esc(t("noCategoriesYet"))}</span>`}</div>
    <div class="keypad">${keys}</div>
    <div class="sheet-btn-row" style="margin-top:0">
      <button class="btn-secondary" data-action="close-sheet">${esc(t("cancel"))}</button>
      <button class="btn-primary" data-action="save-expense">${esc(t("done"))}</button>
    </div>
    <p class="error">${esc(state.error)}</p>`, { add: true, persistent: true });
}

function txSheet() {
  const expense = data.expenses.find((e) => e.id === state.txId);
  if (!expense) return "";
  const category = data.categories.find((c) => c.id === expense.category_id);
  const meta = [
    [t("date"), parseDate(expense.date).toLocaleDateString(localeForLang(), { weekday: "short", day: "numeric", month: "short", year: "numeric" })],
    [t("account"), expense.account_name || t("notSet")],
    [t("category"), expense.category_name || t("uncategorized")],
    // The rate is shown as it was on the day, not as it is now - it explains
    // the number stored on this row, which today's rate no longer would.
    ...(expense.original_currency ? [
      [t("paidAmount"), fmtIn(expense.original_amount, expense.original_currency)],
      // A rate keeps four decimals - fmt()'s two would round 5.2524 to 5.25
      // and stop explaining the amount beside it.
      [t("rateUsed"), `1 ${expense.original_currency} = ${withCurrencyIn(
        Number(expense.fx_rate).toLocaleString(localeForLang(), { minimumFractionDigits: 4, maximumFractionDigits: 4 }),
        currentCurrency,
      )}`],
    ] : []),
  ].map(([label, value]) => `<div class="meta-row"><span>${esc(label)}</span><span>${esc(value)}</span></div>`).join("");

  return sheetShell(`
    <div class="tx-sheet-head">
      <span class="tile tile-lg">${esc(category ? emojiForCategory(category) : "💰")}</span>
      <span style="flex:1;min-width:0">
        <div class="tx-sheet-name">${esc(expense.note || expense.category_name || t("expense"))}</div>
        <div class="tx-sheet-cat">${esc(expense.category_name || t("uncategorized"))}</div>
      </span>
      <span class="tx-sheet-amount">${esc(fmt(expense.amount))}</span>
    </div>
    <div class="card card-16">${meta}</div>
    <div class="sheet-btn-row">
      <button class="btn-secondary" style="height:48px;font-size:15.5px" data-action="close-sheet">${esc(t("close"))}</button>
      <button class="btn-danger-soft" data-action="delete-expense" data-id="${expense.id}">${esc(t("delete"))}</button>
    </div>`);
}

function currencySheet() {
  return sheetShell(`
    <div class="sheet-title">${esc(t("currency"))}</div>
    ${optionCard(CURRENCIES.map(([code, symbol]) => ({
      action: "set-currency", value: code, label: `${code}  ${symbol}`,
      selected: (data.me && data.me.currency) === code,
    })))}`);
}

// The browser knows every IANA zone and which one this device is in, so the
// picker is a plain select rather than a hand-kept list that would go stale.
// supportedValuesOf is recent enough to be worth a fallback: without it, the
// detected zone plus a short spread of common ones still lets someone choose.
function knownTimeZones() {
  try {
    const all = Intl.supportedValuesOf("timeZone");
    if (all && all.length) return all;
  } catch {}
  return ["UTC", "Europe/London", "Europe/Bucharest", "Europe/Paris", "Europe/Madrid",
          "America/New_York", "America/Chicago", "America/Los_Angeles", "America/Sao_Paulo",
          "Asia/Dubai", "Asia/Kolkata", "Asia/Tokyo", "Australia/Sydney"];
}

function detectedTimeZone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "";
  } catch {
    return "";
  }
}

function timeZoneSheet() {
  const current = (data.me && data.me.timezone) || "";
  const detected = detectedTimeZone();
  const zones = knownTimeZones();
  // A zone the browser doesn't list (an old name, or a value set elsewhere)
  // still has to appear, or opening the sheet would silently change it.
  const options = zones.includes(current) || !current ? zones : [current, ...zones];

  return sheetShell(`
    <div class="sheet-title">${esc(t("timeZone"))}</div>
    <p class="sheet-hint">${esc(t("timeZoneHint"))}</p>
    ${detected && detected !== current ? `
      <button class="btn-secondary" style="width:100%;margin-bottom:14px"
        data-action="set-timezone" data-value="${esc(detected)}">
        ${esc(t("useDetectedZone", { zone: detected }))}
      </button>` : ""}
    <label class="field"><span>${esc(t("timeZone"))}</span>
      <select id="timezone-select">
        <option value=""${current ? "" : " selected"}>${esc(t("timeZoneUtc"))}</option>
        ${options.map((z) => `<option value="${esc(z)}"${z === current ? " selected" : ""}>${esc(z)}</option>`).join("")}
      </select>
    </label>
    <div class="sheet-btn-row">
      <button class="btn-secondary" data-action="close-sheet">${esc(t("cancel"))}</button>
      <button class="btn-primary" data-action="save-timezone">${esc(t("save"))}</button>
    </div>
    <p class="error">${esc(state.error)}</p>`, { persistent: true });
}

function languageSheet() {
  return sheetShell(`
    <div class="sheet-title">${esc(t("language"))}</div>
    ${optionCard(LANGUAGES.map(([code, label]) => ({
      action: "set-language", value: code, label, selected: settings.lang === code,
    })))}`);
}

function themeSheet() {
  return sheetShell(`
    <div class="sheet-title">${esc(t("theme"))}</div>
    ${optionCard(["dark", "light", "system"].map((value) => ({
      action: "set-theme", value,
      label: t(value),
      selected: settings.theme === value,
    })))}`);
}

function twoFactorSheet() {
  const on = !!(data.me && data.me.two_factor_enabled);
  return sheetShell(`
    <div class="sheet-title">${esc(t("twoFactor"))}</div>
    <p class="sheet-hint">${esc(t("twoFactorHint"))}</p>
    ${optionCard([
      { action: "set-twofactor", value: "on", label: t("on"), selected: on },
      { action: "set-twofactor", value: "off", label: t("off"), selected: !on },
    ])}`);
}

function importSheet() {
  return sheetShell(`
    <div class="sheet-title">${esc(t("importSpreadsheet"))}</div>
    <p class="sheet-hint">${esc(t("importSpreadsheetHint"))}</p>
    <label class="field"><span>${esc(t("file"))}</span>
      <input id="import-file" type="file" accept=".xlsx,.xlsm,.csv,.tsv" />
    </label>
    <label class="field"><span>${esc(t("period"))}</span>
      <input id="import-period" type="month" value="${esc(periodOf(currentRange().start))}" />
    </label>
    <div class="sheet-btn-row">
      <button class="btn-secondary" data-action="close-sheet">${esc(t("cancel"))}</button>
      <button class="btn-primary" data-action="run-import">${esc(t("import"))}</button>
    </div>
    <p class="error">${esc(state.error)}</p>`, { persistent: true });
}

// Deleting is irreversible and clears out more than the button implies, so the
// sheet names what goes and asks for something deliberate: the password on an
// account that has one, and otherwise the word DELETE typed out - a social-only
// account has no password to re-enter, and a bare "are you sure" is too easy to
// tap through by accident.
function deleteAccountSheet() {
  const me = data.me || {};
  const needsPassword = me.has_password !== false;
  const confirmField = needsPassword
    ? `<label class="field"><span>${esc(t("password"))}</span>
         <input id="delete-password" type="password" autocomplete="current-password" />
       </label>`
    : `<label class="field"><span>${esc(t("typeDeleteToConfirm"))}</span>
         <input id="delete-confirm" type="text" autocapitalize="characters" />
       </label>`;

  return sheetShell(`
    <div class="sheet-title">${esc(t("deleteAccount"))}</div>
    <p class="sheet-hint">${esc(t("deleteAccountWarning"))}</p>
    ${confirmField}
    <div class="sheet-btn-row">
      <button class="btn-secondary" data-action="close-sheet">${esc(t("cancel"))}</button>
      <button class="btn-danger-soft" data-action="confirm-delete-account">${esc(t("deleteForever"))}</button>
    </div>
    <p class="error">${esc(state.error)}</p>`, { persistent: true });
}

function whatsappSheet() {
  return sheetShell(`
    <div class="sheet-title">${esc(t("whatsappLogging"))}</div>
    <p class="sheet-hint">${esc(t("whatsappHint"))}</p>
    <button class="btn-primary" style="width:100%" data-action="close-sheet">${esc(t("close"))}</button>`);
}

function categoriesSheet() {
  const rows = decoratedCategories().map((c) => `
    <button class="card-row" data-action="edit-category" data-id="${c.id}">
      <span class="tile tile-cat" style="--cat:${esc(c.color)};--tint:${esc(tintOf(c.color))}">${esc(c.emoji)}</span>
      <span class="tx-name">${esc(c.name)}
        <span class="tx-sub">${esc(c.tag ? t(c.tag.toLowerCase()) : t("noTag"))}</span>
      </span>
      <span class="settings-row-value">${esc(c.target ? fmt(c.target) : t("noLimit"))}</span>
    </button>`).join("");

  return sheetShell(`
    <div class="sheet-title">${esc(t("categories"))}</div>
    <div class="card card-16" style="margin-bottom:18px">
      ${rows}
      <button class="card-row settings-row" data-action="new-category">
        <span class="settings-row-label" style="color:var(--text-muted)">+ ${esc(t("newCategory"))}</span>
      </button>
    </div>
    <button class="btn-primary" style="width:100%" data-action="close-sheet">${esc(t("done"))}</button>`);
}

function categoryEditSheet() {
  const editing = data.categories.find((c) => c.id === state.editingCategoryId);
  const icon = editing ? emojiForCategory(editing) : EMOJI_CHOICES[0];
  const tag = editing ? editing.tag || "" : "";

  return sheetShell(`
    <div class="sheet-title">${esc(t(editing ? "editCategory" : "newCategory"))}</div>
    <label class="field"><span>${esc(t("name"))}</span>
      <input id="cat-name" type="text" value="${esc(editing ? editing.name : "")}" />
    </label>
    <div class="field"><span>${esc(t("iconEmoji"))}</span>
      <div class="emoji-picker" id="cat-emoji">
        ${EMOJI_CHOICES.map((e) => `<button type="button" class="emoji-swatch ${e === icon ? "is-selected" : ""}" data-action="pick-emoji" data-value="${esc(e)}">${esc(e)}</button>`).join("")}
      </div>
    </div>
    <label class="field"><span>${esc(t("monthlyTarget"))}</span>
      <input id="cat-target" type="number" step="0.01" min="0" value="${editing && editing.target != null ? editing.target : ""}" placeholder="${esc(t("noLimit"))}" />
    </label>
    <div class="field"><span>${esc(t("tagOptional"))}</span>
      <div class="segmented" id="cat-tag">
        ${["", "Needs", "Wants", "Savings"].map((value) => `
          <button type="button" class="${value === tag ? "is-selected" : ""}" data-action="pick-tag" data-value="${esc(value)}">${esc(value ? t(value.toLowerCase()) : t("none"))}</button>`).join("")}
      </div>
    </div>
    <div class="sheet-btn-row">
      ${editing ? `<button class="btn-danger-soft" data-action="delete-category" data-id="${editing.id}">${esc(t("delete"))}</button>` : ""}
      <button class="btn-secondary" data-action="open-categories">${esc(t("cancel"))}</button>
      <button class="btn-primary" data-action="save-category">${esc(t("save"))}</button>
    </div>
    <p class="error">${esc(state.error)}</p>`, { persistent: true });
}

function incomeSheet() {
  const rows = data.income.map((i) => `
    <div class="card-row is-static">
      <span class="tx-name">${esc(i.name)}</span>
      <span class="tx-amount">${esc(fmt(i.amount))}</span>
      <button class="chevron" data-action="delete-income" data-id="${i.id}" style="background:none;border:none;cursor:pointer;color:var(--danger)">✕</button>
    </div>`).join("");

  return sheetShell(`
    <div class="sheet-title">${esc(t("income"))}</div>
    <p class="sheet-hint">${esc(t("incomeHint", { period: periodOf(currentRange().start) }))}</p>
    ${rows ? `<div class="card card-16" style="margin-bottom:18px">${rows}</div>` : ""}
    <div class="field-row">
      <label class="field"><span>${esc(t("name"))}</span><input id="income-name" type="text" /></label>
      <label class="field"><span>${esc(t("amount"))}</span><input id="income-amount" type="number" step="0.01" min="0" /></label>
    </div>
    <div class="sheet-btn-row" style="margin-top:0">
      <button class="btn-secondary" data-action="close-sheet">${esc(t("close"))}</button>
      <button class="btn-primary" data-action="add-income">${esc(t("add"))}</button>
    </div>
    <p class="error">${esc(state.error)}</p>`, { persistent: true });
}

function accountEditSheet() {
  const editing = data.accounts.find((a) => a.id === state.editingAccountId);
  const icon = editing ? editing.icon : ACCOUNT_EMOJI_CHOICES[0];

  return sheetShell(`
    <div class="sheet-title">${esc(t(editing ? "editAccount" : "addAccount"))}</div>
    <label class="field"><span>${esc(t("name"))}</span>
      <input id="acc-name" type="text" value="${esc(editing ? editing.name : "")}" />
    </label>
    <div class="field"><span>${esc(t("iconEmoji"))}</span>
      <div class="emoji-picker" id="acc-emoji">
        ${ACCOUNT_EMOJI_CHOICES.map((e) => `<button type="button" class="emoji-swatch ${e === icon ? "is-selected" : ""}" data-action="pick-emoji" data-value="${esc(e)}">${esc(e)}</button>`).join("")}
      </div>
    </div>
    <div class="field-row">
      <label class="field"><span>${esc(t("accountKind"))}</span>
        <input id="acc-kind" type="text" value="${esc(editing && editing.kind ? editing.kind : "")}" placeholder="${esc(t("accountKindPlaceholder"))}" />
      </label>
      <label class="field"><span>${esc(t("lastDigits"))}</span>
        <input id="acc-last4" type="text" maxlength="4" value="${esc(editing && editing.last4 ? editing.last4 : "")}" />
      </label>
    </div>
    <label class="field"><span>${esc(t("balance"))}</span>
      <input id="acc-balance" type="number" step="0.01" value="${editing ? editing.balance : ""}" />
    </label>
    <div class="sheet-btn-row">
      ${editing ? `<button class="btn-danger-soft" data-action="delete-account" data-id="${editing.id}">${esc(t("delete"))}</button>` : ""}
      <button class="btn-secondary" data-action="close-sheet">${esc(t("cancel"))}</button>
      <button class="btn-primary" data-action="save-account">${esc(t("save"))}</button>
    </div>
    <p class="error">${esc(state.error)}</p>`, { persistent: true });
}

function profileSheet() {
  const me = data.me || {};
  return sheetShell(`
    <div class="sheet-title">${esc(t("profile"))}</div>
    <label class="field"><span>${esc(t("displayName"))}</span>
      <input id="profile-name" type="text" maxlength="40" value="${esc(me.display_name || "")}" />
    </label>
    <label class="field"><span>${esc(t("profilePicture"))}</span>
      <input id="profile-avatar" type="file" accept="image/*" />
    </label>
    <div class="field"><span>${esc(t("budgetGoals"))}</span>
      <div class="field-row">
        <label class="field"><span>${esc(t("wants"))}</span><input id="goal-wants" type="number" min="0" max="100" value="${me.wants_goal_pct != null ? me.wants_goal_pct : 50}" /></label>
        <label class="field"><span>${esc(t("needs"))}</span><input id="goal-needs" type="number" min="0" max="100" value="${me.needs_goal_pct != null ? me.needs_goal_pct : 40}" /></label>
        <label class="field"><span>${esc(t("savings"))}</span><input id="goal-savings" type="number" min="0" max="100" value="${me.savings_goal_pct != null ? me.savings_goal_pct : 10}" /></label>
      </div>
    </div>
    <div class="sheet-btn-row" style="margin-top:0">
      <button class="btn-secondary" data-action="close-sheet">${esc(t("cancel"))}</button>
      <button class="btn-primary" data-action="save-profile">${esc(t("save"))}</button>
    </div>
    <p class="error">${esc(state.error)}</p>`, { persistent: true });
}

const SHEETS = {
  period: periodSheet,
  add: addSheet,
  tx: txSheet,
  currency: currencySheet,
  timezone: timeZoneSheet,
  language: languageSheet,
  theme: themeSheet,
  twofactor: twoFactorSheet,
  import: importSheet,
  whatsapp: whatsappSheet,
  deleteAccount: deleteAccountSheet,
  categories: categoriesSheet,
  categoryEdit: categoryEditSheet,
  income: incomeSheet,
  accountEdit: accountEditSheet,
  profile: profileSheet,
};

// --- render --------------------------------------------------------------

const VIEWS = {
  activity: activityView,
  rates: ratesView,
  summary: summaryView,
  detail: detailView,
  budget: budgetView,
  analytics: analyticsView,
  accounts: accountsView,
};

function renderTabs() {
  document.getElementById("tabbar").innerHTML = TAB_DEFS.map(([id, labelKey, icon]) => {
    // The detail view is a drill-down of Summary, so Summary stays lit.
    const active = state.view === id || (id === "summary" && state.view === "detail");
    return `<button class="tab ${active ? "is-active" : ""}" data-action="set-view" data-value="${id}">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="${icon}"></path>
        </svg>
        <span>${esc(t(labelKey))}</span>
      </button>`;
  }).join("");
}

function render() {
  const root = document.getElementById("view-root");
  root.innerHTML = (VIEWS[state.view] || activityView)();
  renderTabs();

  document.getElementById("sheet-root").innerHTML = state.sheet && SHEETS[state.sheet]
    ? SHEETS[state.sheet]()
    : "";

  const search = document.getElementById("search-input");
  if (search) {
    search.focus();
    search.setSelectionRange(search.value.length, search.value.length);
  }
}

// --- loading -------------------------------------------------------------

async function loadIdentity() {
  const [me, stats, accounts] = await Promise.all([
    apiFetch("/api/me"),
    apiFetch("/api/me/stats"),
    apiFetch("/api/accounts"),
  ]);
  data.me = me;
  data.stats = stats;
  data.accounts = accounts;
  currentCurrency = me.currency || "USD";
}

async function loadRange() {
  const range = currentRange();
  const query = rangeQuery(range);
  const previous = previousRange(range);

  const [categories, expenses, goals, prior] = await Promise.all([
    apiFetch(`/api/budget?${query}`),
    apiFetch(`/api/expenses?${query}`),
    apiFetch(`/api/budget/goals?${query}`),
    apiFetch(`/api/expenses?${rangeQuery(previous)}`),
  ]);

  data.categories = categories;
  data.expenses = expenses;
  data.goals = goals;
  data.prevTotal = prior.reduce((sum, e) => sum + e.amount, 0);

  // Income is month-keyed, so it only gets fetched when the Income toggle
  // actually needs it - one call per month the range touches.
  if (state.kind === "Income" || state.sheet === "income") {
    const periods = [];
    let cursor = new Date(range.start.getFullYear(), range.start.getMonth(), 1);
    while (cursor <= range.end) {
      periods.push(periodOf(cursor));
      cursor = addMonths(cursor, 1);
    }
    const pages = await Promise.all(periods.map((p) => apiFetch(`/api/income?period=${p}`)));
    data.income = pages.flat();
  }
}

// Rates are the same for everyone and change once a day, so they load when
// something actually needs them - opening the page, or opening the add sheet
// where the converted preview is drawn - rather than on every refresh.
async function loadRates() {
  try {
    data.rates = await apiFetch("/api/rates");
  } catch (err) {
    // A rates outage must not take down the add sheet: the preview simply
    // doesn't draw, and the backend still converts on save.
    data.rates = { rates: [], error: err.message };
  }
}

async function loadAnalytics() {
  const range = analyticsRange();
  const expenses = await apiFetch(`/api/expenses?${rangeQuery(range)}`);
  data.analyticsExpenses = expenses;

  // With no period chosen the range reaches back to 1970, which would draw
  // hundreds of empty buckets - so the chart starts at the earliest expense
  // there actually is, and falls back to this month when there are none.
  let start = range.start;
  if (!state.analyticsPeriod) {
    const earliest = expenses.reduce((min, e) => (min && min <= e.date ? min : e.date), null);
    start = earliest ? parseDate(earliest) : new Date(range.end.getFullYear(), range.end.getMonth(), 1);
  }
  data.analyticsBuckets = seriesFor({ start, end: range.end }, expenses);
}

async function refresh({ identity = false, analytics = false } = {}) {
  try {
    const jobs = [loadRange()];
    if (identity) jobs.push(loadIdentity());
    if (analytics || state.view === "analytics") jobs.push(loadAnalytics());
    await Promise.all(jobs);
    state.error = "";
  } catch (err) {
    state.error = err.message;
  }
  render();
}

// --- actions -------------------------------------------------------------

function pressKey(key) {
  const amount = state.amount;
  if (key === "⌫") {
    state.amount = amount.slice(0, -1);
    return;
  }
  if (key === ".") {
    if (amount.includes(".")) return;
    state.amount = (amount || "0") + ".";
    return;
  }
  const decimals = amount.split(".")[1];
  if (decimals && decimals.length >= 2) return;
  state.amount = (amount === "0" ? "" : amount) + key;
}

function resizeImageToDataUrl(file, maxSize) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(t("errGeneric")));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error(t("errGeneric")));
      img.onload = () => {
        const scale = Math.min(1, maxSize / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        canvas.getContext("2d").drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.82));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

async function runImport() {
  const fileInput = document.getElementById("import-file");
  const period = document.getElementById("import-period").value;
  if (!fileInput.files.length) {
    state.error = t("errPickFile");
    render();
    return;
  }

  const form = new FormData();
  form.append("file", fileInput.files[0]);
  if (period) form.append("period", period);

  // Multipart, so this can't go through apiFetch - setting a JSON
  // Content-Type here would strip the boundary the server needs.
  const res = await fetch(`${window.API_BASE_URL}/api/import/spreadsheet`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken()}` },
    body: form,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    state.error = body.detail ? translateError(body.detail) : t("errGeneric");
    render();
    return;
  }
  state.sheet = null;
  state.error = "";
  await refresh({ identity: true, analytics: true });
}

// Changing the zone re-files existing expenses onto different calendar days, so
// everything on screen has to be refetched rather than just re-rendered.
async function saveTimeZone(zone) {
  await apiFetch("/api/me/timezone", {
    method: "PUT",
    body: JSON.stringify({ timezone: zone || "" }),
  });
  state.sheet = null;
  state.error = "";
  return refresh({ identity: true, analytics: true });
}

const ACTIONS = {
  "set-view": (el) => {
    state.view = el.dataset.value;
    if (state.view === "summary") state.selCat = null;
    if (state.view === "analytics" && !data.analyticsBuckets) return refresh();
  },
  "go-accounts": () => { state.view = "accounts"; },
  "go-summary": () => { state.view = "summary"; state.selCat = null; },
  "open-category": (el) => { state.view = "detail"; state.selCat = Number(el.dataset.id); },
  "clear-category": () => { state.view = "summary"; state.selCat = null; },
  "open-search": () => { state.view = "activity"; state.searchOpen = true; },
  "close-search": () => { state.searchOpen = false; state.q = ""; },
  "toggle-kind": async () => {
    state.kind = state.kind === "Expenses" ? "Income" : "Expenses";
    // The donut and the twelve-month chart are spend-shaped; income has no
    // categories and no per-day rows, so it always reads on Activity.
    state.view = "activity";
    return refresh();
  },
  "open-period": () => { state.sheet = "period"; },
  "clear-period": async () => {
    if (state.view !== "analytics") return;
    state.analyticsPeriod = null;
    return refresh();
  },
  "set-period": async (el) => {
    if (state.view === "analytics") {
      state.analyticsPeriod = el.dataset.value || null;  // "" is the All time row
    } else {
      state.period = el.dataset.value;
    }
    return refresh();
  },
  "open-add": () => {
    state.sheet = "add";
    state.amount = "";
    state.error = "";
    if (state.addCatId == null) {
      const first = decoratedCategories()[0];
      state.addCatId = first ? first.id : null;
    }
  },
  key: (el) => pressKey(el.dataset.value),
  "set-add-category": (el) => { state.addCatId = Number(el.dataset.id); },
  "save-expense": async () => {
    const amount = parseFloat(state.amount);
    if (!amount) {
      state.sheet = null;
      return;
    }
    await apiFetch("/api/expenses", {
      method: "POST",
      body: JSON.stringify({
        amount,
        category_id: state.addCatId,
        account_id: data.accounts.length ? data.accounts[0].id : null,
        date: isoDate(new Date()),
        // Omitted when it matches the account's currency, so the common case
        // sends exactly what it always did.
        currency: state.addCurrency || undefined,
      }),
    });
    state.sheet = null;
    state.amount = "";
    state.addCurrency = null;
    return refresh({ identity: true, months: true });
  },
  "open-tx": (el) => { state.sheet = "tx"; state.txId = Number(el.dataset.id); },
  "delete-expense": async (el) => {
    await apiFetch(`/api/expenses/${el.dataset.id}`, { method: "DELETE" });
    state.sheet = null;
    state.txId = null;
    return refresh({ identity: true, months: true });
  },
  "close-sheet": () => { state.sheet = null; state.error = ""; },

  "open-currency": () => { state.sheet = "currency"; },
  "open-timezone": () => { state.sheet = "timezone"; state.error = ""; },

  "set-timezone": async (el) => saveTimeZone(el.dataset.value),
  "save-timezone": async () => {
    const select = document.getElementById("timezone-select");
    return saveTimeZone(select ? select.value : "");
  },
  "set-currency": async (el) => {
    await apiFetch("/api/me/currency", { method: "PUT", body: JSON.stringify({ currency: el.dataset.value }) });
    currentCurrency = el.dataset.value;
    state.sheet = null;
    return refresh({ identity: true });
  },
  "open-language": () => { state.sheet = "language"; },
  "set-language": (el) => {
    settings = { ...settings, lang: el.dataset.value };
    saveSettings(settings);
    applySettings(settings);
    state.sheet = null;
  },
  "open-theme": () => { state.sheet = "theme"; },
  "set-theme": (el) => {
    settings = { ...settings, theme: el.dataset.value };
    saveSettings(settings);
    applySettings(settings);
    state.sheet = null;
  },
  "open-twofactor": () => { state.sheet = "twofactor"; },
  "set-twofactor": async (el) => {
    await apiFetch("/api/me/two-factor", {
      method: "PUT",
      body: JSON.stringify({ enabled: el.dataset.value === "on" }),
    });
    state.sheet = null;
    return refresh({ identity: true });
  },
  "open-import": () => { state.sheet = "import"; state.error = ""; },
  "run-import": () => runImport(),
  "open-whatsapp": () => { state.sheet = "whatsapp"; },

  "open-rates": async () => {
    state.view = "rates";
    if (!data.rates) {
      render(); // paint the page's loading state before the request goes out
      await loadRates();
    }
  },
  "set-add-currency": async (el) => {
    const code = el.dataset.value;
    state.addCurrency = code === currentCurrency ? null : code;
    // The preview needs rates the first time a foreign currency is picked.
    if (state.addCurrency && !data.rates) {
      render();
      await loadRates();
    }
  },

  "open-categories": () => { state.sheet = "categories"; state.error = ""; },
  "new-category": () => { state.sheet = "categoryEdit"; state.editingCategoryId = null; state.error = ""; },
  "edit-category": (el) => { state.sheet = "categoryEdit"; state.editingCategoryId = Number(el.dataset.id); state.error = ""; },
  "pick-emoji": (el) => {
    el.parentElement.querySelectorAll(".emoji-swatch").forEach((b) => b.classList.remove("is-selected"));
    el.classList.add("is-selected");
    return "no-render";
  },
  "pick-tag": (el) => {
    el.parentElement.querySelectorAll("button").forEach((b) => b.classList.remove("is-selected"));
    el.classList.add("is-selected");
    return "no-render";
  },
  "save-category": async () => {
    const name = document.getElementById("cat-name").value.trim();
    if (!name) {
      state.error = t("nameRequired");
      return;
    }
    const targetRaw = document.getElementById("cat-target").value;
    const icon = document.querySelector("#cat-emoji .is-selected");
    const tag = document.querySelector("#cat-tag .is-selected");
    const body = {
      name,
      icon: icon ? icon.dataset.value : undefined,
      target: targetRaw === "" ? null : Number(targetRaw),
      tag: tag && tag.dataset.value ? tag.dataset.value : null,
    };

    if (state.editingCategoryId) {
      await apiFetch(`/api/budget/categories/${state.editingCategoryId}`, {
        method: "PUT",
        body: JSON.stringify({ ...body, clear_target: targetRaw === "", clear_tag: !body.tag }),
      });
    } else {
      await apiFetch("/api/budget/categories", { method: "POST", body: JSON.stringify(body) });
    }
    state.sheet = "categories";
    state.error = "";
    return refresh();
  },
  "delete-category": async (el) => {
    await apiFetch(`/api/budget/categories/${el.dataset.id}`, { method: "DELETE" });
    state.sheet = "categories";
    return refresh({ identity: true, months: true });
  },

  "open-income": async () => { state.sheet = "income"; state.error = ""; return refresh(); },
  "add-income": async () => {
    const name = document.getElementById("income-name").value.trim();
    const amount = parseFloat(document.getElementById("income-amount").value);
    if (!name || !amount) {
      state.error = t("nameAndAmountRequired");
      return;
    }
    await apiFetch("/api/income", {
      method: "POST",
      body: JSON.stringify({ name, amount, period: periodOf(currentRange().start) }),
    });
    state.error = "";
    return refresh();
  },
  "delete-income": async (el) => {
    await apiFetch(`/api/income/${el.dataset.id}`, { method: "DELETE" });
    return refresh();
  },

  "add-account": () => { state.sheet = "accountEdit"; state.editingAccountId = null; state.error = ""; },
  "edit-account": (el) => { state.sheet = "accountEdit"; state.editingAccountId = Number(el.dataset.id); state.error = ""; },
  "save-account": async () => {
    const name = document.getElementById("acc-name").value.trim();
    if (!name) {
      state.error = t("nameRequired");
      return;
    }
    const icon = document.querySelector("#acc-emoji .is-selected");
    const balanceRaw = document.getElementById("acc-balance").value;
    const body = {
      name,
      kind: document.getElementById("acc-kind").value.trim() || null,
      last4: document.getElementById("acc-last4").value.trim() || null,
      balance: balanceRaw === "" ? 0 : Number(balanceRaw),
      icon: icon ? icon.dataset.value : undefined,
    };

    if (state.editingAccountId) {
      await apiFetch(`/api/accounts/${state.editingAccountId}`, {
        method: "PUT",
        body: JSON.stringify({ ...body, clear_kind: !body.kind, clear_last4: !body.last4 }),
      });
    } else {
      await apiFetch("/api/accounts", { method: "POST", body: JSON.stringify(body) });
    }
    state.sheet = null;
    return refresh({ identity: true });
  },
  "delete-account": async (el) => {
    await apiFetch(`/api/accounts/${el.dataset.id}`, { method: "DELETE" });
    state.sheet = null;
    return refresh({ identity: true });
  },

  "open-profile": () => { state.sheet = "profile"; state.error = ""; },
  "save-profile": async () => {
    const wants = Number(document.getElementById("goal-wants").value);
    const needs = Number(document.getElementById("goal-needs").value);
    const savings = Number(document.getElementById("goal-savings").value);
    if (Math.abs(wants + needs + savings - 100) > 0.5) {
      state.error = t("errGoalsMustSumTo100");
      return;
    }

    const body = { display_name: document.getElementById("profile-name").value };
    const file = document.getElementById("profile-avatar").files[0];
    if (file) body.avatar_url = await resizeImageToDataUrl(file, 256);

    await apiFetch("/api/me/profile", { method: "PUT", body: JSON.stringify(body) });
    await apiFetch("/api/me/goals", {
      method: "PUT",
      body: JSON.stringify({ wants_pct: wants, needs_pct: needs, savings_pct: savings }),
    });
    state.sheet = null;
    return refresh({ identity: true });
  },

  logout: () => {
    clearToken();
    showAuthScreen();
    return "no-render";
  },

  "open-delete-account": () => { state.sheet = "deleteAccount"; state.error = ""; },

  "confirm-delete-account": async () => {
    const me = data.me || {};
    const body = {};
    if (me.has_password !== false) {
      const password = (document.getElementById("delete-password") || {}).value || "";
      if (!password) { state.error = t("errPasswordRequired"); return; }
      body.password = password;
    } else {
      const typed = ((document.getElementById("delete-confirm") || {}).value || "").trim().toUpperCase();
      if (typed !== "DELETE") { state.error = t("errTypeDelete"); return; }
    }

    await apiFetch("/api/me", { method: "DELETE", body: JSON.stringify(body), credentialCheck: true });
    // The account is gone, so there is nothing left to re-render behind the
    // sheet - drop straight back to the login screen.
    state.sheet = null;
    clearToken();
    localStorage.removeItem(REMEMBERED_EMAIL_KEY);
    showAuthScreen();
    return "no-render";
  },
};

document.addEventListener("click", async (event) => {
  const el = event.target.closest("[data-action]");
  if (!el) return;
  // A tap inside the sheet card bubbles up to the scrim, which is also the
  // close target - so the scrim only closes on a tap that landed on it.
  if (el.classList.contains("sheet-scrim") && event.target !== el) return;

  const action = ACTIONS[el.dataset.action];
  if (!action) return;
  event.preventDefault();

  try {
    const result = await action(el);
    if (result !== "no-render") render();
  } catch (err) {
    state.error = err.message;
    render();
  }
});

document.addEventListener("input", (event) => {
  if (event.target.id === "search-input") {
    state.q = event.target.value;
    render();
    return;
  }

  // The converter updates its own result node instead of re-rendering: a full
  // render would rebuild the input and drop the caret mid-number.
  if (event.target.id === "conv-amount") {
    state.convAmount = event.target.value;
    const output = document.querySelector(".conv-result");
    if (!output) return;
    const typed = parseFloat(state.convAmount);
    const result = typed && ratesReady() ? convertWithRates(typed, state.convFrom, state.convTo) : null;
    output.textContent = result == null ? "—" : fmtIn(result, state.convTo);
  }
});

document.addEventListener("change", (event) => {
  if (event.target.id !== "conv-from" && event.target.id !== "conv-to") return;
  state.convFrom = document.getElementById("conv-from").value;
  state.convTo = document.getElementById("conv-to").value;
  render();
});

// --- auth screens --------------------------------------------------------

const authScreen = document.getElementById("auth-screen");
const otpScreen = document.getElementById("otp-screen");
const quizScreen = document.getElementById("quiz-screen");
const appScreen = document.getElementById("app-screen");
const ALL_SCREENS = [authScreen, otpScreen, quizScreen, appScreen];

let mode = "login";
let pendingOtpEmail = null;
let quizAnswers = {};

function showOnlyScreen(screen) {
  ALL_SCREENS.forEach((s) => s.classList.toggle("hidden", s !== screen));
  document.getElementById("sheet-root").innerHTML = "";
}

function showAuthScreen() {
  showOnlyScreen(authScreen);
  document.getElementById("auth-error").textContent = "";
  const emailInput = document.getElementById("email");
  if (!emailInput.value) emailInput.value = rememberedEmail();
  rememberCheckbox.checked = rememberMe();
  loadOauthProviders();
}

async function showAppScreen() {
  showOnlyScreen(appScreen);
  state.view = "activity";
  await refresh({ identity: true });
}

async function afterLogin() {
  const me = await apiFetch("/api/me");
  data.me = me;
  currentCurrency = me.currency || "USD";
  if (!me.onboarded) return showQuizScreen();
  return showAppScreen();
}

const authForm = document.getElementById("auth-form");
const authError = document.getElementById("auth-error");
const authSubmit = document.getElementById("auth-submit");
const rememberCheckbox = document.getElementById("remember-me");

rememberCheckbox.checked = rememberMe();
rememberCheckbox.addEventListener("change", () => setRememberMe(rememberCheckbox.checked));

document.getElementById("switch-link").addEventListener("click", () => {
  mode = mode === "login" ? "signup" : "login";
  authSubmit.textContent = t(mode === "login" ? "login" : "signup");
  document.getElementById("switch-link").textContent = t(mode === "login" ? "signup" : "backToLogin");
  authError.textContent = "";
});

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authError.textContent = "";
  const email = document.getElementById("email").value;
  const password = document.getElementById("password").value;

  try {
    const body = JSON.stringify({ email, password, lang: settings.lang });
    const res = await apiFetch(`/api/auth/${mode}`, { method: "POST", body });
    if (res.requires_otp) {
      pendingOtpEmail = email;
      showOnlyScreen(otpScreen);
      return;
    }
    setToken(res.access_token);
    rememberEmail(email);
    await afterLogin();
  } catch (err) {
    authError.textContent = err.message;
  }
});

// --- social sign-in ------------------------------------------------------
// The buttons are drawn from whatever the backend has credentials for, so a
// deploy with none configured shows the plain email form and nothing else.

const OAUTH_ICONS = {
  google: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.5h6.5a5.6 5.6 0 01-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.8z"/><path fill="#34A853" d="M12 24c3.2 0 5.9-1.1 7.9-2.9l-3.9-3a7.2 7.2 0 01-10.7-3.8h-4v3.1A12 12 0 0012 24z"/><path fill="#FBBC05" d="M5.3 14.3a7.1 7.1 0 010-4.6V6.6h-4a12 12 0 000 10.8l4-3.1z"/><path fill="#EA4335" d="M12 4.8c1.8 0 3.4.6 4.6 1.8l3.5-3.5A12 12 0 001.3 6.6l4 3.1A7.2 7.2 0 0112 4.8z"/></svg>`,
  apple: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M16.4 12.7c0-2.5 2-3.7 2.1-3.8-1.2-1.7-3-1.9-3.6-2-1.5-.2-3 .9-3.8.9-.8 0-2-.9-3.3-.8-1.7 0-3.2 1-4.1 2.5-1.7 3-.4 7.5 1.3 10 .8 1.2 1.8 2.5 3.1 2.5 1.2 0 1.7-.8 3.2-.8s1.9.8 3.2.8c1.3 0 2.2-1.2 3-2.4a11 11 0 001.4-2.8c-.1 0-2.6-1-2.6-4.1zM14.2 4.6c.7-.8 1.1-2 1-3.1-1 0-2.2.7-2.9 1.5-.6.7-1.2 1.9-1 3 1.1.1 2.2-.6 2.9-1.4z"/></svg>`,
  github: `<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .5a12 12 0 00-3.8 23.4c.6.1.8-.3.8-.6v-2c-3.3.7-4-1.6-4-1.6-.6-1.4-1.4-1.8-1.4-1.8-1.1-.7.1-.7.1-.7 1.2.1 1.9 1.2 1.9 1.2 1.1 1.9 2.9 1.3 3.6 1 .1-.8.4-1.3.8-1.6-2.7-.3-5.5-1.3-5.5-5.9 0-1.3.5-2.4 1.2-3.2-.1-.3-.5-1.5.1-3.2 0 0 1-.3 3.3 1.2a11.5 11.5 0 016 0C17.4 5.2 18.4 5.5 18.4 5.5c.6 1.7.2 2.9.1 3.2.8.8 1.2 1.9 1.2 3.2 0 4.6-2.8 5.6-5.5 5.9.4.4.8 1.1.8 2.2v3.3c0 .3.2.7.8.6A12 12 0 0012 .5z"/></svg>`,
};

// Holds the in-flight (or finished) load, so concurrent callers share one
// request. Cleared again if the request fails, which is the point: a flag set
// before the await would stick on the very failure it needs to recover from -
// the backend sleeps on the free tier, so the first call after a cold start is
// the one most likely to time out, and the buttons would then stay missing for
// the life of the page even once it woke up.
// Holds the in-flight (or finished) load, so concurrent callers share one
// request. Cleared again if the request fails, which is the point: a flag set
// before the await would stick on the very failure it needs to recover from -
// the backend sleeps on the free tier, so the first call after a cold start is
// the one most likely to time out, and the buttons would then stay missing for
// the life of the page even once it woke up.
let oauthProvidersLoad = null;

function loadOauthProviders() {
  if (oauthProvidersLoad) return oauthProvidersLoad;

  oauthProvidersLoad = (async () => {
    let providers = [];
    try {
      providers = (await apiFetch("/api/auth/providers")).providers || [];
    } catch {
      oauthProvidersLoad = null;  // let the next visit to the login screen retry
      return;  // backend asleep or older than this build - the email form still works
    }
    if (!providers.length) return;

    document.getElementById("oauth-buttons").innerHTML = providers.map((p) => `
      <button type="button" class="oauth-btn" data-provider="${esc(p.name)}">
        ${OAUTH_ICONS[p.name] || ""}<span>${esc(t("continueWithProvider", { provider: p.label }))}</span>
      </button>`).join("");
    document.getElementById("oauth-block").classList.remove("hidden");

    document.querySelectorAll("#oauth-buttons .oauth-btn").forEach((button) => {
      button.addEventListener("click", () => {
        // Come back to this page with no hash of its own - the backend appends
        // the token there, and a leftover fragment would collide with it.
        const back = window.location.href.split("#")[0];
        window.location.href =
          `${window.API_BASE_URL}/api/auth/oauth/${encodeURIComponent(button.dataset.provider)}`
          + `/start?redirect_uri=${encodeURIComponent(back)}`;
      });
    });
  })();

  return oauthProvidersLoad;
}

// A social sign-in lands back here with the token (or an error) in the URL
// fragment. Take it, then scrub the address bar so the token isn't sitting in
// history or in whatever the user pastes next.
function consumeOauthRedirect() {
  const hash = new URLSearchParams(window.location.hash.slice(1));
  const token = hash.get("token");
  const error = hash.get("oauth_error");
  if (!token && !error) return false;

  history.replaceState(null, "", window.location.pathname + window.location.search);
  if (error) {
    showAuthScreen();
    authError.textContent = error || t("errOauthFailed");
    return true;
  }
  setToken(token);
  afterLogin().catch((err) => {
    showAuthScreen();
    authError.textContent = err.message;
  });
  return true;
}

document.getElementById("otp-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const otpError = document.getElementById("otp-error");
  otpError.textContent = "";
  try {
    const res = await apiFetch("/api/auth/verify-otp", {
      method: "POST",
      body: JSON.stringify({ email: pendingOtpEmail, code: document.getElementById("otp-code").value }),
    });
    setToken(res.access_token);
    await afterLogin();
  } catch (err) {
    otpError.textContent = err.message;
  }
});

document.getElementById("otp-back-link").addEventListener("click", showAuthScreen);

// Password reset reuses the OTP screen's shape: ask for the email, then take
// the code and the new password in the same place.
document.getElementById("forgot-password-link").addEventListener("click", async () => {
  const email = document.getElementById("email").value.trim();
  if (!email) {
    authError.textContent = t("enterEmailFirst");
    return;
  }
  try {
    await apiFetch("/api/auth/forgot-password", { method: "POST", body: JSON.stringify({ email }) });
    const code = window.prompt(t("resetCodePrompt"));
    if (!code) return;
    const newPassword = window.prompt(t("newPasswordPrompt"));
    if (!newPassword) return;
    await apiFetch("/api/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ email, code, new_password: newPassword }),
    });
    authError.textContent = t("resetSuccess");
  } catch (err) {
    authError.textContent = err.message;
  }
});

async function showQuizScreen() {
  showOnlyScreen(quizScreen);
  quizAnswers = {};
  const questions = await apiFetch("/api/quiz");
  renderQuiz(questions);
}

function renderQuiz(questions) {
  document.getElementById("quiz-questions").innerHTML = questions.map((q) => `
    <div class="quiz-question">
      <p>${esc(localizedQuizText(q.id))}</p>
      <div class="quiz-options">
        ${q.options.map((o) => `<button type="button" class="quiz-option" data-question="${esc(q.id)}" data-option="${esc(o.id)}">${esc(localizedQuizText(q.id, o.id))}</button>`).join("")}
      </div>
    </div>`).join("");

  document.getElementById("quiz-questions").querySelectorAll(".quiz-option").forEach((button) => {
    button.addEventListener("click", () => {
      quizAnswers[button.dataset.question] = button.dataset.option;
      button.parentElement.querySelectorAll(".quiz-option").forEach((b) => b.classList.remove("is-selected"));
      button.classList.add("is-selected");
      document.getElementById("quiz-submit-btn").disabled = Object.keys(quizAnswers).length < questions.length;
    });
  });
}

document.getElementById("quiz-submit-btn").addEventListener("click", async () => {
  const quizError = document.getElementById("quiz-error");
  quizError.textContent = "";
  try {
    await apiFetch("/api/onboarding/complete", {
      method: "POST",
      body: JSON.stringify({ answers: quizAnswers, lang: settings.lang }),
    });
    await showAppScreen();
  } catch (err) {
    quizError.textContent = err.message;
  }
});

// --- boot ----------------------------------------------------------------

applySettings(settings);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("./sw.js").catch(() => {}));
}

if (consumeOauthRedirect()) {
  // handled - afterLogin() or the auth screen is already on its way
} else if (getToken()) {
  afterLogin().catch(() => showAuthScreen());
} else {
  showAuthScreen();
}
