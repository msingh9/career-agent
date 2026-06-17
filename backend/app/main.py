from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, SessionLocal, engine
from .routes import router
from .services.companies import ensure_target_company_schema, seed_default_companies
from .services.apply_schema import ensure_apply_schema
from .services.job_description import enrich_job_description
from .services.job_description_schema import ensure_job_description_schema

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_target_company_schema()
    ensure_job_fit_schema()
    ensure_apply_schema()
    ensure_job_description_schema()
    db = SessionLocal()
    try:
        seed_default_companies(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Semiconductor Career Agent",
    description="Track VP/Senior Director semiconductor job search",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

if STATIC_DIR.exists():
    assets_dir = STATIC_DIR / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")
