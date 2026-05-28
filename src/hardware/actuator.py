class Actuator:

    def __init__(self, id):
        self.id = id
        self._temperature = 40
        self._voltage = 7.4
        self.active = True

    # PROPERTY (netter dan get_ methods)
    @property
    def temperature(self):
        return self._temperature

    @property
    def voltage(self):
        return self._voltage

    # 🔥 BELANGRIJK: nodig voor jouw main.py
    def update_temperature(self, value):
        self._temperature = value

    def stop(self):
        self.active = False
        print(f"🛑 Actuator {self.id} gestopt")

    # optioneel: compatibiliteit met oude code
    def get_temperature(self):
        return self._temperature

    def get_voltage(self):
        return self._voltage