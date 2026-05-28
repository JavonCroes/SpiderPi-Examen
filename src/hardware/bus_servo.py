import hardware.BusServoCmd as BusServoCmd
from hardware.actuator import Actuator

class BusServo(Actuator):

    def move(self, position, time=500):
        print(f"BusServo {self.id} -> {position} in {time}ms")
        BusServoCmd.serial_serro_wirte_cmd(self.id, 1, int(position), int(time))

    def read_position(self):
        BusServoCmd.serial_servo_read_cmd(self.id, 28) # 28 = POS_READ
        return BusServoCmd.serial_servo_get_rmsg(28)