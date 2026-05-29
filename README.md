# SpiderPi OOP Project

## 1. Aan de slag: Verbinding maken

De SpiderPi start standaard op in **Access Point (AP) Modus**.

### Verbindingsgegevens
| Onderdeel | Waarde |
| :--- | :--- |
| **SSID** | Begint met `HW-` |
| **Wachtwoord** | `hiwonder` |
| **IP-adres** | `192.168.149.1` |
| **SSH gebruiker** | `pi` |
| **SSH wachtwoord** | `raspberrypi` |

Verbind je laptop met het `HW-` netwerk en open een terminal:
```bash
ssh pi@192.168.149.1
```

### Robot overzetten naar schoolnetwerk
```bash
bash /home/pi/connect_school.sh
```
> **Let op:** Je SSH-verbinding valt weg zodra de Wi-Fi wisselt. Wacht 30 seconden en maak opnieuw verbinding via `ping raspberrypi.local`.

---

## 2. Installatie

```bash
pip install opencv-python mediapipe dt-apriltags 'PyTurboJPEG<2'
```

Download het MediaPipe face model (alleen nodig voor gezichtsherkenning):
```bash
cd /home/pi/SpiderPi-Examen/src
wget -q https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
     -O face_landmarker_v2_with_blendshapes.task
```

---

## 3. Opstarten

```bash
cd /home/pi/SpiderPi-Examen
python3 src/main.py
```

Open de webinterface in je browser:
```
http://<ip-adres-robot>:8082
```

Het programma start in **Idle** modus. Kies een tracking modus via de knoppen op de webpagina of via het toetsenbord:

| Toets | Modus |
|-------|-------|
| `0` | Idle (camera stil) |
| `1` | AprilTag tracking |
| `2` | Gezichtsherkenning |
| `3` | Kleur tracking (blauw) |
| `r` | Reset (herstart script) |
| `q` | Stop |

### Extra opties
```bash
python3 src/main.py --mode AprilTag   # Start direct in een tracking modus
python3 src/main.py --port 8080       # Andere poort
```

---

## 4. Projectstructuur

```
src/
├── main.py              # RobotTracker klasse (startpunt)
├── face_landmarker_v2_with_blendshapes.task  # AI-model (MediaPipe)
└── vision/
    ├── camera.py        # Camera capture in eigen thread
    ├── pid.py           # PID controller
    ├── processor.py     # AprilTagProcessor, FaceProcessor, ColorProcessor
    ├── servo.py         # Gimbal aansturing (pan/tilt servo's)
    └── stream.py        # Webinterface + MJPEG video stream + API
```

---

## 5. Servo Configuratie

De camera gebruikt **PWM servo's** (niet de bus servo's van de poten):

| Servo | ID | Richting | Bereik | Midden |
|-------|----|----------|--------|--------|
| Tilt | 1 | Omhoog/omlaag | 1000-2000 | 1500 |
| Pan | 2 | Links/rechts | 500-2500 | 1500 |

Communicatie via `/dev/ttyAMA0` (Hiwonder Board SDK).

---

## 6. Documentatie

Zie `PROJECTDOCUMENTATIE.md` voor de volledige technische documentatie.
