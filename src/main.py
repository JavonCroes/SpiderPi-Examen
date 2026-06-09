import argparse
import collections
import os
import queue
import sys
import threading
import time

import cv2 as cv

from movement.chassis import Chassis, ChassisController, StubChassis, TurnDirection

# Als MovementController niet werkt gewoon door
try:
    from movement.movement import MovementController
except Exception as exc:  # noqa: BLE001
    print(f"MovementController unavailable, manual movement disabled: {exc}")
    MovementController = None

from vision.camera import Camera
from vision.pid import PID
from vision.processor import (
    AprilTagProcessor,
    ColorProcessor,
    FaceProcessor,
    VisionProcessor,
)
from vision.servo import GimbalControl
from vision.stream import MJPEGServer

# Deadzone
DEADZONE = 15
VALID_MODES = {"0": "Idle", "1": "AprilTag", "2": "Face", "3": "Color"}

# Instelwaarden voor de body-rotatie
PAN_LIMIT_FRAMES = 5
RECENTER_MARGIN = 400

# Hoeveel speling de kleurkiezer rond de gekozen kleur neemt 
HUE_TOL = 15
SAT_TOL = 100
VAL_TOL = 120


class RobotTracker:
    def __init__(self, mode: str = "Idle", stream_port: int = 8082):
        self._camera = Camera().start()
        self._gimbal = GimbalControl()
        self._stream = MJPEGServer(port=stream_port, quality=50, fps_limit=20)

        # Handmatige besturing van movement voorzichtig opstarten.
        self._movement = None
        if MovementController is not None:
            try:
                self._movement = MovementController(board=self._gimbal.board)
            except Exception as exc:  # noqa: BLE001
                print(f"Manual movement disabled: {exc}")

        # De body-rotatie op de robot zelf anders een stub
        try:
            self._chassis: Chassis = ChassisController(self._gimbal.board)
        except ImportError as exc:
            print(f"Chassis rotation disabled, using stub: {exc}")
            self._chassis = StubChassis()

        # De drie volg-modi. Color hou ik apart bij zodat de kleurkiezer hem
        # later live kan aanpassen 
        self._color = ColorProcessor()
        self._processors: dict[str, VisionProcessor] = {
            "AprilTag": AprilTagProcessor(),
            "Face": FaceProcessor(draw_landmarks=False),
            "Color": self._color,
        }

        self._mode = mode
        self._running = True
        self._restart_requested = False

        # Een PID voor links/rechts (pan) en een voor omhoog/omlaag (tilt).
        self._pid_pan = PID(
            Kp=0.20, Ki=0.01, Kd=0.04, setpoint=0, output_limits=(-40, 40)
        )
        self._pid_tilt = PID(
            Kp=0.20, Ki=0.01, Kd=0.04, setpoint=0, output_limits=(-40, 40)
        )

        # Onthoudt of de body draait en welke kant op.
        self._pan_limit_count = 0
        self._chassis_active = False
        self._chassis_dir: TurnDirection | None = None

        self._switch_mode(self._mode)

        # Het frame gaat van de hoofdlus naar de detectie-thread en het
        # bewerkte frame komt zo weer terug. Sloten houden dat veilig.
        self._infer_frame: cv.typing.MatLike | None = None
        self._infer_lock = threading.Lock()
        self._infer_ready = threading.Event()
        self._annotated: cv.typing.MatLike | None = None
        self._annotated_lock = threading.Lock()

    def _switch_mode(self, mode: str) -> None:
        # Bij elke moduswissel: PID's leegmaken en rotatie stoppen, anders
        # neemt de nieuwe modus oude waarden mee.
        self._mode = mode

        self._pid_pan.clear()
        self._pid_tilt.clear()
        self._reset_chassis()

        if mode == "Idle":
            self._gimbal.center()

        self._stream.set_status("IDLE" if mode == "Idle" else "SEARCHING")
        print(f"Switched to {mode} mode")

    def _set_color_from_hsv(self, payload: str) -> None:
        # zet de schuifjes ("H,S,V") om naar een kleurbereik.
        try:
            h, s, v = (int(x) for x in payload.split(","))
        except ValueError:
            print(f"Ignoring malformed color payload: {payload!r}")
            return
        # Ruime marge naar beneden (licht verandert vooral de helderheid),
        # de bovenkant zetten we vast op het maximum.
        h = max(0, min(179, h))
        lower = (max(0, h - HUE_TOL), max(0, s - SAT_TOL), max(0, v - VAL_TOL))
        upper = (min(179, h + HUE_TOL), 255, 255)
        self._color.set_color(lower, upper)

    def _reset_chassis(self) -> None:
        # Stop de rotatie en zet de teller op nul.
        self._set_chassis_active(False)
        self._pan_limit_count = 0

    def _set_chassis_active(
        self, active: bool, direction: TurnDirection | None = None
    ) -> None:
        # Een plek die bijhoudt of de body draait, zodat de status klopt.
        if active:
            assert direction is not None, (
                "direction is required when activating rotation"
            )
            self._chassis_active = True
            self._chassis_dir = direction
            self._stream.set_status(f"ROTATING {direction.name}")
        else:
            if self._chassis_active:
                self._chassis.stop()
            self._chassis_active = False
            self._chassis_dir = None

    def _handle_pan_limit(self, pan_pos: int, found: bool) -> None:
        gimbal = self._gimbal

        # Geen doel niet draaien en de teller resetten.
        if not found:
            self._set_chassis_active(False)
            self._pan_limit_count = 0
            return

        if not self._chassis_active:
            # Als de pan bij zijn limit is tel dan hoeveel frames achter elkaar.
            at_max = pan_pos >= gimbal.PAN_MAX
            at_min = pan_pos <= gimbal.PAN_MIN
            if not (at_max or at_min):
                self._pan_limit_count = 0
                return
            self._pan_limit_count += 1
            if self._pan_limit_count < PAN_LIMIT_FRAMES:
                return
            # Tegen PAN_MIN -> rechtsom, tegen PAN_MAX -> linksom.
            direction = TurnDirection.RIGHT if at_min else TurnDirection.LEFT
            self._set_chassis_active(True, direction)
            self._chassis.turn(direction)
        else:
            # Als die al aan het draaien is stop dan pas als de pan genoeg terug is van de rand.
            direction = self._chassis_dir
            assert direction is not None
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
        # Zet de afstand-tot-midden om in een gimbal-beweging via de PID's.
        if not found:
            self._pid_pan.clear()
            self._pid_tilt.clear()
            return

        # Binnen de deadzone niet bewegen, en de PID leegmaken.
        pan_move = self._pid_pan.update(error_x, dt) if abs(error_x) > DEADZONE else 0
        tilt_move = self._pid_tilt.update(error_y, dt) if abs(error_y) > DEADZONE else 0

        if abs(error_x) <= DEADZONE:
            self._pid_pan.clear()
        if abs(error_y) <= DEADZONE:
            self._pid_tilt.clear()

        if pan_move != 0 or tilt_move != 0:
            self._gimbal.move(pan_move, tilt_move)

    def _read_input(self) -> None:
        # Bediening via de terminal (los van de webinterface).
        print("Commands: 0 Idle | 1 AprilTag | 2 Face | 3 Color | r Reset | q Quit")

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
        # Leegt de wachtrij met opdrachten die de webserver erin zet.
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

            # Nieuwe kleur uit de kleurkiezer.
            if cmd.startswith("color:"):
                self._set_color_from_hsv(cmd[len("color:"):])
                continue

            if cmd in ("Idle", "AprilTag", "Face", "Color"):
                self._switch_mode(cmd)

            # Bewegingsknoppen
            if self._movement is not None:
                if cmd == "forward":
                    self._movement.forward()

                elif cmd == "backward":
                    self._movement.backward()

                elif cmd == "left":
                    self._movement.strafe_left()

                elif cmd == "right":
                    self._movement.strafe_right()

                elif cmd == "turn_left":
                    self._movement.turn(TurnDirection.LEFT)

                elif cmd == "turn_right":
                    self._movement.turn(TurnDirection.RIGHT)

                elif cmd == "stop":
                    self._movement.stop()

    @staticmethod
    def _hud_text(
        img: cv.typing.MatLike, text: str, org: tuple[int, int], scale: float
    ) -> None:
        # Tekst eerst dik in het zwart, dan in het groen erover
        cv.putText(img, text, org, cv.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 5)
        cv.putText(img, text, org, cv.FONT_HERSHEY_SIMPLEX, scale, (0, 255, 0), 2)

    def _inference_loop(self) -> None:
        # De detectie-thread zwaar werk hier zodat de hoofdlus snel blijft.
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

            mode = self._mode

            if mode == "Idle":
                annotated = frame
                error_x = error_y = 0.0
                found = False
            else:
                # Laat de actieve modus het doel zoeken en stuur de gimbal.
                annotated, error_x, error_y, found = self._processors[mode].get_error(
                    frame
                )
                self._handle_tracking(error_x, error_y, found, dt)
                if mode == "Color":
                    self._handle_pan_limit(self._gimbal.pan_pos, found)

            # Status bijwerken, maar niet als de body draait (dan blijft
            # "ROTATING" staan).
            if mode == "Idle":
                self._stream.set_status("IDLE")
            elif not self._chassis_active:
                self._stream.set_status("TRACKING" if found else "SEARCHING")

            fps = 1.0 / (sum(fps_history) / len(fps_history))

            # Tekst over het beeld modus, fps en de pan-stand.
            self._hud_text(
                annotated,
                f"{mode} | {fps:.1f} fps | pan:{self._gimbal.pan_pos}",
                (10, 30),
                0.8,
            )

            if found:
                self._hud_text(
                    annotated,
                    f"err x:{int(error_x):+d} y:{int(error_y):+d}",
                    (10, 60),
                    0.6,
                )

            with self._annotated_lock:
                self._annotated = annotated

    def run(self) -> None:
        # Start de webstream en de drie hulp-threads.
        self._stream.start()

        threading.Thread(target=self._read_input, daemon=True).start()
        threading.Thread(target=self._process_web_commands, daemon=True).start()
        threading.Thread(target=self._inference_loop, daemon=True).start()

        try:
            while self._running:
                # Als er geen nieuw beeld komt en draait de body nog dan stoppen.
                if not self._camera.wait_new(timeout=0.5):
                    if self._chassis_active:
                        print("No camera frames; stopping chassis rotation")
                        self._reset_chassis()
                    continue

                ret, frame = self._camera.read()
                if not ret or frame is None:
                    continue

                # Frame doorgeven aan de detectie-thread.
                with self._infer_lock:
                    self._infer_frame = frame

                self._infer_ready.set()

                # Het laatst bewerkte frame naar de stream sturen.
                with self._annotated_lock:
                    to_send = self._annotated

                self._stream.update_frame(to_send if to_send is not None else frame)

        finally:
            # Netjes afsluiten alles stoppen en de gimbal centreren.
            if self._movement is not None:
                try:
                    self._movement.shutdown()
                except Exception as exc:  # noqa: BLE001
                    print(f"Manual movement shutdown failed: {exc}")

            self._camera.stop()
            self._stream.stop()
            self._chassis.shutdown()
            self._gimbal.center()

            # Reset
            if self._restart_requested:
                print("Restarting...")
                os.execv(sys.executable, [sys.executable] + sys.argv)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SpiderPi face/AprilTag tracker")
    p.add_argument(
        "--mode", choices=["Idle", "AprilTag", "Face", "Color"], default="Idle"
    )
    p.add_argument("--port", type=int, default=8082)
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    RobotTracker(mode=args.mode, stream_port=args.port).run()
