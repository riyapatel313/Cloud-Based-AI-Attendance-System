from fastapi import APIRouter

from core import face_engine

router = APIRouter(prefix="/system", tags=["System"])


@router.get("/status")
def status():
    return {"status": "healthy", "face_engine": face_engine.engine_status()}
