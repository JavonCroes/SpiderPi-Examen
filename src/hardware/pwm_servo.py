from common.ros_robot_controller_sdk import Board
from hardware.actuator import Actuator

class PWMServo(Actuator):
    def __init__(self, servo_id):
            super().__init__(servo_id)
            self.board = Board() # Initialiseer het Hiwonder Board
    
    def set_angle(self, position, time=500):
        # De officiële methode van de SpiderPi SDK:
        self.board.pwm_servo_set_position(time/1000, [[self.id, int(position)]])
    
    