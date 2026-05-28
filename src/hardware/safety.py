class SafetySystem:

    def __init__(self, servos, buzzer):
        self.servos = servos
        self.buzzer = buzzer
        self.max_temp = 65

    def check(self):
        for servo in self.servos:
            temp = servo.temperature

            if temp > self.max_temp:
                print(f"?? WAARSCHUWING: Servo {servo.id} te heet ({temp}°C)")
                self.emergency_stop()
                return

    def emergency_stop(self):
        print("!!! ROBOT STOP !!!")

        for servo in self.servos:
            print(f"?? Servo {servo.id} uitgeschakeld")
            servo.stop()

        if self.buzzer:
            self.buzzer.beep()