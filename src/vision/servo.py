import threading

from hiwonder.ros_robot_controller_sdk import Board


def _serialize_board_writes(board: Board) -> None:
    """Wrap the Board's packet writer with a lock (idempotent).

    The gimbal (PWM servos) and the chassis legs (bus servos, driven from the
    ChassisController worker thread by the IK library) share this Board's single
    serial port. Every command funnels through ``buf_write`` -> ``port.write``,
    which has no lock, so concurrent writes from two threads could interleave
    bytes and corrupt a packet. Replacing ``buf_write`` with a locked version
    makes each packet atomic; setting it as an instance attribute means calls
    made inside the SDK (and the encrypted IK .so) go through the lock too.
    """
    if getattr(board, "_buf_write_locked", False):
        return
    lock = threading.Lock()
    original = board.buf_write

    def locked_buf_write(func, data):
        with lock:
            return original(func, data)

    # setattr (rather than plain assignment) because these are dynamic
    # attributes the Board class does not statically declare.
    setattr(board, "buf_write", locked_buf_write)
    setattr(board, "_buf_write_locked", True)


class GimbalControl:
    PAN_MIN, PAN_MAX = 500, 2500
    TILT_MIN, TILT_MAX = 1000, 2000
    CENTER = 1500

    def __init__(self, pan_id: int = 2, tilt_id: int = 1, board: Board | None = None):
        # Accept a shared Board so the chassis can drive the leg servos on the
        # same serial connection; constructing a second Board would open
        # /dev/ttyAMA0 twice and corrupt the receive stream.
        self._board = board or Board()
        _serialize_board_writes(self._board)
        self._pan_id = pan_id
        self._tilt_id = tilt_id
        self._pan_pos = self.CENTER
        self._tilt_pos = self.CENTER
        self._apply()

    @property
    def board(self) -> Board:
        return self._board

    @property
    def pan_pos(self) -> int:
        """Current pan servo position (already clamped to [PAN_MIN, PAN_MAX])."""
        return int(self._pan_pos)

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
