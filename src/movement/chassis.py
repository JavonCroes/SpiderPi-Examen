from __future__ import annotations

import enum
import sys
import threading
import time
from typing import Protocol

_SDK_PATHS = (
    "/home/pi/spiderpi/spiderpi_sdk/common_sdk",
    "/home/pi/spiderpi/spiderpi_sdk/common_sdk/common",
)


class TurnDirection(enum.Enum):
    LEFT = "left"
    RIGHT = "right"


class Chassis(Protocol):
    # De gedeelde vorm zowel de echte chassis als de stub volgen dit.
    @property
    def is_moving(self) -> bool: ...

    def is_rotating(self) -> bool: ...

    def turn(self, direction: TurnDirection) -> None: ...

    def stop(self) -> None: ...

    def shutdown(self) -> None: ...


class ChassisController:
    def __init__(self, board, angle: int = 20, speed: int = 60):
        self._board = board
        self._angle = angle
        self._speed = speed
        self._ik = self._make_ik(board)

        # De worker-thread doet het draaien turn() en stop() geven alleen door
        # wat hij moet doen en keren meteen terug.
        self._lock = threading.Lock()
        self._desired: TurnDirection | None = None
        self._is_moving = False
        self._running = True
        self._wake = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    @staticmethod
    def _make_ik(board):
        # De kinematics-library bestaat alleen op de robot niet gevonden dan
        # een ImportError zodat main.py op de stub terugvalt.
        for path in _SDK_PATHS:
            if path not in sys.path:
                sys.path.append(path)
        try:
            import kinematics  # type: ignore[import-not-found]  # encrypted
        except ImportError as exc:
            raise ImportError(
                "Hiwonder 'kinematics' library not found on the SDK path "
                f"{_SDK_PATHS[1]!r}. ChassisController only runs on the robot; "
                "use StubChassis to test the tracking logic off-hardware."
            ) from exc
        return kinematics.IK(board)

    @property
    def is_moving(self) -> bool:
        return self._is_moving

    def is_rotating(self) -> bool:
        return self._is_moving

    def turn(self, direction: TurnDirection) -> None:
        # Geef de gewenste richting door en maak de worker wakker.
        with self._lock:
            self._desired = direction
        self._wake.set()

    def stop(self) -> None:
        # Geen richting meer betekent stoppen.
        with self._lock:
            self._desired = None
        self._wake.set()

    def shutdown(self) -> None:
        # Netjes afsluiten stoppen even wachten tot hij stilstaat dan klaar.
        self.stop()
        deadline = time.monotonic() + 3.0
        while self._is_moving and time.monotonic() < deadline:
            time.sleep(0.05)
        self._running = False
        self._wake.set()
        self._worker.join(timeout=1.0)

    def _run(self) -> None:
        # De worker een stapje per keer en tussendoor opnieuw kijken wat er
        # gevraagd wordt zo blijft de camera ondertussen volgen.
        while self._running:
            if not self._wake.wait(timeout=0.5):
                continue
            with self._lock:
                direction = self._desired
            if direction is None:
                if self._is_moving:
                    self._ik.stand(self._ik.initial_pos)
                    self._is_moving = False
                self._wake.clear()
                continue
            self._is_moving = True
            try:
                # Waarden houding modus (2 = hexapod) hoek snelheid herhalingen.
                if direction is TurnDirection.LEFT:
                    self._ik.turn_left(
                        self._ik.initial_pos, 2, self._angle, self._speed, 1
                    )
                else:
                    self._ik.turn_right(
                        self._ik.initial_pos, 2, self._angle, self._speed, 1
                    )
            except Exception as exc:
                print(f"Chassis turn failed: {exc}")
                self._wake.clear()


class StubChassis:
    # Stub voor testen zonder robot print alleen wat hij zou doen.
    def __init__(self, board=None, angle: int = 10, speed: int = 100):
        self._angle = angle
        self._speed = speed
        self._is_moving = False
        self._desired: TurnDirection | None = None

    @property
    def is_moving(self) -> bool:
        return self._is_moving

    def is_rotating(self) -> bool:
        return self._is_moving

    def turn(self, direction: TurnDirection) -> None:
        if direction is not self._desired:
            print(f"[StubChassis] turn {direction.name} (angle={self._angle})")
        self._desired = direction
        self._is_moving = True

    def stop(self) -> None:
        if self._desired is not None:
            print("[StubChassis] stop -> stand")
        self._desired = None
        self._is_moving = False

    def shutdown(self) -> None:
        self.stop()
