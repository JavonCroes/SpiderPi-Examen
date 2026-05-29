import argparse
import collections
import os
import queue
import sys
import threading
import time

import cv2 as cv

from vision.camera import Camera
from vision.pid import PID
from vision.processor import AprilTagProcessor, ColorProcessor, FaceProcessor, VisionProcessor
from vision.servo import GimbalControl
from vision.stream import MJPEGServer

DEADZONE = 15
VALID_MODES = {"0": "Idle", "1": "AprilTag", "2": "Face", "3": "Color"}


class RobotTracker:
    def __init__(self, mode: str = "Idle", stream_port: int = 8082):
        self._camera = Camera().start()
        self._gimbal = GimbalControl()
        self._stream = MJPEGServer(port=stream_port, quality=50, fps_limit=20)

        self._processors: dict[str, VisionProcessor] = {
            "AprilTag": AprilTagProcessor(),
            "Face": FaceProcessor(draw_landmarks=False),
            "Color": ColorProcessor(),
        }
        self._mode = mode
        self._running = True
        self._restart_requested = False

        self._pid_pan = PID(
            Kp=0.20, Ki=0.01, Kd=0.04, setpoint=0, output_limits=(-40, 40)
        )
        self._pid_tilt = PID(
            Kp=0.20, Ki=0.01, Kd=0.04, setpoint=0, output_limits=(-40, 40)
        )
        self._switch_mode(self._mode)

        self._infer_frame: cv.typing.MatLike | None = None
        self._infer_lock = threading.Lock()
        self._infer_ready = threading.Event()
        self._annotated: cv.typing.MatLike | None = None
        self._annotated_lock = threading.Lock()

    def _switch_mode(self, mode: str) -> None:
        self._mode = mode

        self._pid_pan.clear()
        self._pid_tilt.clear()

        if mode == "Idle":
            self._gimbal.center()

        print(f"Switched to {mode} mode")

    def _handle_tracking(
        self, error_x: float, error_y: float, found: bool, dt: float
    ) -> None:
        if not found:
            self._pid_pan.clear()
            self._pid_tilt.clear()
            return

        pan_move = self._pid_pan.update(error_x, dt) if abs(error_x) > DEADZONE else 0
        tilt_move = self._pid_tilt.update(error_y, dt) if abs(error_y) > DEADZONE else 0

        if abs(error_x) <= DEADZONE:
            self._pid_pan.clear()
        if abs(error_y) <= DEADZONE:
            self._pid_tilt.clear()

        if pan_move != 0 or tilt_move != 0:
            self._gimbal.move(pan_move, tilt_move)

    def _read_input(self) -> None:
        print(
            "Commands: '0' = Idle | '1' = AprilTag | '2' = Face | '3' = Color | 'r' = Reset | 'q' = Quit"
        )
        for line in sys.stdin:
            cmd = line.strip()
            if cmd == "q":
                self._running = False
                break
            if cmd == "r":
                self._restart_requested = True
                self._running = False
                break
            mode = VALID_MODES.get(cmd)
            if mode:
                self._switch_mode(mode)

    def _process_web_commands(self) -> None:
        while self._running:
            try:
                cmd = self._stream.commands.get(timeout=0.5)
            except queue.Empty:
                continue
            if cmd == "quit":
                self._running = False
                break
            if cmd == "reset":
                self._restart_requested = True
                self._running = False
                break
            if cmd in ("Idle", "AprilTag", "Face", "Color"):
                self._switch_mode(cmd)

    def _inference_loop(self) -> None:
        last_time = time.monotonic()
        fps_history: collections.deque[float] = collections.deque(maxlen=30)

        while self._running:
            if not self._infer_ready.wait(timeout=0.5):
                continue
            self._infer_ready.clear()

            with self._infer_lock:
                frame = self._infer_frame
            if frame is None:
                continue

            now = time.monotonic()
            dt = max(now - last_time, 1e-4)
            last_time = now
            fps_history.append(dt)

            # Read mode once: another thread may switch it mid-iteration, and
            # the property lookup self._processors[mode] has no "Idle" key.
            mode = self._mode
            if mode == "Idle":
                annotated = frame
                error_x = error_y = 0.0
                found = False
            else:
                annotated, error_x, error_y, found = self._processors[mode].get_error(frame)
                self._handle_tracking(error_x, error_y, found, dt)

            fps = 1.0 / (sum(fps_history) / len(fps_history))
            cv.putText(
                annotated,
                f"{mode} | {fps:.1f} fps",
                (10, 30),
                cv.FONT_HERSHEY_SIMPLEX,
                0.8,
                (255, 255, 255),
                2,
            )
            if found:
                cv.putText(
                    annotated,
                    f"err x:{int(error_x):+d} y:{int(error_y):+d}",
                    (10, 60),
                    cv.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    (180, 180, 180),
                    2,
                )

            with self._annotated_lock:
                self._annotated = annotated

    def run(self) -> None:
        self._stream.start()
        threading.Thread(target=self._read_input, daemon=True).start()
        threading.Thread(target=self._process_web_commands, daemon=True).start()
        threading.Thread(target=self._inference_loop, daemon=True).start()

        try:
            while self._running:
                if not self._camera.wait_new(timeout=0.5):
                    continue

                ret, frame = self._camera.read()
                if not ret or frame is None:
                    continue

                with self._infer_lock:
                    self._infer_frame = frame
                self._infer_ready.set()

                with self._annotated_lock:
                    to_send = self._annotated
                self._stream.update_frame(to_send if to_send is not None else frame)

        finally:
            self._camera.stop()
            self._stream.stop()
            self._gimbal.center()
            if self._restart_requested:
                print("Restarting...")
                os.execv(sys.executable, [sys.executable] + sys.argv)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SpiderPi face/AprilTag tracker")
    p.add_argument("--mode", choices=["Idle", "AprilTag", "Face", "Color"], default="Idle")
    p.add_argument("--port", type=int, default=8082, help="MJPEG stream port")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    RobotTracker(mode=args.mode, stream_port=args.port).run()
