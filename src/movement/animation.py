from movement.movement import MovementController


class AnimationController:
    """
    Handles smooth animation transitions.
    """

    def __init__(self, board):
        self._board = board

        import sys
        sys.path.append(
            "/home/pi/spiderpi/spiderpi_sdk/common_sdk/common"
        )

        import kinematics
        self._ik = kinematics.IK(board)

    def stand(self):
        """
        Return to neutral pose smoothly.
        """
        self._ik.stand(
            self._ik.initial_pos,
            t=500
        )

    def smooth_start(self):
        """
        Move into a stable walking pose.
        """
        self._ik.stand(
            self._ik.initial_pos,
            t=300
        )

    def smooth_stop(self):
        """
        Smoothly return to rest.
        """
        self._ik.stand(
            self._ik.initial_pos,
            t=500
        )