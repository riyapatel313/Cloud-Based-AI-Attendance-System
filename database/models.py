from datetime import datetime

from sqlalchemy import (Column, Date, DateTime, Float, ForeignKey, Integer,
                        LargeBinary, String, UniqueConstraint)

from database.connection import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(10), nullable=False)  # "teacher" | "student"
    full_name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    student_code = Column(String(30), unique=True, nullable=False, index=True)
    full_name = Column(String(100), nullable=False)
    email = Column(String(120), nullable=False)
    department = Column(String(80), nullable=False, default="")
    created_at = Column(DateTime, default=datetime.now)


class FaceEmbedding(Base):
    """One row per enrolled face photo (a 128-number vector stored as float32 bytes)."""
    __tablename__ = "face_embeddings"
    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, index=True)
    vector = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class Course(Base):
    __tablename__ = "courses"
    id = Column(Integer, primary_key=True)
    code = Column(String(30), unique=True, nullable=False)
    name = Column(String(120), nullable=False)
    room = Column(String(30), nullable=False, default="")
    teacher_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.now)


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("course_id", "student_id"),)
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, index=True)


class ClassSession(Base):
    """One attendance-taking session = one class on one day."""
    __tablename__ = "class_sessions"
    __table_args__ = (UniqueConstraint("course_id", "date"),)
    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False, index=True)
    date = Column(Date, nullable=False)
    started_at = Column(DateTime, default=datetime.now)
    ended_at = Column(DateTime, nullable=True)


class Attendance(Base):
    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("session_id", "student_id"),)  # no duplicates
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("class_sessions.id"), nullable=False, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False, index=True)
    status = Column(String(10), nullable=False)  # present | late | absent
    confidence = Column(Float, nullable=True)
    marked_by = Column(String(10), nullable=False, default="face")  # face | manual | auto
    timestamp = Column(DateTime, default=datetime.now)
