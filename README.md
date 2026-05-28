# SpiderPi OOP Project

Hexapod robot met camera tracking (AprilTag, gezicht en kleur) via een OOP-architectuur in Python.

## Vereisten

- Raspberry Pi 5 met Hiwonder SpiderPi
- Python 3.11+
- USB/CSI camera op gimbal

## Installatie

```bash
pip install opencv-python mediapipe dt-apriltags 'PyTurboJPEG<2'
```

Download het MediaPipe face model (alleen nodig voor gezichtsherkenning):
```bash
cd src
wget -q https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
     -O face_landmarker_v2_with_blendshapes.task
```

## Opstarten

```bash
python3 src/main.py
```

Open de webinterface in je browser:
```
http://<pi-ip>:8082
```

Het programma start in idle modus. Kies een tracking modus via de knoppen op de webpagina of via het toetsenbord in de SSH terminal:

| Toets | Modus |
|-------|-------|
| `0` | Idle |
| `1` | AprilTag |
| `2` | Gezicht |
| `3` | Kleur |
| `r` | Reset |
| `q` | Stop |

### Extra opties

```bash
python3 src/main.py --mode AprilTag   # Start direct in een tracking modus
python3 src/main.py --port 8080       # Andere poort
```

## Projectstructuur

```
src/
├── main.py              # RobotTracker klasse — startpunt
└── vision/
    ├── camera.py        # Camera capture in eigen thread
    ├── pid.py           # PID controller
    ├── processor.py     # AprilTagProcessor, FaceProcessor, ColorProcessor
    ├── servo.py         # Gimbal aansturing (pan/tilt)
    └── stream.py        # Webinterface + MJPEG stream
```

## Verbinding met de robot

### AP-modus (standaard)

| Gegeven | Waarde |
|---------|--------|
| Wi-Fi naam | Begint met `HW-` |
| Wachtwoord | `hiwonder` |
| IP-adres | `192.168.149.1` |
| SSH gebruiker | `pi` |
| SSH wachtwoord | `raspberrypi` |

```bash
ssh pi@192.168.149.1
```

### Schoolnetwerk

```bash
bash /home/pi/connect_school.sh
# Wacht 30 seconden, zoek daarna het nieuwe IP:
ping raspberrypi.local
ssh pi@<nieuw-ip>
```
