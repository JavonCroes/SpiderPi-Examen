class PID:
    def __init__(
        self,
        Kp: float,
        Ki: float,
        Kd: float,
        setpoint: float = 0,
        output_limits: tuple[float | None, float | None] = (None, None),
    ):
        self.Kp = Kp
        self.Ki = Ki
        self.Kd = Kd
        self.setpoint = setpoint
        self._min, self._max = output_limits
        self._integral = 0.0
        self._prev_error = 0.0
        self._first = True

    @property
    def output_limits(self) -> tuple[float | None, float | None]:
        return self._min, self._max

    @output_limits.setter
    def output_limits(self, limits: tuple[float | None, float | None]) -> None:
        self._min, self._max = limits

    def clear(self) -> None:
        self._integral = 0.0
        self._prev_error = 0.0
        self._first = True

    def update(self, measurement: float, dt: float = 0.03) -> float:
        error = self.setpoint - measurement
        self._integral += error * dt

        # Anti-windup: clamp integral so Ki * integral stays within output limits
        if self.Ki != 0:
            if self._max is not None:
                self._integral = min(self._integral, self._max / self.Ki)
            if self._min is not None:
                self._integral = max(self._integral, self._min / self.Ki)

        # Skip the derivative on the first update after a clear/reset so a fresh
        # large error doesn't produce a derivative kick that slams the output.
        if self._first:
            derivative = 0.0
            self._first = False
        else:
            derivative = (error - self._prev_error) / dt
        output = self.Kp * error + self.Ki * self._integral + self.Kd * derivative

        if self._max is not None:
            output = min(output, self._max)
        if self._min is not None:
            output = max(output, self._min)

        self._prev_error = error
        return output
