"""End-to-end API test. Run with:  pytest -q
Uses the offline test face engine and a throw-away database, so it needs no internet.
(Needs: pip install pytest httpx scikit-image)"""
import base64
import os
import tempfile

import pytest

tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}/test.db"
os.environ["FACE_ENGINE"] = "dev"
os.environ["TEACHER_SIGNUP_CODE"] = "TESTCODE"
os.environ["JWT_SECRET_KEY"] = "test-secret"

skimage = pytest.importorskip("skimage")
cv2 = pytest.importorskip("cv2")
from fastapi.testclient import TestClient  # noqa: E402
from skimage import data  # noqa: E402

from main import app  # noqa: E402

client = TestClient(app)


def face_jpeg(shift=0, bright=0):
    img = cv2.cvtColor(data.astronaut(), cv2.COLOR_RGB2BGR)
    img = cv2.convertScaleAbs(img, alpha=1.0, beta=bright)
    if shift:
        img = img[shift:, shift:]
    ok, buf = cv2.imencode(".jpg", img)
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def blank_jpeg():
    ok, buf = cv2.imencode(".jpg", cv2.imread(cv2.samples.findFile("lena.jpg")) if False else (255 * __import__("numpy").ones((300, 300, 3), "uint8")))
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def hdr(token):
    return {"Authorization": f"Bearer {token}"}


def test_full_flow():
    # --- auth ---
    assert client.post("/api/auth/register-teacher", json={"full_name": "Ms Rao", "username": "rao", "password": "secret1", "signup_code": "nope"}).status_code == 403
    r = client.post("/api/auth/register-teacher", json={"full_name": "Ms Rao", "username": "rao", "password": "secret1", "signup_code": "TESTCODE"})
    assert r.status_code == 200
    T = hdr(r.json()["access_token"])
    assert client.post("/api/auth/login", json={"username": "rao", "password": "bad"}).status_code == 401
    assert client.get("/api/students").status_code == 401

    # --- class + students ---
    c = client.post("/api/courses", json={"code": "cs101", "name": "Intro", "room": "B1"}, headers=T).json()
    assert c["code"] == "CS101"
    s1 = client.post("/api/students", json={"student_code": "S001", "full_name": "Asha Rao", "email": "a@x.com"}, headers=T).json()
    s2 = client.post("/api/students", json={"student_code": "S002", "full_name": "Ben Roy", "email": "b@x.com"}, headers=T).json()
    assert client.post("/api/students", json={"student_code": "S001", "full_name": "Dup", "email": "d@x.com"}, headers=T).status_code == 409
    assert client.put(f"/api/courses/{c['id']}/students", json={"student_ids": [s1["id"], s2["id"]]}, headers=T).json()["enrolled"] == 2

    # --- face enrolment ---
    bad = client.post(f"/api/students/{s1['id']}/faces", json={"images": [blank_jpeg()]}, headers=T).json()
    assert bad["saved"] == 0 and bad["problems"]
    ok = client.post(f"/api/students/{s1['id']}/faces", json={"images": [face_jpeg(), face_jpeg(bright=15)]}, headers=T).json()
    assert ok["saved"] == 2, ok

    # --- session + recognition ---
    assert client.post("/api/sessions/start", json={"course_id": c["id"]}, headers=T).status_code == 200
    sess = client.post("/api/sessions/start", json={"course_id": c["id"]}, headers=T).json()  # resume, no duplicate
    sid = sess["session"]["id"]
    r1 = client.post(f"/api/sessions/{sid}/recognize", json={"image": face_jpeg(bright=5)}, headers=T).json()
    assert r1["newly_marked"] == 1 and r1["faces"][0]["status"] == "marked" and r1["faces"][0]["name"] == "Asha Rao", r1
    r2 = client.post(f"/api/sessions/{sid}/recognize", json={"image": face_jpeg(bright=5)}, headers=T).json()
    assert r2["newly_marked"] == 0 and r2["faces"][0]["status"] == "already"  # no duplicates
    assert client.post(f"/api/sessions/{sid}/recognize", json={"image": blank_jpeg()}, headers=T).json()["faces"] == []

    # manual correction, then end session -> unmarked become absent
    d = client.post(f"/api/sessions/{sid}/mark", json={"student_id": s2["id"], "status": "late"}, headers=T).json()
    assert {r["student_code"]: r["status"] for r in d["roster"]} == {"S001": "present", "S002": "late"}
    client.post(f"/api/sessions/{sid}/mark", json={"student_id": s2["id"], "status": "absent"}, headers=T)
    ended = client.post(f"/api/sessions/{sid}/end", json={}, headers=T).json()
    assert ended["session"]["ended_at"] and ended["session"]["present_count"] == 1
    assert client.post(f"/api/sessions/{sid}/recognize", json={"image": face_jpeg()}, headers=T).status_code == 400

    # --- reports ---
    rep = client.get(f"/api/reports/course/{c['id']}", headers=T).json()
    by = {s["student_code"]: s for s in rep["students"]}
    assert by["S001"]["percentage"] == 100.0 and by["S002"]["percentage"] == 0.0
    csv_text = client.get(f"/api/reports/course/{c['id']}/export.csv", headers=T).text
    assert "Asha Rao" in csv_text and "100.0" in csv_text
    assert "Date,Student ID" in client.get(f"/api/reports/course/{c['id']}/export.csv?detail=true", headers=T).text.replace("\ufeff", "")
    assert client.get("/api/reports/summary", headers=T).json()["face_registered"] == 1

    # --- student portal ---
    st = client.post("/api/auth/login", json={"username": "S001", "password": "S001"}).json()
    S = hdr(st["access_token"])
    assert st["role"] == "student"
    me = client.get("/api/reports/me", headers=S).json()
    assert me["courses"][0]["percentage"] == 100.0 and me["recent"][0]["status"] == "present"
    assert client.get("/api/students", headers=S).status_code == 403   # students cannot use teacher APIs
    assert client.get("/api/courses", headers=S).json()[0]["code"] == "CS101"
    assert client.post("/api/auth/change-password", json={"old_password": "S001", "new_password": "newpass1"}, headers=S).status_code == 200
    assert client.post("/api/auth/login", json={"username": "S001", "password": "newpass1"}).status_code == 200

    # --- cleanup paths ---
    assert client.delete(f"/api/students/{s2['id']}", headers=T).status_code == 200
    assert client.delete(f"/api/courses/{c['id']}", headers=T).status_code == 200


def test_pages_load():
    for path in ("/login", "/teacher", "/student", "/static/js/common.js", "/static/css/style.css", "/health", "/api/system/status"):
        assert client.get(path, follow_redirects=False).status_code == 200, path
    assert client.get("/", follow_redirects=False).status_code in (302, 307)
