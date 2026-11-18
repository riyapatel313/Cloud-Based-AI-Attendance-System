from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.security import get_current_user, require_teacher
from database.connection import get_db
from database.models import (Attendance, ClassSession, Course, Enrollment,
                             Student, User)

router = APIRouter(prefix="/courses", tags=["Classes"])


class CourseIn(BaseModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=2, max_length=120)
    room: str = Field(default="", max_length=30)


class EnrollIn(BaseModel):
    student_ids: list[int]


def owned_course(db: Session, course_id: int, teacher: User) -> Course:
    c = db.get(Course, course_id)
    if not c or c.teacher_id != teacher.id:
        raise HTTPException(404, "Class not found.")
    return c


@router.post("", status_code=201)
def create_course(data: CourseIn, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    code = data.code.strip().upper()
    if db.query(Course).filter(Course.code == code).first():
        raise HTTPException(409, f"A class with code {code} already exists.")
    c = Course(code=code, name=data.name.strip(), room=data.room.strip(), teacher_id=teacher.id)
    db.add(c)
    db.commit()
    return {"id": c.id, "code": c.code, "name": c.name, "room": c.room, "student_count": 0}


@router.get("")
def list_courses(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    if user.role == "teacher":
        courses = db.query(Course).filter(Course.teacher_id == user.id).order_by(Course.code).all()
    else:
        courses = (db.query(Course).join(Enrollment, Enrollment.course_id == Course.id)
                   .join(Student, Student.id == Enrollment.student_id)
                   .filter(Student.user_id == user.id).order_by(Course.code).all())
    counts = dict(db.query(Enrollment.course_id, func.count()).group_by(Enrollment.course_id).all())
    return [{"id": c.id, "code": c.code, "name": c.name, "room": c.room, "student_count": counts.get(c.id, 0)}
            for c in courses]


@router.delete("/{course_id}")
def delete_course(course_id: int, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    c = owned_course(db, course_id, teacher)
    ids = [s.id for s in db.query(ClassSession).filter(ClassSession.course_id == c.id).all()]
    if ids:
        db.query(Attendance).filter(Attendance.session_id.in_(ids)).delete(synchronize_session=False)
    db.query(ClassSession).filter(ClassSession.course_id == c.id).delete()
    db.query(Enrollment).filter(Enrollment.course_id == c.id).delete()
    db.delete(c)
    db.commit()
    return {"message": "Class deleted."}


@router.get("/{course_id}/students")
def course_students(course_id: int, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    owned_course(db, course_id, teacher)
    return {"student_ids": [e.student_id for e in db.query(Enrollment).filter(Enrollment.course_id == course_id)]}


@router.put("/{course_id}/students")
def set_course_students(course_id: int, data: EnrollIn, db: Session = Depends(get_db),
                        teacher: User = Depends(require_teacher)):
    owned_course(db, course_id, teacher)
    valid = {s.id for s in db.query(Student).filter(Student.id.in_(data.student_ids))} if data.student_ids else set()
    db.query(Enrollment).filter(Enrollment.course_id == course_id).delete()
    for sid in valid:
        db.add(Enrollment(course_id=course_id, student_id=sid))
    db.commit()
    return {"enrolled": len(valid)}
