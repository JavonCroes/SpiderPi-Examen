import argparse
import collections
import os
import queue
import sys
import threading
import time

import cv2 as cv

from movement.chassis import Chassis, ChassisController, StubChassis, TurnDirection
from vision.camera import Camera
from vision.pid import PID
from vision.processor import AprilTagProcessor, ColorProcessor, FaceProcessor, VisionProcessor
from vision.servo import GimbalControl
from vision.stream import MJPEGServer

DEADZONE = 15
VALID_MODES = {"0": "Idle", "1": "AprilTag", "2": "Face", "3": "Color"}

# Body-rotation handoff (Color mode only). Once the pan servo is pinned at a
# limit for PAN_LIMIT_FRAMES consecutive frames, the chassis turns; it keeps
# turning until the gimbal has re-centered RECENTER_MARGIN servo-units back from
# the limit. Both thresholds add hysteresis so the body does not toggle at the
# boundary.
PAN_LIMIT_FRAMES = 5
RECENTER_MARGIN = 400


class RobotTracker:
    def __init__(self, mode: str = "Idle", stream_port: int = 8082):
        self._camera = Camera().start()
        self._gimbal = GimbalControl()
        self._stream = MJPEGServer(port=stream_port, quality=50, fps_limit=20)

        # Chassis rotation shares the gimbal's single serial Board (see
        # GimbalControl) and is the "body takes over" half of the pan handoff.
        # Swap ChassisController -> StubChassis here to test off-hardware; it
        # also falls back to the stub automatically when the IK SDK is absent.
        try:
            self._chassis: Chassis = ChassisController(self._gimbal.board)
        except ImportError as exc:
            print(f"Chassis rotation disabled, using stub: {exc}")
            self._chassis = StubChassis()

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

        # Pan-limit hysteresis state, consumed by _handle_pan_limit.
        self._pan_limit_count = 0
        self._chassis_active = False
        self._chassis_dir: TurnDirection | None = None

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
        self._reset_chassis()

        if mode == "Idle":
            self._gimbal.center()

        print(f"Switched to {mode} mode")

    def _reset_chassis(self) -> None:
        """Stop any rotation and clear the pan-limit hysteresis (mode switches)."""
        self._set_chassis_active(False)
        self._pan_limit_count = 0

    def _set_chassis_active(self, active: bool, direction: TurnDirection | None = None) -> None:
        if active:
            assert direction is not None, "direction is required when activating rotation"
            self._chassis_active = True
            self._chassis_dir = direction
        else:
            # Guard: only command a stand if we were actually rotating, so a
            # mode switch doesn't needlessly run a gait cycle. The chassis and a
            # future MovementController share this bus and must not move at once.
            if self._chassis_active:
                self._chassis.stop()
            self._chassis_active = False
            self._chassis_dir = None

    def _handle_pan_limit(self, pan_pos: int, found: bool) -> None:
        """Hand pan tracking off to body rotation when the gimbal runs out of travel.

        Implements images/flowchart_chassis_rotatie.png (Color mode only). When
        the target is found AND the pan servo is pinned at a limit for
        PAN_LIMIT_FRAMES consecutive frames, the body rotates toward that side.
        Direction is the empirically-verified mapping (matches the flowchart):
        on this robot the gimbal pans toward PAN_MIN to follow a target on the
        RIGHT, so PAN_MIN -> turn RIGHT and PAN_MAX -> turn LEFT. It keeps
        turning until the gimbal has re-centered RECENTER_MARGIN servo-units back
        from the limit -- not just one tick off it -- so it does not toggle.
        """
        gimbal = self._gimbal

        # No target: cancel any rotation and reset the counter.
        if not found:
            self._set_chassis_active(False)
            self._pan_limit_count = 0
            return

        if not self._chassis_active:
            at_max = pan_pos >= gimbal.PAN_MAX
            at_min = pan_pos <= gimbal.PAN_MIN
            if not (at_max or at_min):
                # Off the limit: the gimbal alone is coping, reset the counter.
                self._pan_limit_count = 0
                return
            # Pinned at a limit: require N stable frames before taking over.
            self._pan_limit_count += 1
            if self._pan_limit_count < PAN_LIMIT_FRAMES:
                return
            # Empirical mapping (see docstring): PAN_MIN -> RIGHT, PAN_MAX -> LEFT.
            direction = TurnDirection.RIGHT if at_min else TurnDirection.LEFT
            self._set_chassis_active(True, direction)
            self._chassis.turn(direction)
        else:
            # Already rotating: stop once the gimbal has re-centered comfortably,
            # measured against the limit we were pinned at (RIGHT was PAN_MIN).
            direction = self._chassis_dir
            assert direction is not None  # always set while _chassis_active is True
            if direction is TurnDirection.RIGHT:
                recentered = pan_pos >= gimbal.PAN_MIN + RECENTER_MARGIN
            else:
                recentered = pan_pos <= gimbal.PAN_MAX - RECENTER_MARGIN
            if recentered:
                self._set_chassis_active(False)
                self._pan_limit_count = 0
            else:
                self._chassis.turn(direction)

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
                # The body-rotation handoff is scoped to Color mode (the tracked
                # target for this feature); the pan position is already clamped.
                if mode == "Color":
                    self._handle_pan_limit(self._gimbal.pan_pos, found)

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
            self._chassis.shutdown()  # stop rotating, stand, join the worker
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
