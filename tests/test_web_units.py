"""
Unit tests for the pure logic in web/, which until now was only ever verified
by hand in a browser.

These cover the parts where a silent regression would be worst and least
visible: money formatting, the date ranges every screen filters on, which
period Analytics opens with, where the sign-in token is stored, HTML escaping,
and whether the four translation tables actually agree with each other.

They run through tests/js_harness.js, which loads the real web/i18n.js and
web/app.js in Node against a stub DOM - no test framework in the browser, no
node_modules, no build step, and `pytest` still runs everything.

What this deliberately does NOT cover: rendering, event wiring, sheets, or
anything needing a real DOM. That is an end-to-end job, and pretending to
test it against these stubs would give false confidence.
"""

import json
import os
import shutil
import subprocess

import pytest

HARNESS = os.path.join(os.path.dirname(__file__), "js_harness.js")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None,
    reason="Node isn't installed; the web/ unit tests need it to run browser code",
)


def js(expression: str):
    """Evaluates `expression` (a JS function body ending in `return`) inside the app."""
    proc = subprocess.run(
        ["node", HARNESS, expression],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    if proc.returncode != 0:
        raise AssertionError(f"harness failed:\n{proc.stderr.strip()}")
    return json.loads(proc.stdout)


# --- money -----------------------------------------------------------------


def test_currency_sits_on_the_correct_side_of_the_amount():
    out = js("""
      const at = (code, n) => { currentCurrency = code; return fmt(n); };
      return { usd: at("USD", 9), eur: at("EUR", 9), gbp: at("GBP", 9),
               ron: at("RON", 9), ronBig: at("RON", 1234.5) };
    """)
    assert out["usd"] == "$9"
    assert out["eur"] == "\u20ac9"
    assert out["gbp"] == "\u00a39"
    # The whole point of the change: lei goes after the number, with a space.
    assert out["ron"] == "9 lei"
    assert out["ronBig"].endswith(" lei") and out["ronBig"].startswith("1,234.5")


def test_whole_amounts_lose_the_decimals_and_real_cents_keep_them():
    out = js("""
      currentCurrency = "USD";
      return { whole: fmt(50), cents: fmt(12.5), rounding: fmt(0.004), zero: fmt(0),
               negative: fmt(-30), notANumber: fmt(undefined) };
    """)
    assert out["whole"] == "$50"
    assert out["cents"] == "$12.50"
    assert out["rounding"] == "$0"        # under half a cent reads as whole
    assert out["zero"] == "$0"
    assert out["negative"] == "-$30" or out["negative"] == "$-30"
    assert out["notANumber"] == "$0"      # never renders "$NaN"


def test_an_unknown_currency_code_falls_back_to_showing_the_code():
    assert js('return currencySymbol("XYZ");') == "XYZ"
    assert js('return currencySymbol("RON");') == "lei"


def test_thousands_are_abbreviated_for_chart_axes():
    out = js('return { k: fmtK(1500), flat: fmtK(2000), small: fmtK(100) };')
    assert out["k"] == "1.5k"
    assert out["flat"] == "2k"       # the trailing .0 is dropped
    assert out["small"] == "0.1k"


# --- date ranges -----------------------------------------------------------


def test_each_period_covers_the_range_it_claims():
    out = js("""
      const iso = (d) => isoDate(d);
      const on = new Date(2026, 5, 17);  // Wednesday 17 June 2026
      const r = (p) => { const x = rangeFor(p, on); return [iso(x.start), iso(x.end)]; };
      return { daily: r("Daily"), weekly: r("Weekly"), monthly: r("Monthly"),
               yearly: r("Yearly"), last12: r("Last 12 months") };
    """)
    assert out["daily"] == ["2026-06-17", "2026-06-17"]
    assert out["weekly"] == ["2026-06-15", "2026-06-21"]   # Monday-first week
    assert out["monthly"] == ["2026-06-01", "2026-06-30"]  # month end, not day+30
    assert out["yearly"] == ["2026-01-01", "2026-12-31"]
    assert out["last12"] == ["2025-07-01", "2026-06-30"]   # 12 months inclusive


def test_a_month_range_ends_on_the_real_last_day_including_february():
    out = js("""
      const end = (y, m) => isoDate(rangeFor("Monthly", new Date(y, m, 5)).end);
      return { feb2026: end(2026, 1), feb2028: end(2028, 1), apr: end(2026, 3) };
    """)
    assert out["feb2026"] == "2026-02-28"
    assert out["feb2028"] == "2028-02-29"   # leap year
    assert out["apr"] == "2026-04-30"


def test_analytics_opens_with_no_period_and_therefore_no_lower_bound():
    """The default this session changed: Analytics starts on everything, not 12 months."""
    out = js("""
      state.analyticsPeriod = null;
      const all = analyticsRange();
      state.analyticsPeriod = "Monthly";
      const narrowed = analyticsRange();
      state.analyticsPeriod = null;
      return { defaultPeriod: state.analyticsPeriod,
               allTimeStartYear: all.start.getFullYear(),
               narrowedStart: isoDate(narrowed.start) };
    """)
    assert out["defaultPeriod"] is None
    assert out["allTimeStartYear"] == 1970          # i.e. no lower bound
    assert narrowed_is_a_month(out["narrowedStart"])


def narrowed_is_a_month(iso_date: str) -> bool:
    return iso_date.endswith("-01")


def test_the_analytics_period_is_separate_from_the_other_tabs():
    """Narrowing Analytics must not drag Activity and Budget along with it."""
    out = js("""
      state.period = "Monthly";
      state.analyticsPeriod = "Yearly";
      const activity = rangeFor(state.period, new Date(2026, 5, 17));
      const analytics = analyticsRange();
      state.analyticsPeriod = null;
      return { activity: isoDate(activity.start), analytics: isoDate(analytics.start) };
    """)
    assert out["activity"] == "2026-06-01"
    assert out["analytics"] == "2026-01-01"


# --- chart bucketing -------------------------------------------------------


def test_short_ranges_bucket_by_day_and_long_ones_by_month():
    out = js("""
      const series = (start, end, expenses) =>
        seriesFor({ start: new Date(start), end: new Date(end) }, expenses || []);
      const month = series("2026-06-01", "2026-06-30");
      const year = series("2026-01-01", "2026-12-31");
      return { monthByMonth: month.byMonth, monthBuckets: month.buckets.length,
               yearByMonth: year.byMonth, yearBuckets: year.buckets.length };
    """)
    assert out["monthByMonth"] is False and out["monthBuckets"] == 30
    # A year would be 365 unreadable bars, so it collapses to 12.
    assert out["yearByMonth"] is True and out["yearBuckets"] == 12


def test_expenses_land_in_the_right_bucket_and_the_total_is_preserved():
    out = js("""
      const s = seriesFor(
        { start: new Date(2026, 5, 1), end: new Date(2026, 5, 30) },
        [{ date: "2026-06-01", amount: 10 }, { date: "2026-06-01", amount: 5 },
         { date: "2026-06-30", amount: 7 }, { date: "2026-07-15", amount: 999 }]);
      return { first: s.buckets[0].value, last: s.buckets[s.buckets.length - 1].value,
               total: s.buckets.reduce((a, b) => a + b.value, 0) };
    """)
    assert out["first"] == 15    # same-day expenses add together
    assert out["last"] == 7
    assert out["total"] == 22    # the out-of-range expense is excluded, not clamped in


# --- session storage -------------------------------------------------------


def test_save_my_login_info_decides_which_store_holds_the_token():
    out = js("""
      localStorage.clear(); sessionStorage.clear();
      setRememberMe(true); setToken("tok-remembered");
      const on = { local: localStorage.getItem(TOKEN_KEY), session: sessionStorage.getItem(TOKEN_KEY),
                   read: getToken() };

      localStorage.clear(); sessionStorage.clear();
      setRememberMe(false); setToken("tok-session");
      const off = { local: localStorage.getItem(TOKEN_KEY), session: sessionStorage.getItem(TOKEN_KEY),
                    read: getToken() };
      return { on, off };
    """)
    assert out["on"]["local"] == "tok-remembered" and out["on"]["session"] is None
    assert out["off"]["session"] == "tok-session" and out["off"]["local"] is None
    # Either way the app finds it - reads check both stores.
    assert out["on"]["read"] == "tok-remembered" and out["off"]["read"] == "tok-session"


def test_turning_the_switch_off_rehomes_a_live_session_instead_of_dropping_it():
    """Flipping it mid-session must not log the user out."""
    out = js("""
      localStorage.clear(); sessionStorage.clear();
      setRememberMe(true); setToken("live-token");
      setRememberMe(false);
      const afterOff = { token: getToken(), local: localStorage.getItem(TOKEN_KEY),
                         session: sessionStorage.getItem(TOKEN_KEY) };
      setRememberMe(true);
      const afterOn = { token: getToken(), local: localStorage.getItem(TOKEN_KEY) };
      return { afterOff, afterOn };
    """)
    assert out["afterOff"]["token"] == "live-token"      # still signed in
    assert out["afterOff"]["session"] == "live-token"    # moved, not deleted
    assert out["afterOff"]["local"] is None
    assert out["afterOn"]["token"] == "live-token"       # and back again
    assert out["afterOn"]["local"] == "live-token"


def test_the_remembered_email_is_forgotten_when_the_switch_goes_off():
    out = js("""
      localStorage.clear(); sessionStorage.clear();
      setRememberMe(true); rememberEmail("someone@example.com");
      const kept = rememberedEmail();
      setRememberMe(false);
      const afterOff = rememberedEmail();
      rememberEmail("another@example.com");   // must not write while off
      return { kept, afterOff, whileOff: rememberedEmail(),
               stored: localStorage.getItem(REMEMBERED_EMAIL_KEY) };
    """)
    assert out["kept"] == "someone@example.com"
    assert out["afterOff"] == ""
    assert out["whileOff"] == ""
    assert out["stored"] is None


def test_logging_out_clears_the_token_from_both_stores():
    out = js("""
      localStorage.clear(); sessionStorage.clear();
      setRememberMe(true); setToken("a");
      setRememberMe(false); setToken("b");
      localStorage.setItem(TOKEN_KEY, "stale-leftover");  // both populated at once
      clearToken();
      return { token: getToken(), local: localStorage.getItem(TOKEN_KEY),
               session: sessionStorage.getItem(TOKEN_KEY) };
    """)
    assert out["token"] is None and out["local"] is None and out["session"] is None


# --- escaping --------------------------------------------------------------


def test_user_text_is_escaped_before_it_reaches_innerHTML():
    """Notes and category names are interpolated into HTML strings by hand."""
    out = js("""
      return { tag: esc("<script>alert(1)</script>"),
               attr: esc('" onmouseover="evil()'),
               amp: esc("Tom & Jerry"), quote: esc("it's"),
               empty: esc(""), nullish: esc(null), undef: esc(undefined) };
    """)
    assert "<" not in out["tag"] and ">" not in out["tag"]
    assert out["tag"] == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert '"' not in out["attr"]
    assert out["amp"] == "Tom &amp; Jerry"
    assert out["quote"] == "it&#39;s"
    # Missing values render as nothing, not the words "null"/"undefined".
    assert out["empty"] == "" and out["nullish"] == "" and out["undef"] == ""


# --- translations ----------------------------------------------------------


def test_every_language_defines_the_same_keys():
    """
    A key missing from one language renders as the raw key - which happened in
    this project ("allTime" showing instead of "All time"). Four tables edited
    by hand drift silently, so compare them.
    """
    out = js("""
      const langs = Object.keys(TRANSLATIONS);
      const en = Object.keys(TRANSLATIONS.en).sort();
      const missing = {}, extra = {};
      langs.forEach((l) => {
        const keys = Object.keys(TRANSLATIONS[l]);
        const gone = en.filter((k) => !keys.includes(k));
        const spare = keys.filter((k) => !en.includes(k));
        if (gone.length) missing[l] = gone;
        if (spare.length) extra[l] = spare;
      });
      return { langs, missing, extra, count: en.length };
    """)
    assert out["langs"] == ["en", "es", "fr", "ro"]
    assert out["missing"] == {}, f"languages missing keys: {out['missing']}"
    assert out["extra"] == {}, f"languages with keys English lacks: {out['extra']}"
    assert out["count"] > 100


def test_every_period_has_a_translation_key_that_resolves():
    """periodKey() maps the period list to i18n keys; an unmapped one renders raw."""
    out = js("""
      setLang("en");
      const rows = PERIODS.map((p) => ({ period: p, key: periodKey(p), text: t(periodKey(p)) }));
      return { rows, allTime: t("allTime") };
    """)
    for row in out["rows"]:
        assert row["key"], f"no i18n key for period {row['period']}"
        # If a key is missing from the table, t() returns the key itself.
        assert row["text"] != row["key"], f"period {row['period']} renders as a raw key"
    assert out["allTime"] == "All time"


def test_a_backend_error_string_maps_to_a_translated_message():
    """
    These map exact strings the API returns. If a message is reworded on one
    side only, the user sees raw English - and the delete flow depends on it.
    """
    out = js("""
      setLang("en");
      return { password: translateError("Incorrect password"),
               exists: translateError("An account with this email already exists"),
               unmapped: translateError("Some brand new server message") };
    """)
    assert out["password"] == "Incorrect password"
    assert out["exists"] == "An account with this email already exists"
    # Anything unmapped falls through unchanged rather than blanking out.
    assert out["unmapped"] == "Some brand new server message"


def test_translated_strings_interpolate_their_variables():
    out = js("""
      setLang("en");
      return { provider: t("continueWithProvider", { provider: "Google" }),
               missingVar: t("continueWithProvider") };
    """)
    assert out["provider"] == "Continue with Google"
    assert "{provider}" in out["missingVar"]  # honest placeholder, not a crash
