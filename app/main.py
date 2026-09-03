from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.database import Base, engine, ensure_columns
from app import webhook, api

load_dotenv()  # picks up RESEND_API_KEY etc. from a local .env before anything reads os.environ

Base.metadata.create_all(bind=engine)
# Added after the first deploy, so databases created before it need the
# column backfilled - create_all only ever creates whole tables.
ensure_columns(table="expenses", columns={"account_id": "INTEGER"})

app = FastAPI(title="WhatsApp Expense Tracker")

# CORS stays open for now so a future native app (different origin, or none
# at all on iOS/Android) can call the same API without extra config.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook.router)
app.include_router(api.router)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.is_dir():
    app.mount("/app", StaticFiles(directory=WEB_DIR, html=True), name="web")


@app.get("/")
def health_check():
    return {"status": "running"}
