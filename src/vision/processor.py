import time
from abc import ABC, abstractmethod
from pathlib import Path

import cv2 as cv
import mediapipe as mp
import numpy as np
from dt_apriltags import Detector
from mediapipe.tasks import python
from mediapipe.tasks.python import vision

_CROSSHAIR = (80, 80, 80)
_DETECT = (255, 255, 255)
_LANDMARK = (140, 140, 140)


def _draw_crosshairs(frame: cv.typing.MatLike) -> None:
    h, w = frame.shape[:2]
    cx, cy = w // 2, h // 2
    cv.line(frame, (cx, 0), (cx, h), _CROSSHAIR, 1)
    cv.line(frame, (0, cy), (w, cy), _CROSSHAIR, 1)


class VisionProcessor(ABC):
    @abstractmethod
    def get_error(
        self, frame: cv.typing.MatLike
    ) -> tuple[cv.typing.MatLike, float, float, bool]:
        """Return (annotated_frame, error_x, error_y, target_found)."""


class AprilTagProcessor(VisionProcessor):
    def __init__(self, family: str = "tag36h11"):
        self._detector = Detector(
            families=family,
            nthreads=2,
            quad_decimate=1.5,
            quad_sigma=0.4,
            refine_edges=1,
            decode_sharpening=0.25,
            debug=0,
        )
        self._gray = np.empty((480, 640), dtype=np.uint8)

    def get_error(
        self, frame: cv.typing.MatLike
    ) -> tuple[cv.typing.MatLike, float, float, bool]:
        cv.cvtColor(frame, cv.COLOR_BGR2GRAY, dst=self._gray)
        gray = self._gray
        tags = self._detector.detect(gray)
        h, w = frame.shape[:2]
        _draw_crosshairs(frame)

        if not tags:
            return frame, 0, 0, False

        tag = max(tags, key=lambda t: (t.corners[2][0] - t.corners[0][0]) ** 2
                  + (t.corners[2][1] - t.corners[0][1]) ** 2) if len(tags) > 1 else tags[0]
        tx, ty = int(tag.center[0]), int(tag.center[1])

        for i in range(4):
            cv.line(
                frame,
                tuple(tag.corners[i].astype(int)),
                tuple(tag.corners[(i + 1) % 4].astype(int)),
                _DETECT,
                2,
            )
        cv.drawMarker(frame, (tx, ty), _DETECT, cv.MARKER_CROSS, 20, 2)

        return frame, tx - w // 2, ty - h // 2, True


class FaceProcessor(VisionProcessor):
    _MODEL = str(
        Path(__file__).resolve().parent.parent
        / "face_landmarker_v2_with_blendshapes.task"
    )
    # forehead(10), chin(152), left ear(234), right ear(454)
    _BBOX_INDICES = (10, 152, 234, 454)

    def __init__(self, draw_landmarks: bool = False):
        self._draw_landmarks = draw_landmarks
        self._start_ms = int(time.monotonic() * 1000)
        self._last_ts_ms = -1
        self._rgb = np.empty((480, 640, 3), dtype=np.uint8)

        options = vision.FaceLandmarkerOptions(
            base_options=python.BaseOptions(model_asset_path=self._MODEL),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            min_face_detection_confidence=0.5,
            min_face_presence_confidence=0.5,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)

    def _now_ms(self) -> int:
        ts = int(time.monotonic() * 1000) - self._start_ms
        if ts <= self._last_ts_ms:
            ts = self._last_ts_ms + 1
        self._last_ts_ms = ts
        return ts

    def get_error(
        self, frame: cv.typing.MatLike
    ) -> tuple[cv.typing.MatLike, float, float, bool]:
        cv.cvtColor(frame, cv.COLOR_BGR2RGB, dst=self._rgb)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=self._rgb)
        result = self._landmarker.detect_for_video(mp_image, self._now_ms())

        h, w = frame.shape[:2]
        _draw_crosshairs(frame)

        if not result.face_landmarks:
            return frame, 0, 0, False

        landmarks = result.face_landmarks[0]

        if self._draw_landmarks:
            for lm in landmarks:
                cv.circle(frame, (int(lm.x * w), int(lm.y * h)), 1, _LANDMARK, -1)

        min_x = min_y = 1.0
        max_x = max_y = 0.0
        for i in self._BBOX_INDICES:
            lm = landmarks[i]
            if lm.x < min_x:
                min_x = lm.x
            if lm.x > max_x:
                max_x = lm.x
            if lm.y < min_y:
                min_y = lm.y
            if lm.y > max_y:
                max_y = lm.y

        face_cx = int(((min_x + max_x) / 2) * w)
        face_cy = int(((min_y + max_y) / 2) * h)

        cv.rectangle(
            frame,
            (int(min_x * w), int(min_y * h)),
            (int(max_x * w), int(max_y * h)),
            _DETECT,
            2,
        )
        cv.drawMarker(frame, (face_cx, face_cy), _DETECT, cv.MARKER_CROSS, 20, 2)

        return frame, face_cx - w // 2, face_cy - h // 2, True


class ColorProcessor(VisionProcessor):
    def __init__(
        self,
        lower_hsv: tuple[int, int, int] = (100, 120, 50),
        upper_hsv: tuple[int, int, int] = (130, 255, 255),
        min_area: int = 500,
    ):
        self._lower = np.array(lower_hsv, dtype=np.uint8)
        self._upper = np.array(upper_hsv, dtype=np.uint8)
        self._min_area = min_area
        self._hsv = np.empty((480, 640, 3), dtype=np.uint8)
        self._kernel = cv.getStructuringElement(cv.MORPH_ELLIPSE, (9, 9))

    def get_error(
        self, frame: cv.typing.MatLike
    ) -> tuple[cv.typing.MatLike, float, float, bool]:
        h, w = frame.shape[:2]
        _draw_crosshairs(frame)

        cv.cvtColor(frame, cv.COLOR_BGR2HSV, dst=self._hsv)
        mask = cv.inRange(self._hsv, self._lower, self._upper)

        # Remove noise, fill gaps
        mask = cv.morphologyEx(mask, cv.MORPH_OPEN, self._kernel)
        mask = cv.morphologyEx(mask, cv.MORPH_CLOSE, self._kernel)

        contours, _ = cv.findContours(mask, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)
        if not contours:
            return frame, 0, 0, False

        largest = max(contours, key=cv.contourArea)
        area = cv.contourArea(largest)
        if area < self._min_area:
            return frame, 0, 0, False

        x, y, bw, bh = cv.boundingRect(largest)
        cx = x + bw // 2
        cy = y + bh // 2

        cv.rectangle(frame, (x, y), (x + bw, y + bh), _DETECT, 2)
        cv.drawMarker(frame, (cx, cy), _DETECT, cv.MARKER_CROSS, 20, 2)

        return frame, cx - w // 2, cy - h // 2, True
