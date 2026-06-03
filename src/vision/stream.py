import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2 as cv
from turbojpeg import TurboJPEG


_PAGE = b"""\
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width">
<title>SpiderPi</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#1a1a1a;color:#ccc;font-family:'Courier New',monospace;
display:flex;flex-direction:column;align-items:center;min-height:100vh;padding:18px}
h1{font-size:20px;color:#ddd;margin-bottom:14px;letter-spacing:1px}
.wrap{display:flex;gap:14px;flex-wrap:wrap;justify-content:center;width:100%;max-width:980px}
.cam{flex:1 1 560px;max-width:660px}
.topbar{background:#2a2a2a;border:1px solid #444;border-bottom:none;
padding:6px 12px;display:flex;align-items:center;justify-content:space-between;
font-size:11px;color:#888}
.rec{display:flex;align-items:center;gap:6px}
.rec::before{content:'';width:8px;height:8px;border-radius:50%;background:#c00;
display:inline-block;animation:blink 1s steps(1) infinite}
@keyframes blink{0%,100%{opacity:1}50%{opacity:0}}
.stream{width:100%;display:block;background:#000;border:1px solid #444}
.controls{flex:0 0 230px;display:flex;flex-direction:column;gap:6px}
.label{font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;margin:2px 0}
.btn{padding:9px 0;font-family:'Courier New',monospace;
font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;cursor:pointer;
background:#333;color:#999;border:1px solid #555;transition:all .1s}
.btn:hover{background:#3a3a3a;color:#ddd;border-color:#777}
.btn:active{background:#444}
.btn.active{background:#444;color:#fff;border-color:#888}
.btn.stop{color:#a33;border-color:#555}
.btn.stop:hover{background:#3a2020;color:#e44;border-color:#a33}
.row{display:flex;gap:6px}
.row .btn{flex:1}
/* Kleurkiezer (US-02) -- orange accent per the wireframe */
.picker{margin-top:6px;border:1px solid #d2691e;background:#241c14;padding:10px}
.picker .title{color:#e8821e;font-size:11px;font-weight:700;text-transform:uppercase;
letter-spacing:1px;margin-bottom:8px}
.picker label{display:flex;align-items:center;gap:8px;font-size:12px;margin:5px 0;color:#caa}
.picker input[type=range]{flex:1;accent-color:#e8821e}
.preview{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:11px;color:#888}
.swatch{width:34px;height:18px;border:1px solid #666;display:inline-block}
/* Movement buttons (US-04, Anas) -- moved to the bottom-left, not restyled */
.movement{width:100%;max-width:980px;margin-top:14px}
.movement .grid{display:flex;gap:6px;flex-wrap:wrap}
.movement .grid .btn{flex:0 0 96px}
</style>
</head>
<body>
<h1>SpiderPi Tracking Dashboard</h1>
<div class="wrap">
 <div class="cam">
  <div class="topbar">
   <div class="rec">REC</div>
   <div>CAM-01</div>
  </div>
  <img class="stream" src="/stream">
 </div>
 <div class="controls">
  <div class="label">Tracking-modus</div>
  <button class="btn" onclick="sendMode('AprilTag',this)">AprilTag</button>
  <button class="btn" onclick="sendMode('Face',this)">Face</button>
  <button class="btn" onclick="sendMode('Color',this)">Color</button>
  <div class="row">
   <button class="btn stop" onclick="reset()">Reset</button>
   <button class="btn stop" onclick="fetch('/api/quit',{method:'POST'})">Stop</button>
  </div>
  <div class="picker">
   <div class="title">Kleurkiezer</div>
   <label>H <input type="range" min="0" max="179" value="115" id="h"></label>
   <label>S <input type="range" min="0" max="255" value="220" id="s"></label>
   <label>V <input type="range" min="0" max="255" value="170" id="v"></label>
   <div class="preview"><span class="swatch" id="swatch"></span> preview</div>
  </div>
 </div>
</div>

<!-- Movement controls (US-04, Anas) -- relocated to the bottom-left corner untouched -->
<div class="movement">
 <div class="label">Besturing</div>
 <div class="grid">
  <button class="btn" onmousedown="move('forward')" onmouseup="stopMove()">Forward</button>
  <button class="btn" onmousedown="move('backward')" onmouseup="stopMove()">Back</button>
  <button class="btn" onmousedown="move('left')" onmouseup="stopMove()">Left</button>
  <button class="btn" onmousedown="move('right')" onmouseup="stopMove()">Right</button>
  <button class="btn" onmousedown="move('turn_left')" onmouseup="stopMove()">Turn L</button>
  <button class="btn" onmousedown="move('turn_right')" onmouseup="stopMove()">Turn R</button>
 </div>
</div>

<script>

function sendMode(m,el){
 fetch('/api/mode',{method:'POST',body:m});
 document.querySelectorAll('.btn').forEach(b=>b.classList.remove('active'));
 if(el) el.classList.add('active');
}

/* US-04 movement */
let moveInterval = null;

function move(dir){
 fetch('/api/move',{method:'POST',body:dir});
 moveInterval = setInterval(()=>{
   fetch('/api/move',{method:'POST',body:dir});
 }, 300);
}

function stopMove(){
 clearInterval(moveInterval);
 fetch('/api/move',{method:'POST',body:'stop'});
}

function reset(){
 fetch('/api/reset',{method:'POST'});
 document.querySelectorAll('.btn').forEach(b=>b.classList.remove('active'));
 setTimeout(()=>location.reload(),1500);
}

/* US-02 color picker -- live, debounced POST of H,S,V to /api/color */
const H=document.getElementById('h'),S=document.getElementById('s'),
      V=document.getElementById('v'),SW=document.getElementById('swatch');
function hsv2css(h,s,v){ // OpenCV ranges: h 0-179, s/v 0-255
 h=h/179*360;s=s/255;v=v/255;
 const c=v*s,x=c*(1-Math.abs((h/60)%2-1)),m=v-c;let r=0,g=0,b=0;
 if(h<60){r=c;g=x}else if(h<120){r=x;g=c}else if(h<180){g=c;b=x}
 else if(h<240){g=x;b=c}else if(h<300){r=x;b=c}else{r=c;b=x}
 return `rgb(${Math.round((r+m)*255)},${Math.round((g+m)*255)},${Math.round((b+m)*255)})`;
}
let timer=null;
function pick(send){
 SW.style.background=hsv2css(+H.value,+S.value,+V.value);
 if(!send)return;
 clearTimeout(timer);
 timer=setTimeout(()=>fetch('/api/color',{method:'POST',
  body:`${H.value},${S.value},${V.value}`}),150);
}
[H,S,V].forEach(e=>e.addEventListener('input',()=>pick(true)));
pick(false);

</script>
</body>
</html>
"""


class MJPEGServer:
    def __init__(self, port: int = 8080, quality: int = 80, fps_limit: int = 20):
        self._port = port
        self._quality = quality
        self._jpeg = TurboJPEG()
        self._interval = 1.0 / fps_limit
        self._frame = None
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None

        self.commands: queue.Queue[str] = queue.Queue()

    def update_frame(self, frame: cv.typing.MatLike) -> None:
        with self._lock:
            self._frame = frame

    def _get_frame(self) -> cv.typing.MatLike | None:
        with self._lock:
            return self._frame

    def start(self) -> None:
        stream = self

        class _Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(_PAGE)

                elif self.path == "/stream":
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "multipart/x-mixed-replace; boundary=frame",
                    )
                    self.end_headers()

                    try:
                        while True:
                            t0 = time.monotonic()
                            frame = stream._get_frame()

                            if frame is not None:
                                buf: bytes = stream._jpeg.encode(  # type: ignore[assignment]
                                    frame, quality=stream._quality
                                )

                                self.wfile.write(
                                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                                    + buf
                                    + b"\r\n"
                                )

                                delay = stream._interval - (time.monotonic() - t0)
                                if delay > 0:
                                    time.sleep(delay)
                            else:
                                time.sleep(0.01)

                    except (BrokenPipeError, ConnectionResetError):
                        pass

                else:
                    self.send_error(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                data = self.rfile.read(length).decode().strip()

                # vision mode
                if self.path == "/api/mode":
                    if data in ("Idle", "AprilTag", "Face", "Color"):
                        stream.commands.put(data)

                # movement
                elif self.path == "/api/move":
                    stream.commands.put(data)

                # color picker body is "H,S,V"
                elif self.path == "/api/color":
                    stream.commands.put(f"color:{data}")

                elif self.path == "/api/reset":
                    stream.commands.put("reset")

                elif self.path == "/api/quit":
                    stream.commands.put("quit")

                self.send_response(204)
                self.end_headers()

            def log_message(self, format, *args):
                pass

        self._server = ThreadingHTTPServer(("0.0.0.0", self._port), _Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

        print(
            f"Dashboard: http://<pi-ip>:{self._port} | Stream: http://<pi-ip>:{self._port}/stream"
        )

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()