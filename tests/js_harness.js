/*
 * Loads web/i18n.js and web/app.js into a stubbed browser environment so their
 * pure logic can be asserted from pytest, then evaluates the expression given
 * as argv[2] and prints the result as JSON.
 *
 * Both files are plain scripts written for a browser: they read the DOM at load
 * time, attach listeners and run boot code. Rather than restructure working
 * code to make it importable - which would be changing the app to suit the
 * tests - this fakes just enough of a browser for them to finish loading. The
 * stubs are deliberately dumb: any test that needs real DOM behaviour is
 * testing the wrong layer and belongs in an end-to-end run instead.
 *
 * Node only, no dependencies, so `pytest` stays the single command to run
 * everything and web/ keeps its no-build-step property.
 */

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "web");

function fakeElement() {
  const el = {
    value: "",
    checked: false,
    textContent: "",
    innerHTML: "",
    placeholder: "",
    disabled: false,
    dataset: {},
    style: {},
    childNodes: [],
    classList: {
      _set: new Set(),
      add(c) { this._set.add(c); },
      remove(c) { this._set.delete(c); },
      contains(c) { return this._set.has(c); },
      toggle(c, on) { on ? this._set.add(c) : this._set.delete(c); },
    },
    addEventListener() {},
    removeEventListener() {},
    setAttribute() {},
    getAttribute() { return null; },
    focus() {},
    scrollIntoView() {},
    setSelectionRange() {},
    getBoundingClientRect() { return { x: 0, y: 0, width: 0, height: 0 }; },
    querySelector() { return fakeElement(); },
    querySelectorAll() { return []; },
    closest() { return null; },
    appendChild() {},
  };
  return el;
}

function makeStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => map.set(k, String(v)),
    removeItem: (k) => map.delete(k),
    clear: () => map.clear(),
    get length() { return map.size; },
  };
}

const documentStub = {
  documentElement: fakeElement(),
  body: fakeElement(),
  getElementById: () => fakeElement(),
  querySelector: () => fakeElement(),
  querySelectorAll: () => [],
  addEventListener: () => {},
  createElement: () => fakeElement(),
};

const windowStub = {
  location: { href: "https://example.test/app/", hash: "", pathname: "/app/", search: "", hostname: "example.test" },
  matchMedia: () => ({ matches: false, addEventListener: () => {} }),
  addEventListener: () => {},
  history: { replaceState: () => {} },
  API_BASE_URL: "https://api.test",
};

const sandbox = {
  window: windowStub,
  document: documentStub,
  localStorage: makeStorage(),
  sessionStorage: makeStorage(),
  // Empty, so the `"serviceWorker" in navigator` guard at boot is false.
  navigator: {},
  history: windowStub.history,
  location: windowStub.location,
  Node: { TEXT_NODE: 3 },
  console,
  setTimeout,
  clearTimeout,
  setInterval,
  clearInterval,
  Response,
  URLSearchParams,
  // Answering with an empty provider list keeps loadOauthProviders() from
  // retrying with backoff, which would leave timers pending and hang the run.
  fetch: async () => ({ ok: true, status: 200, json: async () => ({ providers: [] }) }),
};
sandbox.globalThis = sandbox;
vm.createContext(sandbox);

for (const file of ["i18n.js", "app.js"]) {
  vm.runInContext(fs.readFileSync(path.join(WEB, file), "utf8"), sandbox, { filename: file });
}

const result = vm.runInContext(
  `(() => { ${process.argv[2]} })()`,
  sandbox,
  { filename: "expression" }
);
process.stdout.write(JSON.stringify(result === undefined ? null : result));
process.exit(0);
