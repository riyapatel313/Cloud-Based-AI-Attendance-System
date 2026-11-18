"""Face detection + recognition.

Default engine ("opencv"): OpenCV YuNet (detector) + SFace (recognizer). Both are small ONNX
models that are downloaded automatically into ./models on first use. No TensorFlow/PyTorch/dlib.

Every face is turned into a 128-number vector ("embedding"). Two photos of the same person give
vectors with a high cosine similarity; different people give a low one.
"""
import base64
import shutil
import threading
import urllib.request

import cv2
import numpy as np

from config import settings

MODEL_DIR = settings.BASE_DIR / "models"
MODELS = {
    "yunet": (
        "face_detection_yunet_2023mar.onnx", 100_000,
        ["https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
         "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx"],
    ),
    "sface": (
        "face_recognition_sface_2021dec.onnx", 10_000_000,
        ["https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
         "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx"],
    ),
}
MAX_SIDE = 800       # frames are shrunk to this size before processing (speed)
MIN_FACE_PX = 60     # faces smaller than this (after shrinking) are too far away


class FaceEngineError(Exception):
    """A problem the user can understand and fix (bad image, missing model, ...)."""


def decode_image(data: str) -> np.ndarray:
    if not data:
        raise FaceEngineError("No image received.")
    if data.strip().startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    try:
        raw = base64.b64decode(data)
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        img = None
    if img is None:
        raise FaceEngineError("Could not read the image.")
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def _normalise(v: np.ndarray) -> np.ndarray:
    v = v.flatten().astype(np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _download(key: str):
    fname, min_size, urls = MODELS[key]
    path = MODEL_DIR / fname
    if path.exists() and path.stat().st_size >= min_size:
        return path
    MODEL_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".part")
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "attendance-system"})
            with urllib.request.urlopen(req, timeout=90) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f)
            if tmp.stat().st_size >= min_size:  # a tiny file = Git-LFS pointer, not the model
                tmp.replace(path)
                return path
        except Exception:
            pass
        tmp.unlink(missing_ok=True)
    raise FaceEngineError(
        f"Could not download the face model '{fname}'. Check your internet connection and restart, "
        f"or download it manually from {urls[0]} and put it in the folder: {MODEL_DIR}"
    )


class OpenCVEngine:
    name = "opencv (YuNet + SFace)"

    def __init__(self):
        yunet, sface = _download("yunet"), _download("sface")
        self._lock = threading.Lock()
        self._detector = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), 0.85, 0.3, 50)
        self._recognizer = cv2.FaceRecognizerSF.create(str(sface), "")

    def detect(self, img):
        h, w = img.shape[:2]
        with self._lock:
            self._detector.setInputSize((w, h))
            _, rows = self._detector.detect(img)
        faces = []
        for r in (rows if rows is not None else []):
            x, y, fw, fh = [int(v) for v in r[:4]]
            faces.append({"x": max(x, 0), "y": max(y, 0), "w": fw, "h": fh, "score": float(r[14]), "raw": r})
        return faces

    def embed(self, img, face):
        with self._lock:
            aligned = self._recognizer.alignCrop(img, face["raw"])
            return _normalise(self._recognizer.feature(aligned))


class DevEngine:
    """Crude Haar-cascade engine that works offline. FOR TESTING ONLY - not accurate."""
    name = "dev (Haar cascade - testing only)"

    def __init__(self):
        self._cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")

    def detect(self, img):
        gray = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        boxes = self._cascade.detectMultiScale(gray, 1.1, 5, minSize=(MIN_FACE_PX, MIN_FACE_PX))
        return [{"x": int(x), "y": int(y), "w": int(w), "h": int(h), "score": 1.0, "raw": None}
                for x, y, w, h in boxes]

    def embed(self, img, face):
        crop = img[face["y"]:face["y"] + face["h"], face["x"]:face["x"] + face["w"]]
        gray = cv2.equalizeHist(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
        return _normalise(small - small.mean())


# ---- lazy singleton so the server starts instantly and loads models in the background ----
_engine = None
_error = None
_lock = threading.Lock()


def get_engine():
    global _engine, _error
    with _lock:
        if _engine is None:
            try:
                _engine = DevEngine() if settings.FACE_ENGINE == "dev" else OpenCVEngine()
                _error = None
            except FaceEngineError as e:
                _error = str(e)
                raise
            except Exception as e:  # e.g. old OpenCV without FaceDetectorYN
                _error = f"Face engine failed to start: {e}"
                raise FaceEngineError(_error)
        return _engine


def engine_status() -> dict:
    return {"ready": _engine is not None, "name": _engine.name if _engine else settings.FACE_ENGINE, "error": _error}


def best_match(vec: np.ndarray, ids: np.ndarray, matrix: np.ndarray):
    """Return (student_id, similarity) of the closest enrolled face, or (None, 0.0)."""
    if matrix.shape[0] == 0:
        return None, 0.0
    sims = matrix @ vec
    i = int(np.argmax(sims))
    return int(ids[i]), float(sims[i])
