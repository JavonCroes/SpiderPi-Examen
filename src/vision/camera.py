import threading
import time

import cv2 as cv


class Camera:
    """Threaded camera capture — always returns the latest frame without blocking."""

    def __init__(self, src: int = 0, width: int = 640, height: int = 480):
        self._cap = cv.VideoCapture(src)
        self._cap.set(cv.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv.CAP_PROP_FRAME_HEIGHT, height)
        self._cap.set(cv.CAP_PROP_FPS, 30)
        # NB: do NOT force CAP_PROP_BUFFERSIZE=1 — on this UVC camera's V4L2 driver
        # a single buffer drops throughput from ~22fps to ~17fps. The capture thread
        # below already drains continuously and keeps only the latest frame, so a
        # deeper driver buffer adds no real latency.
        self._frame = None
        self._lock = threading.Lock()
        self._new_frame = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self) -> "Camera":
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return self

    def _capture_loop(self) -> None:
        while self._running:
            ret, frame = self._cap.read()
            if ret:
                with self._lock:
                    self._frame = frame
                self._new_frame.set()
            else:
                time.sleep(0.03)

    def wait_new(self, timeout: float = 0.5) -> bool:
        """Block until a new frame arrives. Returns False on timeout."""
        if self._new_frame.wait(timeout=timeout):
            self._new_frame.clear()
            return True
        return False

    def read(self) -> tuple[bool, cv.typing.MatLike | None]:
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
        self._cap.release()
