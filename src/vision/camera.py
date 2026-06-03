import threading
import time

import cv2 as cv


class Camera:
    def __init__(self, src: int = 0, width: int = 640, height: int = 480):
        self._src = src
        self._width = width
        self._height = height
        self._cap = self._open()
        self._frame = None
        self._lock = threading.Lock()
        self._new_frame = threading.Event()
        self._running = False
        self._thread: threading.Thread | None = None

    def _open(self) -> cv.VideoCapture:
        for idx in [self._src, *(i for i in range(10) if i != self._src)]:
            cap = cv.VideoCapture(idx)
            if cap.isOpened():
                cap.set(cv.CAP_PROP_FRAME_WIDTH, self._width)
                cap.set(cv.CAP_PROP_FRAME_HEIGHT, self._height)
                cap.set(cv.CAP_PROP_FPS, 30)
                ok, _ = cap.read()
                if ok:
                    if idx != self._src:
                        print(f"Camera: using index {idx} (/dev/video{idx})")
                    self._src = idx
                    return cap
            cap.release()
        return cv.VideoCapture(self._src)

    def start(self) -> "Camera":
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        return self

    def _capture_loop(self) -> None:
        fails = 0
        while self._running:
            ret, frame = self._cap.read()
            if ret:
                fails = 0
                with self._lock:
                    self._frame = frame
                self._new_frame.set()
            else:
                fails += 1
                if fails >= 30:
                    self._reconnect()
                    fails = 0
                else:
                    time.sleep(0.03)

    def _reconnect(self) -> None:
        print("Camera: no frames, attempting reconnect...")
        try:
            self._cap.release()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
        self._cap = self._open()
        if self._cap.isOpened():
            print("Camera: reconnected")

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
