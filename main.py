"""Cloud-Based AI Attendance System - FastAPI application entry point."""
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api import attendance, auth, courses, reports, students, system
from core import face_engine
from database import models  # noqa: F401  (registers the tables)
from database.connection import Base, engine

BASE_DIR = Path(__file__).parent
Base.metadata.create_all(bind=engine)


def _warm_up_face_engine():
    try:
        face_engine.get_engine()
        print("Face engine ready:", face_engine.engine_status()["name"])
    except Exception as e:
        print("Face engine NOT ready:", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load / download the face models in the background so the server starts instantly.
    threading.Thread(target=_warm_up_face_engine, daemon=True).start()
    yield


app = FastAPI(title="AI Attendance System",
              description="Cloud-based, camera-driven student attendance with face recognition.",
              version="2.0.0", lifespan=lifespan)

for module in (auth, students, courses, attendance, reports, system):
    app.include_router(module.router, prefix="/api")

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def _page(name: str) -> FileResponse:
    return FileResponse(BASE_DIR / "templates" / name, headers={"Cache-Control": "no-store"})


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/login")


@app.get("/login", include_in_schema=False)
def login_page():
    return _page("login.html")


@app.get("/teacher", include_in_schema=False)
def teacher_page():
    return _page("teacher.html")


@app.get("/student", include_in_schema=False)
def student_page():
    return _page("student.html")


@app.get("/health", include_in_schema=False)
def health():
    return {"status": "healthy"}
