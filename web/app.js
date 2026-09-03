// Talks to the same FastAPI app this page is served from (mounted at /app),
// so API calls are same-origin - no base URL to configure.
// Translation strings and t()/setLang() come from i18n.js, loaded first.

const TOKEN_KEY = "expense_tracker_token";
const SETTINGS_KEY = "expense_tracker_settings";

const CURRENCIES = [
  ["USD", "$"], ["EUR", "€"], ["GBP", "£"], ["RON", "lei"], ["JPY", "¥"],
  ["CHF", "Fr"], ["CAD", "$"], ["AUD", "$"], ["CNY", "¥"], ["INR", "₹"],
  ["BRL", "R$"], ["MXN", "$"], ["SEK", "kr"], ["NOK", "kr"], ["PLN", "zł"], ["TRY", "₺"],
];

const FONT_STACKS = {
  mono: `"IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, monospace`,
  sans: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`,
  rounded: `ui-rounded, "SF Pro Rounded", "Segoe UI Rounded", "Nunito", sans-serif`,
  serif: `Georgia, "Iowan Old Style", "Palatino Linotype", serif`,
};

// Each swatch is [dark hex, light hex] - the picker stores the swatch index
// so a theme switch can resolve to the right member without writing a
// neon dark value into the paper theme or vice versa.
const ACCENT_SWATCHES = [
  ["#e8a13a", "#b3762a"], // amber (lamp default)
  ["#5f9e9a", "#3f7873"], // teal
  ["#8f7fb8", "#6d5b94"], // violet
  ["#d4614f", "#b4442f"], // rust
  ["#c9c2b4", "#55524a"], // bone
];

function accentForTheme(index, theme) {
  const pair = ACCENT_SWATCHES[index] || ACCENT_SWATCHES[0];
  return theme === "light" ? pair[1] : pair[0];
}

function resolvedTheme(settings) {
  if (settings.theme === "system") {
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  return settings.theme;
}

function currentMonthPeriod() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

let currentCurrency = "USD";
let currentUser = null; // last /api/me response - display_name, avatar_url, goal %s
let editingCategoryTag = ""; // "" / "Needs" / "Wants" / "Savings", set by the segmented picker in the category modal
let currentPeriod = currentMonthPeriod(); // "YYYY-MM", freely navigable - not limited to months with data
let currentGraphYear = new Date().getFullYear();
let editingCategoryId = null; // set when the category modal is in "edit" mode
let editingEntryId = null; // set when the entry modal is in "edit" mode
let currentCategories = []; // cached from the last /api/budget load, for the entry-category dropdown and the Add-view picker
let selectedAddCategoryId = null; // category chosen in the Add view

function currencySymbol(code) {
  const found = CURRENCIES.find(([c]) => c === code);
  return found ? found[1] : code;
}

function formatMoney(amount) {
  return `${currencySymbol(currentCurrency)}${Number(amount).toFixed(2)}`;
}

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function setToken(t) { localStorage.setItem(TOKEN_KEY, t); }
function clearToken() { localStorage.removeItem(TOKEN_KEY); }

// Render's free tier spins the backend down after inactivity; the request
// that wakes it back up can take 30-60s and often drops/times out instead of
// resolving, which surfaces to fetch() as a generic network error (frequently
// mislabeled "CORS" in the console since the browser never got a response to
// judge CORS on). Retrying a few times with backoff rides out that wake-up
// instead of failing the very first thing the user does after opening the app.
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
  const token = getToken();
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let res;
  try {
    res = await fetchWithWakeupRetry(window.API_BASE_URL + path, { ...options, headers });
  } catch {
    throw new Error(t("errServerWakingUp"));
  }
  if (res.status === 401 && token) {
    // Only an authenticated request's 401 means "your session is dead" -
    // public endpoints like OTP/reset verification also return 401 for a
    // plain wrong code, which isn't a reason to log the user out.
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

// Category.icon holds either a shape enum ("square|circle|diamond|bar|dashed",
// written by the mark picker) or a legacy emoji string from before this
// redesign. Legacy values get a deterministic shape so existing categories
// still read as visually distinct instead of collapsing onto one glyph.
const MARK_SHAPES = ["square", "circle", "diamond", "bar"];
function markShapeFor(category) {
  const icon = (category && category.icon) || "";
  if (icon === "square" || icon === "circle" || icon === "diamond" || icon === "bar" || icon === "dashed") return icon;
  const key = String((category && category.id) ?? (category && category.name) ?? "x");
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  return MARK_SHAPES[Math.abs(hash) % MARK_SHAPES.length];
}
function markHtml(category) {
  return `<span class="mark mark-${markShapeFor(category)}"></span>`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// =========================================================================
// Settings (language / font / accent / theme) - purely a local device
// preference, no reason to round-trip these to the server.
// =========================================================================

function loadSettings() {
  try {
    return { theme: "dark", accentIndex: 0, font: "mono", lang: "en", ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}") };
  } catch {
    return { theme: "dark", accentIndex: 0, font: "mono", lang: "en" };
  }
}

function saveSettings(settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  applySettings(settings);
}

function applySettings(settings) {
  const root = document.documentElement;
  if (settings.theme === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", settings.theme);
  }
  root.style.setProperty("--accent", accentForTheme(settings.accentIndex || 0, resolvedTheme(settings)));
  root.style.setProperty("--font-stack", FONT_STACKS[settings.font] || FONT_STACKS.mono);

  setLang(settings.lang);
  applyStaticI18n();

  document.querySelectorAll("#theme-segmented button").forEach((b) => b.classList.toggle("active", b.dataset.value === settings.theme));
  document.querySelectorAll("#font-segmented button").forEach((b) => b.classList.toggle("active", b.dataset.value === settings.font));
  document.querySelectorAll("#lang-segmented button").forEach((b) => b.classList.toggle("active", b.dataset.value === settings.lang));
  document.querySelectorAll("#accent-swatches .swatch").forEach((b) => {
    b.classList.toggle("active", Number(b.dataset.index) === (settings.accentIndex || 0));
    b.style.background = accentForTheme(Number(b.dataset.index), resolvedTheme(settings));
  });

  // Re-render anything holding already-translated / locale-formatted text.
  if (!appScreen.classList.contains("hidden")) {
    loadBudget();
    loadGraph();
    renderCategoryPicker();
    updateAddSummary();
  }
}

function initSettingsUI() {
  const accentRow = document.getElementById("accent-swatches");
  ACCENT_SWATCHES.forEach((pair, index) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "swatch";
    btn.style.background = accentForTheme(index, resolvedTheme(loadSettings()));
    btn.dataset.index = String(index);
    btn.addEventListener("click", () => {
      const s = loadSettings();
      s.accentIndex = index;
      saveSettings(s);
    });
    accentRow.appendChild(btn);
  });

  document.querySelectorAll("#theme-segmented button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const s = loadSettings();
      s.theme = btn.dataset.value;
      saveSettings(s);
    });
  });

  document.querySelectorAll("#font-segmented button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const s = loadSettings();
      s.font = btn.dataset.value;
      saveSettings(s);
    });
  });

  document.querySelectorAll("#lang-segmented button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const s = loadSettings();
      s.lang = btn.dataset.value;
      saveSettings(s);
    });
  });

  applySettings(loadSettings());
}

document.getElementById("settings-btn").addEventListener("click", () => openModal("settings-modal"));
document.getElementById("settings-close-btn").addEventListener("click", () => closeModal("settings-modal"));

function openModal(id) { document.getElementById(id).classList.remove("hidden"); }
function closeModal(id) { document.getElementById(id).classList.add("hidden"); }

// =========================================================================
// Auth
// =========================================================================

let mode = "login";
let pendingOtpEmail = null; // email a login OTP was issued for, until verified

const authScreen = document.getElementById("auth-screen");
const otpScreen = document.getElementById("otp-screen");
const quizScreen = document.getElementById("quiz-screen");
const appScreen = document.getElementById("app-screen");
const profileScreen = document.getElementById("profile-screen");
const authForm = document.getElementById("auth-form");
const authError = document.getElementById("auth-error");
const authSubmit = document.getElementById("auth-submit");
const switchLink = document.getElementById("switch-link");

const ALL_SCREENS = [authScreen, otpScreen, quizScreen, appScreen, profileScreen];
function showOnlyScreen(screen) {
  ALL_SCREENS.forEach((s) => s.classList.toggle("hidden", s !== screen));
}

switchLink.addEventListener("click", (e) => {
  e.preventDefault();
  mode = mode === "login" ? "signup" : "login";
  authSubmit.textContent = mode === "login" ? t("login") : t("signup");
  switchLink.textContent = mode === "login" ? t("signup") : t("backToLogin");
  authError.textContent = "";
});

authForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  authError.textContent = "";
  const email = document.getElementById("email").value.trim();
  const password = document.getElementById("password").value;

  try {
    const path = mode === "login" ? "/api/auth/login" : "/api/auth/signup";
    const body = mode === "login" ? { email, password } : { email, password, lang: currentLang };
    const data = await apiFetch(path, { method: "POST", body: JSON.stringify(body) });

    if (data.requires_otp) {
      pendingOtpEmail = email;
      document.getElementById("otp-subtitle").textContent = t("otpSentTo");
      document.getElementById("otp-code").value = "";
      document.getElementById("otp-error").textContent = "";
      showOnlyScreen(otpScreen);
      return;
    }

    setToken(data.access_token);
    await afterLogin();
  } catch (err) {
    authError.textContent = err.message;
  }
});

function showAuthScreen() {
  showOnlyScreen(authScreen);
}

// Common landing logic after any successful auth (password login, OTP
// verify, or fresh signup): first-time accounts go to the quiz, everyone
// else goes straight to the app.
async function afterLogin() {
  try {
    const me = await apiFetch("/api/me");
    currentUser = me;
    currentCurrency = me.currency || "USD";
    document.getElementById("currency-select").value = currentCurrency;
    updateAddSummary();
    document.querySelectorAll("#two-factor-segmented button").forEach((b) =>
      b.classList.toggle("active", b.dataset.value === (me.two_factor_enabled ? "on" : "off"))
    );
    updateAvatarUI();

    if (!me.onboarded) {
      await showQuizScreen();
      return;
    }
  } catch {
    /* handled by apiFetch redirecting to auth on 401 */
    return;
  }

  showAppScreen();
}

// Reflects currentUser.avatar_url / display_name (or email initial as a
// fallback) into every avatar button on the page - topbar and profile screen.
function updateAvatarUI() {
  if (!currentUser) return;
  const initial = (currentUser.display_name || currentUser.email || "?").trim().charAt(0).toUpperCase() || "?";

  document.querySelectorAll(".avatar-img").forEach((img) => {
    if (currentUser.avatar_url) {
      img.src = currentUser.avatar_url;
      img.classList.remove("hidden");
    } else {
      img.classList.add("hidden");
      img.removeAttribute("src");
    }
  });
  document.querySelectorAll(".avatar-initial").forEach((el) => {
    el.textContent = initial;
    el.classList.toggle("hidden", !!currentUser.avatar_url);
  });
}

function showAppScreen() {
  showOnlyScreen(appScreen);
  if (!periodInput.value) periodInput.value = currentPeriod;
  loadBudget();
}

// =========================================================================
// Profile screen: avatar, display name, stats, budget-goal split
// =========================================================================

document.getElementById("profile-btn").addEventListener("click", showProfileScreen);
document.getElementById("profile-back-btn").addEventListener("click", showAppScreen);
document.getElementById("profile-settings-btn").addEventListener("click", () => openModal("settings-modal"));

async function showProfileScreen() {
  showOnlyScreen(profileScreen);
  document.getElementById("profile-display-name").value = (currentUser && currentUser.display_name) || "";
  document.getElementById("profile-email").textContent = currentUser ? currentUser.email : "";
  document.getElementById("goal-wants").value = currentUser ? currentUser.wants_goal_pct : 50;
  document.getElementById("goal-needs").value = currentUser ? currentUser.needs_goal_pct : 40;
  document.getElementById("goal-savings").value = currentUser ? currentUser.savings_goal_pct : 10;
  document.getElementById("goal-error").textContent = "";
  updateAvatarUI();

  const statsEl = document.getElementById("profile-stats");
  statsEl.innerHTML = `<p class="empty-hint">…</p>`;
  try {
    const stats = await apiFetch("/api/me/stats");
    renderProfileStats(stats);
  } catch (err) {
    statsEl.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
}

function renderProfileStats(stats) {
  const cards = [
    [t("statTotalAllTime"), formatMoney(stats.total_all_time)],
    [t("statThisMonth"), formatMoney(stats.total_this_month), true],
    [t("statMonthlyAverage"), formatMoney(stats.monthly_average)],
    [t("statTopCategory"), stats.top_category || "—"],
    [t("statStreak"), `${stats.current_streak_days} ${t("days")}`],
    [t("statMemberSince"), stats.member_since ? stats.member_since.slice(0, 10) : "—"],
  ];
  document.getElementById("profile-stats").innerHTML = cards
    .map(([label, value, accent]) => `<div class="stat-card"><div class="stat-value${accent ? " accent" : ""}">${escapeHtml(String(value))}</div><div class="stat-label">${escapeHtml(label)}</div></div>`)
    .join("");
}

// --- Avatar upload: resized/compressed client-side before base64-encoding ---

const profileAvatarInput = document.getElementById("profile-avatar-input");
document.getElementById("profile-avatar-btn").addEventListener("click", () => profileAvatarInput.click());

profileAvatarInput.addEventListener("change", async () => {
  const file = profileAvatarInput.files[0];
  if (!file) return;
  const hint = document.getElementById("profile-save-hint");
  try {
    const dataUrl = await resizeImageToDataUrl(file, 256);
    await apiFetch("/api/me/profile", { method: "PUT", body: JSON.stringify({ avatar_url: dataUrl }) });
    currentUser.avatar_url = dataUrl;
    updateAvatarUI();
    hint.textContent = t("profileSaved");
    hint.classList.remove("hidden");
  } catch (err) {
    hint.textContent = err.message;
    hint.classList.remove("hidden");
  } finally {
    profileAvatarInput.value = "";
  }
});

function resizeImageToDataUrl(file, maxSize) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(t("errGeneric")));
    reader.onload = () => {
      img.onerror = () => reject(new Error(t("errGeneric")));
      img.onload = () => {
        const scale = Math.min(1, maxSize / Math.max(img.width, img.height));
        const canvas = document.createElement("canvas");
        canvas.width = Math.round(img.width * scale);
        canvas.height = Math.round(img.height * scale);
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL("image/jpeg", 0.85));
      };
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

let displayNameSaveTimer = null;
document.getElementById("profile-display-name").addEventListener("input", (e) => {
  clearTimeout(displayNameSaveTimer);
  const value = e.target.value;
  displayNameSaveTimer = setTimeout(async () => {
    try {
      await apiFetch("/api/me/profile", { method: "PUT", body: JSON.stringify({ display_name: value }) });
      currentUser.display_name = value.trim() || null;
      updateAvatarUI();
    } catch {
      /* silently retried on the next keystroke's debounce */
    }
  }, 600);
});

document.getElementById("goal-save-btn").addEventListener("click", async () => {
  const errorEl = document.getElementById("goal-error");
  errorEl.textContent = "";
  const wants_pct = Number(document.getElementById("goal-wants").value);
  const needs_pct = Number(document.getElementById("goal-needs").value);
  const savings_pct = Number(document.getElementById("goal-savings").value);

  try {
    const result = await apiFetch("/api/me/goals", { method: "PUT", body: JSON.stringify({ wants_pct, needs_pct, savings_pct }) });
    currentUser.wants_goal_pct = result.wants_goal_pct;
    currentUser.needs_goal_pct = result.needs_goal_pct;
    currentUser.savings_goal_pct = result.savings_goal_pct;
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

document.getElementById("logout-btn").addEventListener("click", () => {
  clearToken();
  closeModal("settings-modal");
  showAuthScreen();
});

// --- Import spreadsheet: multipart upload, so this bypasses apiFetch (which
// always sets a JSON Content-Type) and builds the request by hand. ---

document.getElementById("import-period-input").value = currentMonthPeriod();

document.getElementById("import-submit-btn").addEventListener("click", async () => {
  const fileInput = document.getElementById("import-file-input");
  const resultEl = document.getElementById("import-result");
  const errorEl = document.getElementById("import-error");
  resultEl.textContent = "";
  errorEl.textContent = "";

  const file = fileInput.files[0];
  if (!file) {
    errorEl.textContent = t("errPickFile");
    return;
  }

  const period = document.getElementById("import-period-input").value;
  const formData = new FormData();
  formData.append("file", file);
  if (period) formData.append("period", period);

  try {
    const res = await fetch(window.API_BASE_URL + "/api/import/spreadsheet", {
      method: "POST",
      headers: { Authorization: `Bearer ${getToken()}` },
      body: formData,
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail ? translateError(body.detail) : t("errGeneric"));

    resultEl.textContent = t("importResultSummary")
      .replace("{categories}", body.categories_created + body.categories_updated)
      .replace("{income}", body.income_rows)
      .replace("{period}", body.period);
    fileInput.value = "";
    if (currentPeriod === body.period) loadBudget();
  } catch (err) {
    errorEl.textContent = err.message;
  }
});

// --- OTP verification (login 2FA) ---

const otpForm = document.getElementById("otp-form");
const otpError = document.getElementById("otp-error");

otpForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  otpError.textContent = "";
  const code = document.getElementById("otp-code").value.trim();

  try {
    const data = await apiFetch("/api/auth/verify-otp", {
      method: "POST",
      body: JSON.stringify({ email: pendingOtpEmail, code }),
    });
    setToken(data.access_token);
    pendingOtpEmail = null;
    await afterLogin();
  } catch (err) {
    otpError.textContent = err.message;
  }
});

document.getElementById("otp-back-link").addEventListener("click", (e) => {
  e.preventDefault();
  pendingOtpEmail = null;
  showAuthScreen();
});

// --- Forgot password ---

const forgotEmailForm = document.getElementById("forgot-email-form");
const forgotResetForm = document.getElementById("forgot-reset-form");
const forgotError = document.getElementById("forgot-error");
let forgotPasswordEmail = null;

document.getElementById("forgot-password-link").addEventListener("click", (e) => {
  e.preventDefault();
  forgotEmailForm.classList.remove("hidden");
  forgotResetForm.classList.add("hidden");
  document.getElementById("forgot-email").value = document.getElementById("email").value.trim();
  forgotError.textContent = "";
  openModal("forgot-password-modal");
});

[document.getElementById("forgot-cancel-btn"), document.getElementById("forgot-cancel-btn-2")].forEach((btn) =>
  btn.addEventListener("click", () => closeModal("forgot-password-modal"))
);

forgotEmailForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  forgotError.textContent = "";
  forgotPasswordEmail = document.getElementById("forgot-email").value.trim();

  try {
    await apiFetch("/api/auth/forgot-password", { method: "POST", body: JSON.stringify({ email: forgotPasswordEmail }) });
    forgotEmailForm.classList.add("hidden");
    forgotResetForm.classList.remove("hidden");
  } catch (err) {
    forgotError.textContent = err.message;
  }
});

forgotResetForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  forgotError.textContent = "";
  const code = document.getElementById("forgot-code").value.trim();
  const newPassword = document.getElementById("forgot-new-password").value;

  try {
    await apiFetch("/api/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ email: forgotPasswordEmail, code, new_password: newPassword }),
    });
    closeModal("forgot-password-modal");
    document.getElementById("email").value = forgotPasswordEmail;
    document.getElementById("password").value = "";
    authError.textContent = t("resetSuccess");
  } catch (err) {
    forgotError.textContent = err.message;
  }
});

// --- Onboarding quiz ---

let quizAnswers = {};

async function showQuizScreen() {
  showOnlyScreen(quizScreen);
  quizAnswers = {};
  document.getElementById("quiz-submit-btn").disabled = true;
  document.getElementById("quiz-error").textContent = "";

  const container = document.getElementById("quiz-questions");
  container.innerHTML = `<p class="empty-hint">…</p>`;
  try {
    const questions = await apiFetch("/api/quiz");
    renderQuiz(questions);
  } catch (err) {
    container.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
}

function renderQuiz(questions) {
  const container = document.getElementById("quiz-questions");
  container.innerHTML = "";

  questions.forEach((q) => {
    const block = document.createElement("div");
    block.className = "quiz-question";
    block.innerHTML = `<div class="quiz-question-text">${escapeHtml(localizedQuizText(q.id))}</div><div class="quiz-options"></div>`;
    const optionsEl = block.querySelector(".quiz-options");

    q.options.forEach((o) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "quiz-option";
      btn.textContent = localizedQuizText(q.id, o.id);
      btn.addEventListener("click", () => {
        quizAnswers[q.id] = o.id;
        optionsEl.querySelectorAll(".quiz-option").forEach((b) => b.classList.remove("selected"));
        btn.classList.add("selected");
        document.getElementById("quiz-submit-btn").disabled = Object.keys(quizAnswers).length < questions.length;
      });
      optionsEl.appendChild(btn);
    });

    container.appendChild(block);
  });
}

document.getElementById("quiz-submit-btn").addEventListener("click", async () => {
  const quizError = document.getElementById("quiz-error");
  quizError.textContent = "";
  try {
    await apiFetch("/api/onboarding/complete", { method: "POST", body: JSON.stringify({ answers: quizAnswers, lang: currentLang }) });
    showAppScreen();
  } catch (err) {
    quizError.textContent = err.message;
  }
});

// --- Two-factor toggle (Settings) ---

document.querySelectorAll("#two-factor-segmented button").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const enabled = btn.dataset.value === "on";
    try {
      await apiFetch("/api/me/two-factor", { method: "PUT", body: JSON.stringify({ enabled }) });
      document.querySelectorAll("#two-factor-segmented button").forEach((b) => b.classList.toggle("active", b === btn));
    } catch (err) {
      alert(err.message);
    }
  });
});

// =========================================================================
// Tabs
// =========================================================================

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll("#add-view, #budget-view, #graph-view").forEach((v) => v.classList.add("hidden"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.view).classList.remove("hidden");
    if (btn.dataset.view === "budget-view") loadBudget();
    if (btn.dataset.view === "graph-view") loadGraph();
  });
});

// =========================================================================
// Currency
// =========================================================================

function initCurrencySelect() {
  const select = document.getElementById("currency-select");
  select.innerHTML = CURRENCIES.map(([code, symbol]) => `<option value="${code}">${symbol} ${code}</option>`).join("");
  select.value = currentCurrency;

  select.addEventListener("change", async () => {
    const code = select.value;
    try {
      await apiFetch("/api/me/currency", { method: "PUT", body: JSON.stringify({ currency: code }) });
      currentCurrency = code;
      updateAddSummary();
      loadBudget();
      loadGraph();
    } catch (err) {
      select.value = currentCurrency;
      alert(err.message);
    }
  });
}

// =========================================================================
// Add expense: pick a category (searchable once you have 5+), set an amount
// with a linked slider + number field, then confirm from a live summary.
// =========================================================================

const AMOUNT_SLIDER_MAX = 10000;
const CATEGORY_SEARCH_THRESHOLD = 5;
const AMOUNT_PRESETS = [5, 10, 25, 50, 100];

const categorySearch = document.getElementById("category-search");
const categoryPicker = document.getElementById("category-picker");
const amountSlider = document.getElementById("amount-slider");
const amountNumber = document.getElementById("amount-number");
const amountCurrencySymbol = document.getElementById("amount-currency-symbol");
const addSummaryText = document.getElementById("add-summary-text");
const addConfirmBtn = document.getElementById("add-confirm-btn");
const addSuccess = document.getElementById("add-success");

const SHELF_TAGS = ["Needs", "Wants", "Savings", ""];
const shelfLabelFor = (tag) =>
  tag === "Needs" ? t("needs") : tag === "Wants" ? t("wants") : tag === "Savings" ? t("savings") : t("uncategorized");

function groupByShelf(categories) {
  const groups = new Map(SHELF_TAGS.map((tag) => [tag, []]));
  categories.forEach((c) => {
    const tag = SHELF_TAGS.includes(c.tag) ? c.tag : "";
    groups.get(tag).push(c);
  });
  return SHELF_TAGS.map((tag) => ({ tag, items: groups.get(tag) })).filter((g) => g.items.length);
}

function renderCategoryPicker() {
  categorySearch.classList.toggle("hidden", currentCategories.length < CATEGORY_SEARCH_THRESHOLD);
  const query = categorySearch.value.trim().toLowerCase();
  const visible = query
    ? currentCategories.filter((c) => c.name.toLowerCase().includes(query))
    : currentCategories;

  categoryPicker.innerHTML = "";
  groupByShelf(visible).forEach((group) => {
    const shelf = document.createElement("div");
    shelf.className = "shelf-group";
    shelf.innerHTML = `<span class="shelf-label">${escapeHtml(shelfLabelFor(group.tag))}</span>`;
    const row = document.createElement("div");
    row.className = "shelf-row";
    group.items.forEach((c) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `category-chip${c.id === selectedAddCategoryId ? " selected" : ""}`;
      btn.innerHTML = `<span class="icon">${markHtml(c)}</span><span>${escapeHtml(c.name)}</span>`;
      btn.addEventListener("click", () => {
        selectedAddCategoryId = c.id;
        renderCategoryPicker();
        updateAddSummary();
      });
      row.appendChild(btn);
    });
    shelf.appendChild(row);
    categoryPicker.appendChild(shelf);
  });
}

categorySearch.addEventListener("input", renderCategoryPicker);

const amountPresets = document.getElementById("amount-presets");
AMOUNT_PRESETS.forEach((preset) => {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "preset-chip";
  btn.textContent = `+${preset}`;
  btn.addEventListener("click", () => {
    setAmount((Number(amountNumber.value) || 0) + preset);
  });
  amountPresets.appendChild(btn);
});

function setAmount(value) {
  const clamped = Math.max(0, value);
  amountNumber.value = clamped === 0 ? "" : clamped;
  amountSlider.value = Math.min(clamped, AMOUNT_SLIDER_MAX);
  updateAddSummary();
}

amountSlider.addEventListener("input", () => {
  amountNumber.value = amountSlider.value;
  updateAddSummary();
});

amountNumber.addEventListener("input", () => {
  const value = Number(amountNumber.value) || 0;
  amountSlider.value = Math.min(Math.max(0, value), AMOUNT_SLIDER_MAX);
  updateAddSummary();
});

function updateAddSummary() {
  amountCurrencySymbol.textContent = currencySymbol(currentCurrency);
  const amount = Number(amountNumber.value) || 0;
  const category = currentCategories.find((c) => c.id === selectedAddCategoryId);

  if (category && amount > 0) {
    addSummaryText.textContent = t("summaryConfirm", { amount: formatMoney(amount), category: category.name });
    addConfirmBtn.disabled = false;
  } else {
    addSummaryText.textContent = t("pickCategoryAndAmount");
    addConfirmBtn.disabled = true;
  }
}

addConfirmBtn.addEventListener("click", async () => {
  const amount = Number(amountNumber.value) || 0;
  if (!selectedAddCategoryId || amount <= 0) return;

  addConfirmBtn.disabled = true;
  try {
    const category = currentCategories.find((c) => c.id === selectedAddCategoryId);
    await apiFetch("/api/expenses", {
      method: "POST",
      body: JSON.stringify({ amount, category_id: selectedAddCategoryId }),
    });

    addSuccess.textContent = t("loggedSuccess", { amount: formatMoney(amount), category: category.name });
    addSuccess.classList.remove("hidden");
    setTimeout(() => addSuccess.classList.add("hidden"), 2500);

    setAmount(0);
    if (currentPeriod === currentMonthPeriod()) loadBudget();
  } catch (err) {
    addSummaryText.textContent = err.message;
  } finally {
    updateAddSummary();
  }
});

// =========================================================================
// Budget
// =========================================================================

const budgetList = document.getElementById("budget-list");
const periodInput = document.getElementById("period-input");

periodInput.value = currentPeriod;

function shiftPeriod(period, delta) {
  const [year, month] = period.split("-").map(Number);
  const d = new Date(year, month - 1 + delta, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

document.getElementById("period-prev").addEventListener("click", () => {
  currentPeriod = shiftPeriod(currentPeriod, -1);
  periodInput.value = currentPeriod;
  loadBudget();
});

document.getElementById("period-next").addEventListener("click", () => {
  currentPeriod = shiftPeriod(currentPeriod, 1);
  periodInput.value = currentPeriod;
  loadBudget();
});

periodInput.addEventListener("change", () => {
  if (!periodInput.value) return;
  currentPeriod = periodInput.value;
  loadBudget();
});

async function loadBudget() {
  budgetList.innerHTML = `<p class="empty-hint">…</p>`;
  try {
    const categories = await apiFetch(`/api/budget?period=${encodeURIComponent(currentPeriod)}`);
    currentCategories = categories;
    renderBudget(categories);
    renderCategoryPicker();
    loadEntries();
    loadGoalsBar();
  } catch (err) {
    budgetList.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
}

async function loadGoalsBar() {
  const el = document.getElementById("goals-bar");
  try {
    const goals = await apiFetch(`/api/budget/goals?period=${encodeURIComponent(currentPeriod)}`);
    renderGoalsBar(goals);
  } catch {
    el.innerHTML = "";
    el.classList.add("hidden");
  }
}

function renderGoalsBar(goals) {
  const el = document.getElementById("goals-bar");
  const hasData = goals.some((g) => g.actual_amount > 0);
  el.classList.toggle("hidden", !hasData);
  if (!hasData) {
    el.innerHTML = "";
    return;
  }
  const labelFor = { Wants: t("wants"), Needs: t("needs"), Savings: t("savings") };
  const fillClassFor = { Wants: "wants", Needs: "needs", Savings: "savings" };
  el.innerHTML = goals
    .map((g) => {
      const pct = Math.min(100, g.actual_pct);
      const over = g.actual_pct > g.target_pct;
      return `
        <div class="goal-row${over ? " goal-over" : ""}">
          <span class="goal-row-label">${escapeHtml(labelFor[g.tag] || g.tag)}</span>
          <div class="goal-row-track"><div class="goal-row-fill ${fillClassFor[g.tag] || ""}" style="width:${pct}%"></div></div>
          <span class="goal-row-values">${g.actual_pct.toFixed(0)} / ${g.target_pct.toFixed(0)}%</span>
        </div>`;
    })
    .join("");
}

// Days elapsed this month / days in the month - drives the three-state
// budget row treatment. Past periods read as fully burned (nothing to
// dim), future ones as untouched (nothing to warn about yet).
function daysInMonth(period) {
  const [year, month] = period.split("-").map(Number);
  return new Date(year, month, 0).getDate();
}

function periodBurn(period) {
  const todayPeriod = currentMonthPeriod();
  if (period < todayPeriod) return 1;
  if (period > todayPeriod) return 0;
  return new Date().getDate() / daysInMonth(period);
}

function renderBudget(categories) {
  const total = categories.reduce((a, c) => a + c.total, 0);
  document.getElementById("budget-month-total").textContent = Number(total).toFixed(2);
  document.getElementById("budget-month-total-symbol").textContent = currencySymbol(currentCurrency);
  const dayEl = document.getElementById("budget-day-of-month");
  const dim = daysInMonth(currentPeriod);
  const todayPeriod = currentMonthPeriod();
  const day = currentPeriod < todayPeriod ? dim : currentPeriod > todayPeriod ? 1 : new Date().getDate();
  dayEl.textContent = t("dayOfMonth", { day: String(day), total: String(dim) });

  if (!categories.length) {
    budgetList.innerHTML = `<p class="empty-hint">${t("noCategoriesHint")}</p>`;
    return;
  }

  const burn = periodBurn(currentPeriod);
  budgetList.innerHTML = "";
  groupByShelf(categories).forEach((group) => {
    const shelf = document.createElement("div");
    shelf.className = "shelf-group budget-shelf";
    shelf.innerHTML = `<span class="shelf-label">${escapeHtml(shelfLabelFor(group.tag))}</span>`;
    const board = document.createElement("div");
    board.className = "shelf-board";

    group.items.forEach((c) => {
      const row = document.createElement("div");

      const pct = c.target ? Math.min(100, (c.total / c.target) * 100) : 0;
      const amountsText = c.target != null
        ? `${formatMoney(c.total)} / ${formatMoney(c.target)}`
        : formatMoney(c.total);

      let paceClass = "";
      if (c.target != null) {
        const spendRatio = c.total / c.target;
        if (c.over_budget) paceClass = "pace-over";
        else if (spendRatio > burn) paceClass = "pace-behind";
        else paceClass = "pace-on";
      }
      row.className = `budget-row${paceClass ? " " + paceClass : ""}`;

      row.innerHTML = `
        <div class="budget-row-top">
          <span class="icon">${markHtml(c)}</span>
          <span class="name">${escapeHtml(c.name)}</span>
          <span class="amounts">${amountsText}</span>
          <button class="edit-btn" data-id="${c.id}"><svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.1"><path d="M11 2.5l2.5 2.5L5 13.5H2.5V11z" /></svg></button>
        </div>
        ${c.target != null ? `<div class="budget-bar-track"><div class="budget-bar-fill" style="width:${pct}%"></div><div class="budget-pace-marker" style="left:${Math.min(100, burn * 100)}%"></div></div>` : ""}
      `;
      row.querySelector(".edit-btn").addEventListener("click", () => openCategoryModal(c));
      board.appendChild(row);
      if (c.target != null) {
        const marker = row.querySelector(".budget-pace-marker");
        requestAnimationFrame(() => marker.classList.add("show"));
      }
    });

    shelf.appendChild(board);
    budgetList.appendChild(shelf);
  });
}

// --- Category add/edit modal ---

const categoryModal = document.getElementById("category-modal");
const categoryForm = document.getElementById("category-form");
const categoryError = document.getElementById("category-error");
const categoryDeleteBtn = document.getElementById("category-delete-btn");

document.getElementById("add-category-btn").addEventListener("click", () => openCategoryModal(null));
document.getElementById("category-cancel-btn").addEventListener("click", () => closeModal("category-modal"));

document.querySelectorAll("#category-tag-segmented button").forEach((btn) => {
  btn.addEventListener("click", () => {
    editingCategoryTag = btn.dataset.value;
    document.querySelectorAll("#category-tag-segmented button").forEach((b) => b.classList.toggle("active", b === btn));
  });
});

const categoryIconInput = document.getElementById("category-icon");
document.querySelectorAll("#category-mark-picker .mark-swatch").forEach((btn) => {
  btn.addEventListener("click", () => {
    categoryIconInput.value = btn.dataset.value;
    document.querySelectorAll("#category-mark-picker .mark-swatch").forEach((b) => b.classList.toggle("active", b === btn));
  });
});

function openCategoryModal(category) {
  editingCategoryId = category ? category.id : null;
  editingCategoryTag = (category && category.tag) || "";
  document.getElementById("category-modal-title").textContent = category ? t("editCategory") : t("newCategory");
  categoryIconInput.value = category ? markShapeFor(category) : "square";
  document.getElementById("category-name").value = category ? category.name : "";
  document.getElementById("category-target").value = category && category.target != null ? category.target : "";
  document.querySelectorAll("#category-tag-segmented button").forEach((b) => b.classList.toggle("active", b.dataset.value === editingCategoryTag));
  document.querySelectorAll("#category-mark-picker .mark-swatch").forEach((b) => b.classList.toggle("active", b.dataset.value === categoryIconInput.value));
  categoryDeleteBtn.classList.toggle("hidden", !category);
  categoryError.textContent = "";
  openModal("category-modal");
}

categoryForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  categoryError.textContent = "";

  const icon = categoryIconInput.value.trim();
  const name = document.getElementById("category-name").value.trim();
  const targetRaw = document.getElementById("category-target").value;
  const target = targetRaw === "" ? null : Number(targetRaw);

  try {
    if (editingCategoryId) {
      await apiFetch(`/api/budget/categories/${editingCategoryId}`, {
        method: "PUT",
        body: JSON.stringify({
          name,
          icon: icon || undefined,
          target,
          clear_target: target === null,
          tag: editingCategoryTag || undefined,
          clear_tag: editingCategoryTag === "",
        }),
      });
    } else {
      await apiFetch("/api/budget/categories", {
        method: "POST",
        body: JSON.stringify({ name, icon: icon || undefined, target, tag: editingCategoryTag || undefined }),
      });
    }
    closeModal("category-modal");
    loadBudget();
  } catch (err) {
    categoryError.textContent = err.message;
  }
});

categoryDeleteBtn.addEventListener("click", async () => {
  if (!editingCategoryId) return;
  if (!confirm(t("confirmDeleteCategory"))) return;
  try {
    await apiFetch(`/api/budget/categories/${editingCategoryId}`, { method: "DELETE" });
    closeModal("category-modal");
    loadBudget();
  } catch (err) {
    categoryError.textContent = err.message;
  }
});

// =========================================================================
// Entries (individual expenses, editable for any month - not just the
// current one, which is what actually makes a past month's budget editable)
// =========================================================================

const entriesList = document.getElementById("entries-list");
const entryModal = document.getElementById("entry-modal");
const entryForm = document.getElementById("entry-form");
const entryError = document.getElementById("entry-error");
const entryDeleteBtn = document.getElementById("entry-delete-btn");

async function loadEntries() {
  entriesList.innerHTML = `<p class="empty-hint">…</p>`;
  try {
    const entries = await apiFetch(`/api/expenses?period=${encodeURIComponent(currentPeriod)}`);
    renderEntries(entries);
  } catch (err) {
    entriesList.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
}

function renderEntries(entries) {
  if (!entries.length) {
    entriesList.innerHTML = `<p class="empty-hint">${t("noEntriesHint")}</p>`;
    return;
  }
  entriesList.innerHTML = "";
  entries.forEach((e) => {
    const row = document.createElement("div");
    row.className = "entry-row";
    row.innerHTML = `
      <span class="entry-date">${e.date.slice(5).replace("-", ".")}</span>
      <span class="icon">${markHtml({ icon: e.category_icon, id: e.category_id, name: e.category_name })}</span>
      <div class="entry-main">
        <div class="entry-category">${escapeHtml(e.category_name || t("uncategorized"))}</div>
        <div class="entry-meta">${e.note ? escapeHtml(e.note) : ""}</div>
      </div>
      <span class="entry-amount">${formatMoney(e.amount)}</span>
    `;
    row.addEventListener("click", () => openEntryModal(e));
    entriesList.appendChild(row);
  });
}

function defaultDateForCurrentPeriod() {
  const today = new Date();
  const todayPeriod = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}`;
  if (currentPeriod === todayPeriod) {
    return today.toISOString().slice(0, 10);
  }
  return `${currentPeriod}-15`;
}

function populateEntryCategorySelect(selectedId) {
  const select = document.getElementById("entry-category");
  select.innerHTML = currentCategories
    .map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`)
    .join("");
  if (selectedId != null) select.value = selectedId;
}

function openEntryModal(entry) {
  editingEntryId = entry ? entry.id : null;
  document.getElementById("entry-modal-title").textContent = entry ? t("editEntry") : t("newEntry");
  populateEntryCategorySelect(entry ? entry.category_id : (currentCategories[0] && currentCategories[0].id));
  document.getElementById("entry-amount").value = entry ? entry.amount : "";
  document.getElementById("entry-date").value = entry ? entry.date : defaultDateForCurrentPeriod();
  document.getElementById("entry-note").value = entry && entry.note ? entry.note : "";
  entryDeleteBtn.classList.toggle("hidden", !entry);
  entryError.textContent = "";
  openModal("entry-modal");
}

document.getElementById("add-entry-btn").addEventListener("click", () => openEntryModal(null));
document.getElementById("entry-cancel-btn").addEventListener("click", () => closeModal("entry-modal"));

entryForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  entryError.textContent = "";

  const amount = Number(document.getElementById("entry-amount").value);
  const category_id = Number(document.getElementById("entry-category").value);
  const date = document.getElementById("entry-date").value;
  const note = document.getElementById("entry-note").value.trim();

  try {
    if (editingEntryId) {
      await apiFetch(`/api/expenses/${editingEntryId}`, {
        method: "PUT",
        body: JSON.stringify({ amount, category_id, date, note }),
      });
    } else {
      await apiFetch("/api/expenses", {
        method: "POST",
        body: JSON.stringify({ amount, category_id, date, note: note || undefined }),
      });
    }
    closeModal("entry-modal");
    currentPeriod = date.slice(0, 7);
    periodInput.value = currentPeriod;
    loadBudget();
  } catch (err) {
    entryError.textContent = err.message;
  }
});

entryDeleteBtn.addEventListener("click", async () => {
  if (!editingEntryId) return;
  if (!confirm(t("confirmDeleteEntry"))) return;
  try {
    await apiFetch(`/api/expenses/${editingEntryId}`, { method: "DELETE" });
    closeModal("entry-modal");
    loadBudget();
  } catch (err) {
    entryError.textContent = err.message;
  }
});

// =========================================================================
// Graph
// =========================================================================

const graphChart = document.getElementById("graph-chart");
const graphTotal = document.getElementById("graph-total");
const yearLabel = document.getElementById("year-label");

document.getElementById("year-prev").addEventListener("click", () => { currentGraphYear--; loadGraph(); });
document.getElementById("year-next").addEventListener("click", () => { currentGraphYear++; loadGraph(); });

function monthAbbr(monthIndex) {
  return new Date(2000, monthIndex, 1).toLocaleDateString(localeForLang(), { month: "short" });
}

async function loadGraph() {
  yearLabel.textContent = currentGraphYear;
  graphChart.innerHTML = `<p class="empty-hint">…</p>`;
  try {
    const data = await apiFetch(`/api/budget/graph?year=${currentGraphYear}`);
    renderGraph(data.months);
  } catch (err) {
    graphChart.innerHTML = `<p class="error">${escapeHtml(err.message)}</p>`;
  }
}

function renderGraph(months) {
  const total = months.reduce((a, b) => a + b, 0);
  graphTotal.innerHTML = `${t("totalThisYear")} <strong>${formatMoney(total)}</strong>`;

  const max = Math.max(...months, 1);
  const avg = total / 12;
  const now = new Date();
  const isCurrentYear = now.getFullYear() === currentGraphYear;

  graphChart.innerHTML = "";
  months.forEach((amount, i) => {
    const col = document.createElement("div");
    col.className = `graph-bar-col${isCurrentYear && i === now.getMonth() ? " current" : ""}`;
    const heightPct = Math.max(2, (amount / max) * 100);
    col.innerHTML = `
      <span class="graph-bar-value">${amount > 0 ? Math.round(amount) : ""}</span>
      <div class="graph-bar" style="height:${heightPct}%"></div>
      <span class="graph-bar-label">${monthAbbr(i)}</span>
    `;
    graphChart.appendChild(col);
  });

  const heaviestIndex = months.reduce((best, v, i) => (v > months[best] ? i : best), 0);
  document.getElementById("graph-footer").innerHTML = months.some((v) => v > 0)
    ? `<span>${t("heaviestMonth")} — ${monthAbbr(heaviestIndex)} · <strong>${formatMoney(months[heaviestIndex])}</strong></span>
       <span>${t("statMonthlyAverage")} — <strong>${formatMoney(avg)}</strong></span>`
    : "";
}

// =========================================================================
// Boot
// =========================================================================

initSettingsUI();
initCurrencySelect();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("./sw.js").catch(() => {});
  });
}

if (getToken()) {
  afterLogin();
} else {
  showAuthScreen();
}
