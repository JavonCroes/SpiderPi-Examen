from hiwonder.ros_robot_controller_sdk import Board


class GimbalControl:
    PAN_MIN, PAN_MAX = 500, 2500
    TILT_MIN, TILT_MAX = 1000, 2000
    CENTER = 1500

    def __init__(self, pan_id: int = 2, tilt_id: int = 1):
        self._board = Board()
        self._pan_id = pan_id
        self._tilt_id = tilt_id
        self._pan_pos = self.CENTER
        self._tilt_pos = self.CENTER
        self._apply()

    def _apply(self, duration: float = 0.05) -> None:
        self._pan_pos = max(self.PAN_MIN, min(self.PAN_MAX, int(self._pan_pos)))
        self._tilt_pos = max(self.TILT_MIN, min(self.TILT_MAX, int(self._tilt_pos)))
        self._board.pwm_servo_set_position(
            duration, [[self._tilt_id, self._tilt_pos], [self._pan_id, self._pan_pos]]
        )

    def move(self, pan_delta: float, tilt_delta: float) -> None:
        self._pan_pos += pan_delta
        self._tilt_pos += tilt_delta
        self._apply()

    def center(self) -> None:
        self._pan_pos = self.CENTER
        self._tilt_pos = self.CENTER
        self._apply()
