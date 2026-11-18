import csv
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from api.courses import owned_course
from core import face_engine
from core.security import get_current_user, require_student, require_teacher
from database.connection import get_db
from database.models import (Attendance, ClassSession, Course, Enrollment,
                             FaceEmbedding, Student, User)

router = APIRouter(prefix="/reports", tags=["Reports"])
PRESENT_LIKE = ("present", "late")


def pct(part: int, total: int) -> float:
    return round(100 * part / total, 1) if total else 0.0


def course_report(db: Session, course: Course) -> dict:
    sessions = db.query(ClassSession).filter(ClassSession.course_id == course.id).order_by(ClassSession.date).all()
    sids = [s.id for s in sessions]
    students = (db.query(Student).join(Enrollment, Enrollment.student_id == Student.id)
                .filter(Enrollment.course_id == course.id).order_by(Student.full_name).all())
    marks = {(a.session_id, a.student_id): a
             for a in (db.query(Attendance).filter(Attendance.session_id.in_(sids)).all() if sids else [])}
    rows = []
    for st in students:
        present = sum(1 for s in sessions if marks.get((s.id, st.id)) and marks[(s.id, st.id)].status == "present")
        late = sum(1 for s in sessions if marks.get((s.id, st.id)) and marks[(s.id, st.id)].status == "late")
        rows.append({"student_id": st.id, "student_code": st.student_code, "full_name": st.full_name,
                     "department": st.department, "present": present, "late": late,
                     "absent": len(sessions) - present - late, "total": len(sessions),
                     "percentage": pct(present + late, len(sessions))})
    return {"course": {"id": course.id, "code": course.code, "name": course.name},
            "total_sessions": len(sessions), "students": rows,
            "sessions": [{"id": s.id, "date": s.date.isoformat(),
                          "present": sum(1 for st in students if marks.get((s.id, st.id)) and marks[(s.id, st.id)].status in PRESENT_LIKE),
                          "enrolled": len(students)} for s in reversed(sessions)],
            "_sessions": sessions, "_students": students, "_marks": marks}


def public(report: dict) -> dict:
    return {k: v for k, v in report.items() if not k.startswith("_")}


@router.get("/summary")
def summary(db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    from datetime import date
    course_ids = [c.id for c in db.query(Course).filter(Course.teacher_id == teacher.id)]
    student_ids = {e.student_id for e in db.query(Enrollment).filter(Enrollment.course_id.in_(course_ids))} if course_ids else set()
    today = (db.query(ClassSession).filter(ClassSession.course_id.in_(course_ids), ClassSession.date == date.today()).all()
             if course_ids else [])
    present_today = (db.query(Attendance).filter(Attendance.session_id.in_([s.id for s in today]),
                                                 Attendance.status.in_(PRESENT_LIKE)).count() if today else 0)
    with_faces = {r[0] for r in db.query(FaceEmbedding.student_id).distinct()}
    return {"students": db.query(Student).count(), "courses": len(course_ids),
            "students_in_my_classes": len(student_ids), "face_registered": len(with_faces),
            "sessions_today": len(today), "present_today": present_today,
            "engine": face_engine.engine_status()}


@router.get("/course/{course_id}")
def report_for_course(course_id: int, db: Session = Depends(get_db), teacher: User = Depends(require_teacher)):
    return public(course_report(db, owned_course(db, course_id, teacher)))


@router.get("/course/{course_id}/export.csv")
def export_csv(course_id: int, detail: bool = False, db: Session = Depends(get_db),
               teacher: User = Depends(require_teacher)):
    rep = course_report(db, owned_course(db, course_id, teacher))
    buf = io.StringIO()
    w = csv.writer(buf)
    if detail:
        w.writerow(["Date", "Student ID", "Name", "Status", "Marked by", "Confidence", "Time"])
        for s in rep["_sessions"]:
            for st in rep["_students"]:
                a = rep["_marks"].get((s.id, st.id))
                w.writerow([s.date.isoformat(), st.student_code, st.full_name, a.status if a else "absent",
                            a.marked_by if a else "", f"{a.confidence:.3f}" if a and a.confidence else "",
                            a.timestamp.strftime("%H:%M:%S") if a else ""])
    else:
        w.writerow(["Student ID", "Name", "Department", "Classes held", "Present", "Late", "Absent", "Attendance %"])
        for r in rep["students"]:
            w.writerow([r["student_code"], r["full_name"], r["department"], r["total"], r["present"],
                        r["late"], r["absent"], r["percentage"]])
    code = rep["course"]["code"]
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{code}_{"detail" if detail else "summary"}.csv"'})


@router.get("/me")
def my_report(db: Session = Depends(get_db), user: User = Depends(require_student)):
    st = db.query(Student).filter(Student.user_id == user.id).first()
    if not st:
        raise HTTPException(404, "Student profile not found.")
    courses = (db.query(Course).join(Enrollment, Enrollment.course_id == Course.id)
               .filter(Enrollment.student_id == st.id).order_by(Course.code).all())
    out, recent = [], []
    for c in courses:
        sessions = db.query(ClassSession).filter(ClassSession.course_id == c.id).order_by(ClassSession.date.desc()).all()
        marks = {a.session_id: a for a in db.query(Attendance).filter(
            Attendance.student_id == st.id, Attendance.session_id.in_([s.id for s in sessions] or [0]))}
        good = sum(1 for s in sessions if marks.get(s.id) and marks[s.id].status in PRESENT_LIKE)
        out.append({"course_id": c.id, "code": c.code, "name": c.name, "total": len(sessions),
                    "attended": good, "absent": len(sessions) - good, "percentage": pct(good, len(sessions))})
        for s in sessions:
            a = marks.get(s.id)
            recent.append({"date": s.date.isoformat(), "course": f"{c.code} - {c.name}",
                           "status": a.status if a else "absent",
                           "time": a.timestamp.strftime("%H:%M") if a and a.status != "absent" else None})
    recent.sort(key=lambda r: r["date"], reverse=True)
    return {"courses": out, "recent": recent[:40]}
