# Copyright 2026 Manish Singh
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import Base, SessionLocal, engine
from .models import User
from .routes import router
from .services.companies import ensure_target_company_schema, seed_default_companies
from .services.apply_schema import ensure_apply_schema
from .services.job_description_schema import ensure_job_description_schema
from .services.job_fit import ensure_job_fit_schema
from .services.job_schema import ensure_job_dedup_schema
from .services.user_schema import ensure_user_schema

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    ensure_target_company_schema()
    ensure_job_fit_schema()
    ensure_apply_schema()
    ensure_job_description_schema()
    ensure_user_schema()
    ensure_job_dedup_schema()
    db = SessionLocal()
    try:
        for user in db.query(User).all():
            seed_default_companies(db, user.id)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Career Agent",
    description="Track and manage your job search",
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
