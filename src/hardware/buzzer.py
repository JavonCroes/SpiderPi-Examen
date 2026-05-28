import time
from gpiozero import Buzzer as GZ_Buzzer

class Buzzer:
    def __init__(self, gpio_pin=None):
        self.gpio_pin = gpio_pin
        self.device = None
        
        if self.gpio_pin is not None:
            try:
                self.device = GZ_Buzzer(self.gpio_pin)
                print(f"✅ Buzzer geactiveerd op pin {self.gpio_pin}")
            except Exception as e:
                print(f"⚠️ Buzzer hardware bezet: {e}. Gebruik simulatie.")

    def beep(self, duration=0.2):
        if self.device:
            self.device.on()
            time.sleep(duration)
            self.device.off()
            print("🔊 PIEP! (Fysiek)")
        else:
            print("🔔 PIEP! (Simulatie geen hardware beschikbaar)")