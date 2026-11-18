import re

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import settings
from core import face_engine
from core.face_engine import FaceEngineError
from core.security import hash_password, require_teacher
from database.connection import get_db
from database.models import (Attendance, Enrollment, FaceEmbedding, Student, User)

router = APIRouter(prefix="/students", tags=["Students & face enrolment"])
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class StudentIn(BaseModel):
    student_code: str = Field(min_length=1, max_length=30)
    full_name: str = Field(min_length=2, max_length=100)
    email: str
    department: str = ""
    password: str = Field(default="", max_length=72)  # blank = same as student code


class FacesIn(BaseModel):
    images: list[str] = Field(min_length=1, max_length=10)


def student_dict(s: Student, faces: int = 0, courses: int = 0) -> dict:
    return {"id": s.id, "student_code": s.student_code, "full_name": s.full_name, "email": s.email,
            "department": s.department, "face_count": faces, "course_count": courses}


@router.post("", status_code=201)
def create_student(data: StudentIn, db: Session = Depends(get_db), _=Depends(require_teacher)):
    code = data.student_code.strip()
    if not EMAIL_RE.match(data.email.strip()):
        raise HTTPException(422, "Enter a valid email address.")
    username = code.lower()
    if db.query(Student).filter(Student.student_code == code).first() or \
            db.query(User).filter(User.username == username).first():
        raise HTTPException(409, f"A user with the ID '{code}' already exists.")
    if data.password and len(data.password) < 6:
        raise HTTPException(422, "Password must be at least 6 characters.")
    password = data.password or code  # blank = the student ID (they can change it after signing in)
    user = User(username=username, hashed_password=hash_password(password), role="student",
                full_name=data.full_name.strip())
    db.add(user)
    db.flush()
    s = Student(user_id=user.id, student_code=code, full_name=data.full_name.strip(),
                email=data.email.strip(), department=data.department.strip())
    db.add(s)
    db.commit()
    return student_dict(s)


@router.get("")
def list_students(db: Session = Depends(get_db), _=Depends(require_teacher)):
    faces = dict(db.query(FaceEmbedding.student_id, func.count()).group_by(FaceEmbedding.student_id).all())
    courses = dict(db.query(Enrollment.student_id, func.count()).group_by(Enrollment.student_id).all())
    rows = db.query(Student).order_by(Student.full_name).all()
    return [student_dict(s, faces.get(s.id, 0), courses.get(s.id, 0)) for s in rows]


@router.delete("/{student_id}")
def delete_student(student_id: int, db: Session = Depends(get_db), _=Depends(require_teacher)):
    s = db.get(Student, student_id)
    if not s:
        raise HTTPException(404, "Student not found.")
    for model in (FaceEmbedding, Attendance, Enrollment):
        db.query(model).filter(model.student_id == s.id).delete()
    db.query(User).filter(User.id == s.user_id).delete()
    db.delete(s)
    db.commit()
    return {"message": "Student deleted."}


@router.post("/{student_id}/faces")
def enrol_faces(student_id: int, data: FacesIn, db: Session = Depends(get_db), _=Depends(require_teacher)):
    """Save face photos for a student. Each photo must contain exactly one clear face."""
    s = db.get(Student, student_id)
    if not s:
        raise HTTPException(404, "Student not found.")
    try:
        engine = face_engine.get_engine()
    except FaceEngineError as e:
        raise HTTPException(503, str(e))

    saved, problems = 0, []
    for n, image in enumerate(data.images, start=1):
        try:
            img = face_engine.decode_image(image)
            faces = engine.detect(img)
            if not faces:
                problems.append(f"Photo {n}: no face found. Face the camera in good light.")
            elif len(faces) > 1:
                problems.append(f"Photo {n}: more than one face. Only the student should be in the photo.")
            elif faces[0]["w"] < face_engine.MIN_FACE_PX:
                problems.append(f"Photo {n}: face too small. Move closer to the camera.")
            else:
                vec = engine.embed(img, faces[0])
                db.add(FaceEmbedding(student_id=s.id, vector=vec.astype(np.float32).tobytes()))
                saved += 1
        except FaceEngineError as e:
            problems.append(f"Photo {n}: {e}")
    db.commit()

    # keep only the newest MAX_FACES_PER_STUDENT embeddings
    rows = db.query(FaceEmbedding).filter(FaceEmbedding.student_id == s.id).order_by(FaceEmbedding.id.desc()).all()
    for old in rows[settings.MAX_FACES_PER_STUDENT:]:
        db.delete(old)
    db.commit()
    total = db.query(FaceEmbedding).filter(FaceEmbedding.student_id == s.id).count()
    return {"saved": saved, "problems": problems, "face_count": total}


@router.delete("/{student_id}/faces")
def clear_faces(student_id: int, db: Session = Depends(get_db), _=Depends(require_teacher)):
    if not db.get(Student, student_id):
        raise HTTPException(404, "Student not found.")
    db.query(FaceEmbedding).filter(FaceEmbedding.student_id == student_id).delete()
    db.commit()
    return {"message": "Face data removed."}
