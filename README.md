# Cloud-Based AI Attendance System

A camera watches the classroom, recognises students' faces and marks them present automatically.
Teachers manage classes, students and reports; students sign in to see their own attendance.

**Stack:** Python · FastAPI · SQLAlchemy (SQLite, or PostgreSQL in the cloud) · OpenCV face recognition
(YuNet detector + SFace recognizer) · plain HTML/CSS/JavaScript front end. No TensorFlow/PyTorch/dlib needed.

## 1. Run it on your computer

You need **Python 3.9 or newer** and a **webcam**, plus internet on the first run (about 40 MB of face models download once).

**Windows:** double-click `start.bat`
**Mac/Linux:** run `./start.sh`

Or manually:
```
python -m venv venv
venv\Scripts\activate          (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt
python run.py
```
Your browser opens at **http://127.0.0.1:8000** (use `127.0.0.1` or `localhost`, because browsers only allow camera access there).
Interactive API docs: http://127.0.0.1:8000/docs

## 2. First-time walkthrough

1. **Teacher sign-up** tab -> create your account. The sign-up code is `TEACHER_SIGNUP_CODE` in the `.env` file (default `TEACHER123`; change it).
2. **Classes** -> add a class (e.g. CS101).
3. **Students** -> add each student (ID, name, email). Their login is their ID; the password is whatever you typed, or the ID if left blank.
4. **Students -> Register face** -> take 3-5 photos (or upload photos). One person per photo, good light.
5. **Classes -> Choose students** -> tick who belongs to the class.
6. **Take attendance** -> pick the class -> *Start today's session* -> *Start scanning*. Faces get a coloured box: green = marked, red = unknown, amber = not in this class. Fix mistakes with the "Set..." menu. Click *End session* and anyone not seen is recorded absent.
7. **Reports** -> attendance % per student, sessions held, CSV download.
8. Students sign in at the same page with their ID to see their percentage per class and recent days.

## 3. Project layout

```
main.py            app entry point, page routes
run.py             starts the server and opens the browser
config/settings.py reads .env (auto-created on first run)
database/          connection.py, models.py (users, students, face_embeddings, courses, enrollments, class_sessions, attendance)
core/security.py   password hashing (bcrypt), JWT login tokens, role checks
core/face_engine.py face detection + recognition, auto-downloads models into ./models
api/               auth, students (+face enrolment), courses, attendance (live recognition), reports, system
templates/         login.html, teacher.html, student.html
static/            css/style.css, js/common.js, js/teacher.js
tests/test_api.py  end-to-end test (pip install pytest httpx scikit-image; then: pytest -q)
```

## 4. Settings (`.env`)

| Setting | Meaning |
|---|---|
| `JWT_SECRET_KEY` | Signs login tokens. Auto-generated. Keep secret. |
| `TEACHER_SIGNUP_CODE` | Code needed to create a teacher account. |
| `DATABASE_URL` | Default is a local SQLite file. Use `postgresql://...` for the cloud. |
| `COSINE_THRESHOLD` | Match strictness, default `0.40`. Raise (0.5) if the wrong person gets marked; lower (0.36) if students are not recognised. |
| `FACE_ENGINE` | `opencv` (real). `dev` is an inaccurate offline engine used only by the tests. |

## 5. Going to the cloud

The app is already cloud-ready: it is a stateless web service plus a database.
1. Create a PostgreSQL database (Neon, Supabase, Render, Railway, AWS RDS...) and copy its connection URL.
2. Deploy this folder with the included `Dockerfile` to Render / Railway / Fly.io / Google Cloud Run / AWS App Runner.
3. Set environment variables: `DATABASE_URL`, `JWT_SECRET_KEY` (long random), `TEACHER_SIGNUP_CODE`.
4. Serve over **HTTPS** (all those hosts do), which browsers require for camera access on a public address.
5. Cameras are the user's own browser/webcam, so no extra hardware setup is needed in the cloud.

Note: the container filesystem is temporary on most hosts. The face models re-download on each restart (about 40 MB), so mount a persistent disk at `/app/models` if startup time matters.

## 6. Troubleshooting

- **"Face recognition is not ready"** on Overview: the model download failed. Check your internet and reload; or download the two `.onnx` files from the link in the message into the `models/` folder.
- **Camera does not start:** allow camera permission in the browser, close other apps using the webcam, and use `127.0.0.1`/`localhost`.
- **Student not recognised:** register 3-5 photos in similar lighting to the classroom; add photos taken from the classroom camera itself.
- **Forgot teacher password:** delete `attendance.db` to start fresh (this erases all data), or ask a developer to reset the hash.

## 7. Known limitations (honest list)

- No **liveness detection**: a printed photo or phone screen of a student could be recognised. Fine for a classroom with a teacher watching; add anti-spoofing before using it unattended.
- Face data is biometric personal data. Get students' consent, protect the database, and follow your school's/country's privacy rules.
- One session per class per day. Duplicate marking is blocked by the database.
