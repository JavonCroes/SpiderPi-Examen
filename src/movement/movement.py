"""
MovementController - US-04 manual control SpiderPi
US-05 smooth walking animations
"""

import queue
import threading
import sys

from movement.chassis import TurnDirection


class MovementController:
    def __init__(self, board):
        self._board = board

        # SpiderPi SDK
        sys.path.append(
            "/home/pi/spiderpi/spiderpi_sdk/common_sdk/common"
        )

        import kinematics
        self._ik = kinematics.IK(board)

        # Start in neutral pose
        self._ik.stand(
            self._ik.initial_pos,
            t=1000
        )

        self._command_queue: queue.Queue = queue.Queue()
        self._running = True
        self._is_moving = False

        self._worker = threading.Thread(
            target=self._loop,
            daemon=True
        )
        self._worker.start()

    # -------------------------
    # Public API
    # -------------------------

    def forward(self, distance: int = 50):
        self._command_queue.put(("forward", distance))

    def backward(self, distance: int = 50):
        self._command_queue.put(("backward", distance))

    def strafe_left(self, distance: int = 50):
        self._command_queue.put(("left", distance))

    def strafe_right(self, distance: int = 50):
        self._command_queue.put(("right", distance))

    def turn(self, direction: TurnDirection):
        self._command_queue.put(("turn", direction))

    def stop(self):
        self._command_queue.put(("stop", None))

    def shutdown(self):
        self._running = False
        self._command_queue.put(("shutdown", None))

    # -------------------------
    # Animation helpers (US-05)
    # -------------------------

    def _smooth_stand(self):
        """
        Return smoothly to neutral pose.
        """
        self._ik.stand(
            self._ik.initial_pos,
            t=1000
        )

    # -------------------------
    # Worker thread
    # -------------------------

    def _loop(self):
        while self._running:
            try:
                cmd, value = self._command_queue.get(timeout=0.5)
            except queue.Empty:
                continue

            self._is_moving = True

            try:
                if cmd == "forward":
                    self._ik.go_forward(
                        self._ik.initial_pos,
                        2,
                        value,
                        60,
                        1
                    )

                elif cmd == "backward":
                    self._ik.back(
                        self._ik.initial_pos,
                        2,
                        value,
                        60,
                        1
                    )

                elif cmd == "left":
                    self._ik.left_move(
                        self._ik.initial_pos,
                        2,
                        value,
                        60,
                        1
                    )

                elif cmd == "right":
                    self._ik.right_move(
                        self._ik.initial_pos,
                        2,
                        value,
                        60,
                        1
                    )

                elif cmd == "turn":
                    if value == TurnDirection.LEFT:
                        self._ik.turn_left(
                            self._ik.initial_pos,
                            2,
                            20,
                            60,
                            1
                        )
                    else:
                        self._ik.turn_right(
                            self._ik.initial_pos,
                            2,
                            20,
                            60,
                            1
                        )

                elif cmd == "stop":
                    self._smooth_stand()

                elif cmd == "shutdown":
                    self._smooth_stand()
                    break

            except Exception as e:
                print("Movement error:", e)

            finally:
                self._is_moving = False

    # -------------------------
    # Status
    # -------------------------

    @property
    def is_moving(self):
        return self._is_moving