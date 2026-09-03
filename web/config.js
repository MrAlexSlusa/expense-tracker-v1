// Backend API base URL.
//
// Empty string = same origin, no prefix - correct when this folder is
// served by the FastAPI app itself (e.g. local dev via `uvicorn`, mounted
// at /app). When this folder is hosted separately - e.g. on GitHub Pages -
// point this at the deployed backend instead, e.g.:
//   window.API_BASE_URL = "https://expense-tracker.onrender.com";
window.API_BASE_URL = "https://expense-tracker-7mnp.onrender.com";
