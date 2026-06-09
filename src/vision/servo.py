import threading

from hiwonder.ros_robot_controller_sdk import Board


def _serialize_board_writes(board: Board) -> None:
    # Gimbal en poten delen dezelfde verbinding dit slot zorgt dat hun
    # commando's elkaar niet door de war sturen.
    if getattr(board, "_buf_write_locked", False):
        return
    lock = threading.Lock()
    original = board.buf_write

    def locked_buf_write(func, data):
        with lock:
            return original(func, data)

    setattr(board, "buf_write", locked_buf_write)
    setattr(board, "_buf_write_locked", True)


class GimbalControl:
    # Grenzen van de servo's buiten deze waarden schrijven we nooit.
    PAN_MIN, PAN_MAX = 500, 2500
    TILT_MIN, TILT_MAX = 1000, 2000
    CENTER = 1500

    def __init__(self, pan_id: int = 2, tilt_id: int = 1, board: Board | None = None):
        # Een gedeelde Board voor gimbal en chassis een tweede zou de bus
        # in de war sturen.
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
        # Huidige pan-stand hier kijkt de body-rotatie naar.
        return int(self._pan_pos)

    def _apply(self, duration: float = 0.05) -> None:
        # Klem de standen binnen de grenzen en schrijf ze naar de servo's.
        self._pan_pos = max(self.PAN_MIN, min(self.PAN_MAX, int(self._pan_pos)))
        self._tilt_pos = max(self.TILT_MIN, min(self.TILT_MAX, int(self._tilt_pos)))
        self._board.pwm_servo_set_position(
            duration, [[self._tilt_id, self._tilt_pos], [self._pan_id, self._pan_pos]]
        )

    def move(self, pan_delta: float, tilt_delta: float) -> None:
        # Beweeg een stapje vanaf de huidige stand.
        self._pan_pos += pan_delta
        self._tilt_pos += tilt_delta
        self._apply()

    def center(self) -> None:
        # Terug naar het midden.
        self._pan_pos = self.CENTER
        self._tilt_pos = self.CENTER
        self._apply()
