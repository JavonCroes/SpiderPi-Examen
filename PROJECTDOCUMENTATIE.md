# SpiderPi -- Projectdocumentatie

## Inhoudsopgave

1. [Wat doet dit project?](#1-wat-doet-dit-project)
2. [Hardware](#2-hardware)
3. [Verbinding maken](#3-verbinding-maken)
4. [Installatie en opstarten](#4-installatie-en-opstarten)
5. [Webinterface en API](#5-webinterface-en-api)
6. [Projectstructuur](#6-projectstructuur)
7. [Hoe de tracking werkt](#7-hoe-de-tracking-werkt)
8. [De drie tracking-modi](#8-de-drie-tracking-modi)
9. [PID-instellingen](#9-pid-instellingen)
10. [Troubleshooting](#10-troubleshooting)
11. [De code uitbreiden](#11-de-code-uitbreiden)

---

## 1. Wat doet dit project?

De SpiderPi is een hexapod robot met een camera op een beweegbare gimbal. Dit project laat de camera automatisch doelwitten volgen door de gimbal aan te sturen met een PID controller. Er zijn drie tracking-modi:

- **AprilTag** -- volgt zwart-wit markerpatronen (tag36h11)
- **Gezicht** -- volgt een menselijk gezicht via Google MediaPipe AI
- **Kleur** -- volgt een blauw object via HSV-kleurfiltering

De gebruiker bedient het systeem via een **webinterface** in de browser of via toetsenbordcommando's in de SSH terminal.

---

## 2. Hardware

### Raspberry Pi 5
De computer van de robot. Draait Linux, geen beeldscherm aangesloten. Toegang via SSH.

### Camera
USB camera (icspring, levert alleen YUYV-formaat). Resolutie: 640x480. Zit op de gimbal gemonteerd.

> **Let op -- framerate:** De camera adverteert 30 fps, maar haalt dat niet in YUYV-modus. De echte bovengrens is **~22 fps** (gemeten met `v4l2-ctl`, los van OpenCV). Dit is een hardwarematige beperking van deze camera, geen USB-bandbreedte: USB 2.0 high-speed (480 Mbit/s) kan 640x480 YUYV @ 30 fps (~18 MB/s) ruim aan. Zie [Troubleshooting](#framerate-is-laag) voor hoe je de volle ~22 fps haalt.

### Gimbal (camera-houder)
Twee PWM servo's die de camera bewegen:

| Servo | ID | Richting | Bereik (microseconden) | Middenpositie |
|-------|----|----------|------------------------|---------------|
| Tilt | 1 | Omhoog/omlaag | 1000 -- 2000 | 1500 |
| Pan | 2 | Links/rechts | 500 -- 2500 | 1500 |

**Communicatie:** De Pi praat met de servo's via serial op `/dev/ttyAMA0`, via de Hiwonder Board SDK (`hiwonder.ros_robot_controller_sdk`). De servo's worden aangestuurd met `pwm_servo_set_position(duration, [[id, positie], ...])`.

**Bewegingssnelheid:** `duration=0.05` seconden per stap. Dit zorgt voor een vloeiende beweging zonder schokken.

> **Let op:** De tilt servo heeft een kleiner bereik (1000-2000) dan de pan servo (500-2500). Dit is een fysieke beperking om de camera niet tegen de behuizing te laten botsen.

---

## 3. Verbinding maken

### Optie A -- AP-modus (standaard)
De robot maakt een eigen Wi-Fi netwerk aan als hij niet met een ander netwerk verbonden is.

| Gegeven | Waarde |
|---------|--------|
| Wi-Fi naam | Begint met `HW-` |
| Wi-Fi wachtwoord | `hiwonder` |
| IP-adres robot | `192.168.149.1` |
| SSH gebruikersnaam | `pi` |
| SSH wachtwoord | `raspberrypi` |

```bash
ssh pi@192.168.149.1
```

### Optie B -- Schoolnetwerk
Verbind eerst via AP-modus, voer dan uit:
```bash
bash /home/pi/connect_school.sh
```

De SSH-verbinding valt weg zodra de Wi-Fi wisselt. Dit is normaal. Wacht 30 seconden en maak opnieuw verbinding:
```bash
ping raspberrypi.local
ssh pi@<nieuw-ip>
```

---

## 4. Installatie en opstarten

### Afhankelijkheden installeren
```bash
pip install opencv-python mediapipe dt-apriltags 'PyTurboJPEG<2'
```

> `PyTurboJPEG<2` is nodig omdat versie 2.x libjpeg-turbo 3.0+ vereist, die niet standaard op de Pi staat.

### Face model downloaden
Alleen nodig voor gezichtsherkenning:
```bash
cd /home/pi/SpiderPi-Examen/src
wget -q https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
     -O face_landmarker_v2_with_blendshapes.task
```

### Programma starten
```bash
cd /home/pi/SpiderPi-Examen
python3 src/main.py
```

De terminal toont:
```
Dashboard: http://<pi-ip>:8082  |  Stream: http://<pi-ip>:8082/stream
Commands: '0' = Idle | '1' = AprilTag | '2' = Face | '3' = Color | 'r' = Reset | 'q' = Quit
Switched to Idle mode
```

### Opstartopties
```bash
python3 src/main.py --mode AprilTag   # Start direct in een tracking modus
python3 src/main.py --mode Face
python3 src/main.py --mode Color
python3 src/main.py --port 8080       # Andere poort (standaard: 8082)
```

### Toetsenbordcommando's (SSH terminal)
| Toets + Enter | Actie |
|---------------|-------|
| `0` | Idle -- camera staat stil |
| `1` | AprilTag tracking |
| `2` | Gezichtsherkenning |
| `3` | Kleur tracking |
| `r` | Reset -- herstart het programma |
| `q` | Stop het programma |

Je kunt ook `Ctrl+C` gebruiken om te stoppen.

---

## 5. Webinterface en API

### Dashboard
Open in je browser:
```
http://<ip-adres-robot>:8082
```

De webpagina toont een live videostream met bedieningsknoppen: **AprilTag**, **Face**, **Color**, **Reset** en **Stop**. Het programma start in Idle -- er wordt niet getrackt totdat je een modus kiest.

De ruwe MJPEG stream (zonder knoppen) is beschikbaar op:
```
http://<ip-adres-robot>:8082/stream
```

### API-endpoints
De webknoppen sturen POST-verzoeken naar de volgende endpoints:

| Endpoint | Body | Actie |
|----------|------|-------|
| `POST /api/mode` | `AprilTag`, `Face`, `Color` of `Idle` | Wisselt van tracking modus |
| `POST /api/reset` | -- | Herstart het programma |
| `POST /api/quit` | -- | Stopt het programma |

### Videostream formaat
De stream gebruikt **MJPEG** (Motion JPEG): elke frame wordt als losse JPEG verstuurd. De browser toont ze snel achter elkaar als video. JPEG-encoding wordt gedaan door TurboJPEG (libjpeg-turbo met SIMD-versnelling).

- Standaard kwaliteit: 50 (instelbaar in `main.py`)
- FPS limiet: 20 frames per seconde
- Standaard poort: 8082

---

## 6. Projectstructuur

```
SpiderPi-Examen/
├── README.md
├── PROJECTDOCUMENTATIE.md       <- dit bestand
├── .gitignore
└── src/
    ├── main.py                  <- startpunt, RobotTracker klasse
    ├── face_landmarker_v2_with_blendshapes.task  <- AI-model (MediaPipe)
    └── vision/
        ├── camera.py            <- camera capture in eigen thread
        ├── pid.py               <- PID controller
        ├── processor.py         <- alle vision processors (AprilTag, Face, Color)
        ├── servo.py             <- gimbal aansturing via Hiwonder Board SDK
        └── stream.py            <- HTTP server: webpagina, MJPEG stream, API
```

### Wat doet elk bestand?

| Bestand | Klasse | Functie |
|---------|--------|---------|
| `main.py` | `RobotTracker` | Verbindt alles: leest camera, stuurt frames naar processor, berekent PID-correctie, stuurt servo's aan, streamt video naar browser |
| `camera.py` | `Camera` | Leest camera-frames in een eigen thread. Gebruikt `threading.Event` om de hoofdloop te signaleren wanneer een nieuw frame klaar is |
| `processor.py` | `VisionProcessor` (abstract), `AprilTagProcessor`, `FaceProcessor`, `ColorProcessor` | Elk processor analyseert een frame en geeft terug: het geannoteerde frame, de afwijking in pixels (error_x, error_y), en of een doelwit gevonden is |
| `pid.py` | `PID` | Berekent hoeveel de servo moet bewegen op basis van de afwijking. Heeft anti-windup om overshooting te voorkomen |
| `servo.py` | `GimbalControl` | Stuurt de twee PWM servo's aan via de Hiwonder Board SDK. Begrenst posities tot het veilige bereik |
| `stream.py` | `MJPEGServer` | Draait een HTTP-server met de webpagina, de MJPEG videostream, en de API-endpoints voor de knoppen |

### Threading-overzicht

Het programma draait met meerdere threads:

| Thread | Taak |
|--------|------|
| Hoofdthread | Leest camera-frames, stuurt ze door naar inferentie-thread en stream |
| Camera thread | Haalt continu frames op van de camera hardware |
| Inferentie thread | Draait de detectie (AprilTag/Face/Color) en PID-berekening |
| Web-commando thread | Leest knopopdrachten van de webpagina en voert ze uit |
| Stream thread(s) | Encodeert frames naar JPEG en stuurt ze naar de browser |
| Input thread | Leest toetsenbordcommando's via SSH |

Detectie en streaming zijn gescheiden zodat de videostream nooit wacht op een trage detectie.

---

## 7. Hoe de tracking werkt

De tracking-loop verwerkt elk frame als volgt:

```
Camera-frame (640x480)
    |
    v
Processor: herken doelwit, bereken middelpunt
    |
    v
Bereken afwijking: error_x = doelwit_x - (640/2)
                   error_y = doelwit_y - (480/2)
    |
    v
Dode zone check: als |error| < 15 pixels -> servo stil, PID reset
    |
    v
PID-controller: bereken servo-correctie op basis van de afwijking
    |
    v
Gimbal: pas servo-positie aan (huidige positie + PID-output)
    |
    v
Geannoteerd frame naar browser sturen
```

### Dode zone
Als het doelwit binnen 15 pixels van het midden zit, doet de camera niets. Dit voorkomt dat de servo constant kleine correcties maakt en gaat trillen. De PID wordt gereset zodat er geen opgebouwde integraal meegaat naar de volgende beweging.

### Idle modus
In Idle modus wordt geen detectie gedraaid. De camera staat stil in de middenpositie. Zodra je een tracking modus kiest, start de detectie.

### Reset
De Reset-knop herstart het volledige Python-proces via `os.execv()`. De camera centreert eerst, dan vervangt het proces zichzelf. De webpagina herlaadt automatisch na 2 seconden.

---

## 8. De drie tracking-modi

### AprilTag (tag36h11)
Herkent AprilTag markerpatronen in het camerabeeld. Gebruikt de `dt-apriltags` bibliotheek.

- Converteert frame naar grijswaarden (AprilTags zijn zwart-wit)
- Detector draait op 2 CPU-threads
- `quad_decimate=1.5`: verkleint de zoekresolutie voor snelheid (mist dan mogelijk kleine tags op afstand)
- Als meerdere tags in beeld: volgt de grootste (= dichtstbijzijnde)
- Positie: middelpunt van de tag

### Gezicht (MediaPipe Face Landmarker)
Herkent een menselijk gezicht via het MediaPipe AI-model. Geeft 478 landmarks (gezichtspunten) terug.

- Model: `face_landmarker_v2_with_blendshapes.task` (~30MB)
- Draait in VIDEO-modus (sneller dan per-frame IMAGE-modus)
- Bounding box wordt berekend met 4 landmarks: voorhoofd (10), kin (152), linkeroor (234), rechteroor (454)
- Positie: middelpunt van de bounding box

### Kleur (HSV filtering)
Volgt een blauw object door te filteren op kleur in het HSV-kleurmodel.

- Standaard HSV-bereik: H=100-130, S=120-255, V=50-255 (blauw)
- Ruis wordt verwijderd met morphological open + close (9x9 ellips kernel)
- Minimale oppervlakte: 500 pixels (kleinere objecten worden genegeerd)
- Volgt het grootste blauwe object in beeld
- Positie: middelpunt van de bounding box

Om een andere kleur te volgen, pas de HSV-waarden aan in `processor.py` bij `ColorProcessor.__init__()`.

---

## 9. PID-instellingen

De PID controller berekent hoeveel de servo moet bewegen per frame. Er zijn twee controllers: een voor pan (links/rechts) en een voor tilt (op/neer). Beide gebruiken dezelfde instellingen.

| Parameter | Waarde | Betekenis |
|-----------|--------|-----------|
| Kp | 0.20 | Sterkte reactie op huidige afwijking |
| Ki | 0.01 | Correctie van langdurige kleine restfouten |
| Kd | 0.04 | Remt af bij snelle veranderingen (demping) |
| Output limieten | -40 tot +40 | Maximale servo-stap per frame |
| Dode zone | 15 pixels | Onder deze afwijking: servo stil |

### Tuning tips
- **Camera trilt/oscilleert:** Verhoog Kd of verlaag Kp
- **Camera reageert te traag:** Verhoog Kp of verhoog de output limieten
- **Camera stopt net naast het doel:** Verhoog Ki (voorzichtig, te hoog = overshooting)
- **Anti-windup:** De integraal wordt begrensd zodat `Ki x integraal` nooit groter wordt dan de output limiet
- **Derivative-kick voorkomen:** De eerste berekening na een reset (`clear()`) -- bij moduswissel, dode zone, of als het doel even weg is -- gebruikt geen D-term. Anders zou de plotselinge grote afwijking de servo in een keer naar de maximale stap duwen en een schok geven. De D-term doet pas vanaf het tweede frame weer mee.

De PID-waarden staan in `main.py` bij `RobotTracker.__init__()`.

---

## 10. Troubleshooting

### Camera start niet / `can't open camera by index`
Een ander proces gebruikt de camera al:
```bash
ps aux | grep python3
kill <PID>
```

### `ModuleNotFoundError: No module named '...'`
Installeer de ontbrekende bibliotheek:
```bash
pip install opencv-python        # voor cv2
pip install mediapipe             # voor gezichtsherkenning
pip install dt-apriltags          # voor AprilTag detectie
pip install 'PyTurboJPEG<2'      # voor JPEG encoding in de stream
```

### `RuntimeError: Unable to open file at .../face_landmarker...task`
Het AI-model bestand ontbreekt. Download het:
```bash
cd /home/pi/SpiderPi-Examen/src
wget -q https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task \
     -O face_landmarker_v2_with_blendshapes.task
```

### Stream is traag of bevriest
- Verlaag JPEG-kwaliteit: in `main.py`, verander `quality=50` naar `quality=30`
- Zorg dat je laptop op hetzelfde netwerk zit als de robot
- Controleer CPU-belasting: `htop` in de terminal

### Framerate is laag
De camera haalt maximaal **~22 fps** in YUYV-modus (de 30 fps uit de specificatie is niet haalbaar -- zie [Hardware](#2-hardware)). Krijg je duidelijk minder, controleer dan het volgende.

**1. Buffergrootte (de grootste valkuil).** Zet in `camera.py` **niet** `CAP_PROP_BUFFERSIZE=1`. Op de V4L2-driver van deze camera laat een enkele buffer de framerate van ~22 naar ~17 fps zakken (~33% verlies).

- *Waarom:* V4L2 levert frames via een wachtrij van buffers. De camera vult een buffer terwijl jij de vorige uitleest -- dat overlapt (pipelining). Met maar 1 buffer kan de camera de volgende frame pas opvangen nadat jij de enige buffer hebt uitgelezen en teruggegeven; in die tussentijd mist hij een frame-slot en wacht hij op het volgende. Resultaat: ~1 op de 4 frames valt weg (22 x 3/4 ≈ 17).
- *Waarom het veilig weg kan:* de `Camera`-thread leest continu en bewaart alleen de nieuwste frame. De wachtrij loopt daardoor nooit vol -- er is altijd maar ~1 frame onderweg, ongeacht de bufferdiepte. Je krijgt dus de hogere framerate zonder extra vertraging. `BUFFERSIZE=1` was hier dus overbodig.

**2. Meet waar het verlies zit.** Toont de stream in een lichte modus (Idle/Color) ook al lage fps? Dan ligt het aan de camera-capture, niet aan de detectie. Is alleen **Face** traag? Dan is het MediaPipe-model de bottleneck, niet de camera.

**3. Controleer de ruwe camera-snelheid** los van de code:
```bash
v4l2-ctl -d /dev/video0 --set-fmt-video=width=640,height=480,pixelformat=YUYV \
         --stream-mmap --stream-count=120
```
Dit toont de fps die de driver levert. Zit dat rond 22 fps en de applicatie lager, dan ligt het aan een software-instelling (zie punt 1).

### SSH bevriest na `connect_school.sh`
Dit is normaal. De Wi-Fi wisselt, de verbinding valt weg. Wacht 30 seconden en maak opnieuw verbinding.

---

## 11. De code uitbreiden

### Een nieuwe tracking-modus toevoegen

1. Maak een nieuwe klasse in `src/vision/processor.py` die overerft van `VisionProcessor`:

```python
class MijnProcessor(VisionProcessor):
    def get_error(self, frame):
        h, w = frame.shape[:2]
        _draw_crosshairs(frame)

        # Jouw detectie-logica hier...
        # Als niets gevonden:
        return frame, 0, 0, False

        # Als gevonden (cx, cy = middelpunt van het object):
        return frame, cx - w // 2, cy - h // 2, True
```

2. Voeg de processor toe in `src/main.py`:

```python
# Bij de imports:
from vision.processor import MijnProcessor

# In __init__, bij self._processors:
"MijnModus": MijnProcessor(),

# In VALID_MODES:
VALID_MODES = {"0": "Idle", "1": "AprilTag", "2": "Face", "3": "Color", "4": "MijnModus"}
```

3. Voeg een knop toe in `src/vision/stream.py` in de HTML (in de `bottombar` div):
```html
<button class="btn" onclick="send('MijnModus',this)">MijnModus</button>
```

De PID, gimbal en stream werken automatisch mee met de nieuwe processor.
