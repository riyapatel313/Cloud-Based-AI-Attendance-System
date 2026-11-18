from datetime import date, datetime

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from api.courses import owned_course
from config import settings
from core import face_engine
from core.face_engine import FaceEngineError
from core.security import require_teacher
from database.connection import get_db
from database.models import (Attendance, ClassSession, Course, Enrollment,
                             FaceEmbedding, Student, User)

router = APIRouter(prefix="/sessions", tags=["Attendance"])
PRESENT_LIKE = ("present", "late")


class StartIn(BaseModel):
    course_id: int


class ImageIn(BaseModel):
    image: str


class MarkIn(BaseModel):
    student_id: int
    status: str  # present | late | absent


def owned_session(db: Session, session_id: int, teacher: User) -> ClassSession:
    s = db.get(ClassSession, session_id)
    if not s:
        raise HTTPException(404, "Session not found.")
    owned_course(db, s.course_id, teacher)
    return s


def session_dict(db: Session, s: ClassSession) -> dict:
    c = db.get(Course, s.course_id)
    present = db.query(Attendance).filter(Attendance.session_id == s.id, Attendance.status.in_(PRESENT_LIKE)).count()
    enrolled = db.query(Enrollment).filter(Enrollment.course_id == s.course_id).count()
    return {"id": s.id, "course_id": s.course_id, "course_code": c.code, "course_name": c.name,
            "date": s.date.isoformat(), "started_at": s.started_at.isoformat(),
            "ended_at": s.ended_at.isoformat() if s.ended_at else None,
            "present_count": present, "enrolled_count": enrolled}


def roster(db: Session, s: ClassSession) -> list[dict]:
    students = (db.query(Student).join(Enrollment, Enrollment.student_id == Student.id)
                .filter(Enrollment.course_id == s.course_id).order_by(Student.full_name).all())
    marks = {a.student_id: a for a in db.query(Attendance).filter(Attendance.session_id == s.id)}
    out = []
    for st in students:
        a = marks.get(st.id)
        out.append({"student_id": st.id, "student_code": st.student_code, "full_name": st.full_name,
                    "status": a.status if a else "not_marked",
                    "confidence": round(a.confidence, 3) if a and a.confidence is not None else None,
                    "marked_by": a.marked_by if a else None,
                    "time": a.timestamp.isoformat() if a else None})
    return out


def upsert(db: Session, session_id: int, student_id: int, status: str, by: str, conf: float | None = None):
    a = db.query(Attendance).filter(Attendance.session_id == session_id, Attendance.student_id == student_id).first()
    if a is None:
        a = Attendance(session_id=session_id, student_id=student_id)
        db.add(a)
    a.status, a.marked_by, a.confidence, a.timestamp = status, by, conf, datetime.now()
    return a


@router.post("/start")
def start_session(data: StartIn, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """Start today's session for a class, or resume it if it already exists."""
    course = owned_course(db, data.course_id, teacher)
    if db.query(Enrollment).filter(Enrollment.course_id == course.id).count() == 0:
        raise HTTPException(400, "This class has no students yet. Add students to the class first.")
    s = db.query(ClassSession).filter(ClassSession.course_id == course.id, ClassSession.date == date.today()).first()
    if s is None:
        s = ClassSession(course_id=course.id, date=date.today())
        db.add(s)
    s.ended_at = None
    db.commit()
    return {"session": session_dict(db, s), "roster": roster(db, s)}


@router.get("")
def list_sessions(course_id: int | None = None, limit: int = 50, db: Session = Depends(get_db),
                  teacher: User = Depends(require_teacher)):
    q = (db.query(ClassSession).join(Course, Course.id == ClassSession.course_id)
         .filter(Course.teacher_id == teacher.id))
    if course_id:
        q = q.filter(ClassSession.course_id == course_id)
    rows = q.order_by(ClassSession.date.desc(), ClassSession.id.desc()).limit(min(limit, 200)).all()
    return [session_dict(db, s) for s in rows]


@router.get("/{session_id}")
def get_session(session_id: int, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    s = owned_session(db, session_id, teacher)
    return {"session": session_dict(db, s), "roster": roster(db, s)}


@router.post("/{session_id}/end")
def end_session(session_id: int, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """Finish the session: everyone who was not marked becomes absent."""
    s = owned_session(db, session_id, teacher)
    for r in roster(db, s):
        if r["status"] == "not_marked":
            upsert(db, s.id, r["student_id"], "absent", "auto")
    s.ended_at = datetime.now()
    db.commit()
    return {"session": session_dict(db, s), "roster": roster(db, s)}


@router.delete("/{session_id}")
def delete_session(session_id: int, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    s = owned_session(db, session_id, teacher)
    db.query(Attendance).filter(Attendance.session_id == s.id).delete()
    db.delete(s)
    db.commit()
    return {"message": "Session deleted."}


@router.post("/{session_id}/mark")
def mark_manually(session_id: int, data: MarkIn, db: Session = Depends(get_db),
                  teacher: User = Depends(require_teacher)):
    s = owned_session(db, session_id, teacher)
    if data.status not in ("present", "late", "absent"):
        raise HTTPException(422, "Status must be present, late or absent.")
    if not db.query(Enrollment).filter(Enrollment.course_id == s.course_id,
                                       Enrollment.student_id == data.student_id).first():
        raise HTTPException(400, "That student is not in this class.")
    upsert(db, s.id, data.student_id, data.status, "manual")
    db.commit()
    return {"session": session_dict(db, s), "roster": roster(db, s)}


@router.post("/{session_id}/recognize")
def recognize(session_id: int, data: ImageIn, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    """Receive one camera frame, find every face, identify students and mark them present."""
    s = owned_session(db, session_id, teacher)
    if s.ended_at:
        raise HTTPException(400, "This session has ended. Start it again to resume.")
    try:
        engine = face_engine.get_engine()
        img = face_engine.decode_image(data.image)
        faces = engine.detect(img)
    except FaceEngineError as e:
        raise HTTPException(503 if "model" in str(e).lower() else 400, str(e))
    if not faces:
        return {"faces": [], "newly_marked": 0}

    rows = db.query(FaceEmbedding.student_id, FaceEmbedding.vector).all()
    ids = np.array([r[0] for r in rows], dtype=np.int64)
    matrix = (np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
              if rows else np.zeros((0, 128), dtype=np.float32))
    enrolled = {e.student_id for e in db.query(Enrollment).filter(Enrollment.course_id == s.course_id)}
    already = {a.student_id: a.status for a in db.query(Attendance).filter(Attendance.session_id == s.id)}
    names = {st.id: st for st in db.query(Student).filter(Student.id.in_(set(ids.tolist()) or {0}))}

    h, w = img.shape[:2]
    results, newly, seen = [], 0, set()
    for f in faces:
        vec = engine.embed(img, f)
        sid, score = face_engine.best_match(vec, ids, matrix)
        item = {"x": f["x"] / w, "y": f["y"] / h, "w": f["w"] / w, "h": f["h"] / h,
                "score": round(score, 3), "status": "unknown", "name": "Unknown", "student_code": None}
        if sid is not None and score >= settings.COSINE_THRESHOLD:
            st = names[sid]
            item.update(name=st.full_name, student_code=st.student_code)
            if sid not in enrolled:
                item["status"] = "not_in_class"
            elif sid in seen or already.get(sid) in PRESENT_LIKE:
                item["status"] = "already"
            else:
                upsert(db, s.id, sid, "present", "face", score)
                item["status"] = "marked"
                newly += 1
            seen.add(sid)
        results.append(item)
    db.commit()
    return {"faces": results, "newly_marked": newly}
