import hmac

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from config import settings
from core.security import (create_token, get_current_user, hash_password,
                           verify_password)
from database.connection import get_db
from database.models import Student, User

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginIn(BaseModel):
    username: str
    password: str


class TeacherSignupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=100)
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=72)
    signup_code: str


class PasswordChangeIn(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=72)


def _session(user: User) -> dict:
    return {"access_token": create_token(user), "role": user.role,
            "full_name": user.full_name, "user_id": user.id}


@router.post("/register-teacher")
def register_teacher(data: TeacherSignupIn, db: Session = Depends(get_db)):
    if not hmac.compare_digest(data.signup_code, settings.TEACHER_SIGNUP_CODE):
        raise HTTPException(403, "Wrong teacher sign-up code.")
    username = data.username.strip().lower()
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(409, "That username is already taken.")
    user = User(username=username, hashed_password=hash_password(data.password),
                role="teacher", full_name=data.full_name.strip())
    db.add(user)
    db.commit()
    return _session(user)


@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == data.username.strip().lower()).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(401, "Wrong username or password.")
    return _session(user)


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    out = {"id": user.id, "username": user.username, "full_name": user.full_name, "role": user.role}
    if user.role == "student":
        s = db.query(Student).filter(Student.user_id == user.id).first()
        if s:
            from database.models import FaceEmbedding
            out.update(student_id=s.id, student_code=s.student_code, email=s.email, department=s.department,
                       face_count=db.query(FaceEmbedding).filter(FaceEmbedding.student_id == s.id).count())
    return out


@router.post("/change-password")
def change_password(data: PasswordChangeIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(data.old_password, user.hashed_password):
        raise HTTPException(400, "Your current password is wrong.")
    user.hashed_password = hash_password(data.new_password)
    db.commit()
    return {"message": "Password changed."}
