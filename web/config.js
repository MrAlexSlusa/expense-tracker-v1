// Backend API base URL.
//
// Empty string = same origin, no prefix - correct when this folder is served
// by the FastAPI app itself (local dev via `uvicorn`, mounted at /app). When
// it's hosted separately - GitHub Pages - it has to point at the deployed
// backend instead.
//
// Getting this wrong is the classic "frontend deployed fine but nothing
// loads" failure, so rather than a single hardcoded value that's right in
// only one of the two places, it picks by where the page is being served
// from: localhost talks to whatever is serving it, anything else talks to
// the deployed backend below. Update DEPLOYED_API_URL after the backend's
// first deploy - Render assigns a random suffix, so it can't be guessed
// ahead of time.
const DEPLOYED_API_URL = "https://expense-tracker-7mnp.onrender.com";

const isLocal = ["localhost", "127.0.0.1", "[::1]"].includes(window.location.hostname);
window.API_BASE_URL = isLocal ? "" : DEPLOYED_API_URL;
