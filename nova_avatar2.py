# All avatars + WASAPI loopback + Echo injection
# pip install pyaudiowpatch numpy pillow
# You need VB Cable Driver to make the echo engine for these  Avaters to  work. It is free. Install it.
# Set System Sound Output  in Windows to Cable INPUT. Set  System Sound INPUT to Cable Output
# Then in Control Panel Sound  - for Sound Input make sure Cable input is default and for Recording Cable Output is selected
# Then click on properties for Cable Output then LISTEN and make sure your audio output device is selected. (then click APPLY - Important)
# This audio output device you just selected must be the same one you select on the combo box for Nova_avatar2.py

import tkinter as tk
import threading
import math
import time
import sys
import os
import random
import colorsys
import collections
import numpy as np
from echo_engine import EchoEngine
try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("pip install pyaudiowpatch")
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageEnhance, ImageTk
    PIL_OK = True
except ImportError:
    PIL_OK = False
    print("WARNING: pip install pillow  (TextureMappedSphere unavailable)")

RADIUS = 240  # half of BASE_DIAMETER=480, used by new avatars


def _lerp(a, b, t): return a + (b - a) * t
def _clamp(v, lo, hi): return max(lo, min(hi, v))
def _blend_hex(c1, c2, t):
    def p(c): c=c.lstrip('#'); return int(c[0:2],16),int(c[2:4],16),int(c[4:6],16)
    r1,g1,b1=p(c1); r2,g2,b2=p(c2)
    return "#{:02x}{:02x}{:02x}".format(int(r1+(r2-r1)*t),int(g1+(g2-g1)*t),int(b1+(b2-b1)*t))
def _stipple(alpha):
    if alpha<0.12: return 'gray12'
    elif alpha<0.25: return 'gray25'
    elif alpha<0.50: return 'gray50'
    elif alpha<0.75: return 'gray75'
    return ''

# ─────────────────────────────────────────────
# Audio config
# ─────────────────────────────────────────────
BLOCK_SIZE  = 2048
NOISE_GATE  = 0.003
GAIN        = 6.0
ATTACK      = 0.85
DECAY       = 0.12
LEVELS      = 32

_lock       = threading.Lock()
_smooth_amp = 0.0

# Shared PCM ring-buffer (mono float32) fed by the loopback callback
_pcm_buf      = collections.deque()
_pcm_buf_lock = threading.Lock()
_pcm_sr       = 44100   # filled in by _start_loopback
_pcm_ch       = 2       # filled in by _start_loopback


# ─────────────────────────────────────────────
# Audio callback
# ─────────────────────────────────────────────
def _audio_callback(in_data, frame_count, time_info, status):
    global _smooth_amp
    pcm = np.frombuffer(in_data, dtype=np.float32).copy()

    if len(pcm) >= frame_count:
        mono = pcm[:frame_count * _pcm_ch]
        if _pcm_ch == 2 and len(mono) == frame_count * 2:
            mono = mono.reshape(-1, 2).mean(axis=1)
        elif len(mono) > frame_count:
            mono = mono[:frame_count]
        with _pcm_buf_lock:
            _pcm_buf.extend(mono.tolist())
            max_len = _pcm_sr * 2
            while len(_pcm_buf) > max_len:
                _pcm_buf.popleft()

    if _pcm_ch == 2 and len(pcm) == frame_count * 2:
        vis = pcm.reshape(-1, 2).mean(axis=1)
    else:
        vis = pcm[:frame_count]
    rms = float(np.sqrt(np.mean(vis ** 2)))
    if rms < NOISE_GATE:
        rms = 0.0
    amp = min(1.0, rms * GAIN)
    with _lock:
        prev        = _smooth_amp
        _smooth_amp = prev + (ATTACK if amp > prev else DECAY) * (amp - prev)
    return (None, pyaudio.paContinue)


# ─────────────────────────────────────────────
# Loopback start
# ─────────────────────────────────────────────
def _start_loopback():
    global _pcm_sr, _pcm_ch
    pa = pyaudio.PyAudio()
    try:
        wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out = pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        print(f"Default output: {default_out['name']}")
        loopback = None
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice") and default_out["name"] in dev["name"]:
                loopback = dev
                break
        if loopback is None:
            for i in range(pa.get_device_count()):
                dev = pa.get_device_info_by_index(i)
                if dev.get("isLoopbackDevice"):
                    loopback = dev
                    break
        if loopback is None:
            print("No loopback device found.")
            return None, pa
        sr = int(loopback["defaultSampleRate"])
        ch = loopback["maxInputChannels"]
        _pcm_sr = sr
        _pcm_ch = ch
        print(f"Loopback: {loopback['name']}  {sr} Hz / {ch} ch")
        stream = pa.open(format=pyaudio.paFloat32, channels=ch, rate=sr,
                         input=True, input_device_index=loopback["index"],
                         frames_per_buffer=BLOCK_SIZE,
                         stream_callback=_audio_callback)
        stream.start_stream()
        return stream, pa
    except Exception as e:
        print(f"Loopback error: {e}")
        return None, pa


class EchoInjector:
    CHUNK = 512

    def __init__(self, pa, sample_rate, intensity=0.47, delay_ms=144.0):
        self._pa = pa
        self._sr = sample_rate
        self._enabled = False
        self._thread = None
        self._stop_evt = threading.Event()
        self._echo = EchoEngine()
        self._echo.enabled = True
        self._echo.intensity = intensity
        self._echo.delay_ms = delay_ms
        self._in_idx  = self._find_device("CABLE Output", input=True)
        self._out_idx = None
        print(f"EchoInjector: capture={self._in_idx}, playback={self._out_idx}")

    def _find_device(self, keyword, input=True):
        key = 'maxInputChannels' if input else 'maxOutputChannels'
        print(f"\n--- All {'input' if input else 'output'} devices ---")
        for i in range(self._pa.get_device_count()):
            dev = self._pa.get_device_info_by_index(i)
            if dev[key] > 0:
                print(f"  [{i}] {dev['name']}")
            if keyword.lower() in dev['name'].lower() and dev[key] > 0:
                print(f"  >>> MATCHED [{i}] {dev['name']}")
                return i
        print(f"  >>> NO MATCH for '{keyword}', using default")
        return None

    @property
    def enabled(self):
        return self._enabled

    def set_enabled(self, value: bool):
        if value and not self._enabled:
            self._echo.enabled = True
            self._start()
        elif not value and self._enabled:
            self._stop()
        self._enabled = value

    def set_intensity(self, v: float):
        self._echo.intensity = float(np.clip(v, 0.0, 1.0))

    def set_delay(self, v: float):
        self._echo.delay_ms = float(np.clip(v, 60.0, 480.0))

    def _start(self):
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print("EchoInjector: started")

    def _stop(self):
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=2)
        print("EchoInjector: stopped")

    def _run(self):
        try:
            stream_in = self._pa.open(
                format=pyaudio.paFloat32, channels=1, rate=self._sr,
                input=True, input_device_index=self._in_idx,
                frames_per_buffer=self.CHUNK,
            )
            print(f"EchoInjector: streams opened OK at {self._sr} Hz")
            stream_out = self._pa.open(
                format=pyaudio.paFloat32, channels=1, rate=self._sr,
                output=True, output_device_index=self._out_idx,
                frames_per_buffer=self.CHUNK,
            )
        except Exception as e:
            print(f"EchoInjector: cannot open streams: {e}")
            return

        while not self._stop_evt.is_set():
            try:
                raw = stream_in.read(self.CHUNK, exception_on_overflow=False)
                block = np.frombuffer(raw, dtype=np.float32).copy()
                wet = self._echo.process_array(block, self._sr)
                stream_out.write(wet.tobytes())
            except Exception:
                break

        try:
            stream_in.stop_stream();  stream_in.close()
            stream_out.stop_stream(); stream_out.close()
        except Exception:
            pass


# ═════════════════════════════════════════════════════════════════════════════
# BASE CLASS
# ═════════════════════════════════════════════════════════════════════════════
class BaseAvatarWindow(tk.Toplevel):
    LEVELS        = LEVELS
    BG            = "#000000"
    MASK_COLOR    = "#00FF00"
    SCALE_MIN     = 0.3
    SCALE_MAX     = 2.0
    SCALE_STEP    = 0.1
    BASE_DIAMETER = 480

    def __init__(self, master, title="Avatar"):
        super().__init__(master)
        self.title(title)
        self._scale_factor  = 1.0
        self._base_diameter = self.BASE_DIAMETER
        self._rect_mode     = False
        try:
            self.overrideredirect(True)
            self.wm_attributes("-transparentcolor", self.MASK_COLOR)
            self.configure(bg=self.MASK_COLOR)
        except Exception:
            pass
        self.wm_attributes("-topmost", True)
        self._update_window_size()
        self.center_on_screen()
        self._drag_data = {"x": 0, "y": 0}
        self.bind("<Button-1>",   self._start_drag)
        self.bind("<B1-Motion>",  self._do_drag)
        self.bind("<MouseWheel>", self._on_mouse_wheel)
        self.bind("<Button-4>",   self._on_mouse_wheel)
        self.bind("<Button-5>",   self._on_mouse_wheel)
        self.canvas = tk.Canvas(self, bg=self.MASK_COLOR, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>",  self._on_configure)
        self.canvas.bind("<MouseWheel>", self._on_mouse_wheel)
        self.canvas.bind("<Button-4>",   self._on_mouse_wheel)
        self.canvas.bind("<Button-5>",   self._on_mouse_wheel)
        self.level            = 0
        self._running         = True
        self.pad              = 8
        self._animation_timer = None

    # ── shape toggle ──────────────────────────────────────────────────────
    def _draw_bg(self, cx, cy, r, color=None):
        fill = color if color else self.BG
        if self._rect_mode:
            w = max(1, self.canvas.winfo_width())
            h = max(1, self.canvas.winfo_height())
            self.canvas.create_rectangle(0, 0, w, h, fill=fill, outline=fill)
        else:
            self.canvas.create_oval(cx-r, cy-r, cx+r, cy+r, fill=fill, outline=fill)

    def set_rect_mode(self, val: bool):
        self._rect_mode = val
        bg = self.BG if val else self.MASK_COLOR
        self.configure(bg=bg)
        self.canvas.configure(bg=bg)

    # ── existing helpers ──────────────────────────────────────────────────
    def _on_configure(self, e):
        self.redraw()

    def _update_window_size(self):
        d = int(self._base_diameter * self._scale_factor)
        try:
            g = self.geometry()
            if '+' in g:
                parts = g.split('+')
                if len(parts) == 3:
                    self.geometry(f"{d}x{d}+{parts[1]}+{parts[2]}")
                    return
        except Exception:
            pass
        self.geometry(f"{d}x{d}")

    def center_on_screen(self):
        self.update_idletasks()
        w, h = self.winfo_width(), self.winfo_height()
        x = (self.winfo_screenwidth()  // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _start_drag(self, e):
        self._drag_data["x"] = e.x_root - self.winfo_x()
        self._drag_data["y"] = e.y_root - self.winfo_y()

    def _do_drag(self, e):
        self.geometry(f"+{e.x_root-self._drag_data['x']}+{e.y_root-self._drag_data['y']}")

    def _on_mouse_wheel(self, event):
        if event.delta > 0 or event.num == 4:
            ns = min(self.SCALE_MAX, self._scale_factor + self.SCALE_STEP)
        else:
            ns = max(self.SCALE_MIN, self._scale_factor - self.SCALE_STEP)
        if ns != self._scale_factor:
            self._scale_factor = ns
            self._update_window_size()

    def _hsv_to_hex(self, h, s, v):
        i = int(h*6); f = h*6-i; p = v*(1-s); q = v*(1-f*s); t = v*(1-(1-f)*s)
        i %= 6
        r, g, b = [(v,t,p),(q,v,p),(p,v,t),(p,q,v),(t,p,v),(v,p,q)][i]
        return "#%02x%02x%02x" % (int(r*255), int(g*255), int(b*255))

    def _circle_geom(self):
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        cx, cy = cw//2, ch//2
        r = max(1, min(cw, ch)//2 - self.pad)
        return cx, cy, r

    def show(self):
        self.deiconify()
        self.lift()

    def hide(self):
        self.withdraw()

    def destroy(self):
        self._running = False
        try:
            if self._animation_timer is not None:
                self.after_cancel(self._animation_timer)
        except Exception:
            pass
        super().destroy()

    def set_level(self, level: int):
        self.level = max(0, min(self.LEVELS-1, int(level)))

    def redraw(self):
        pass


# ═════════════════════════════════════════════════════════════════════════════
# RINGS
# ═════════════════════════════════════════════════════════════════════════════
class CircleAvatarWindow(BaseAvatarWindow):
    MAX_RINGS = 32

    def __init__(self, master):
        super().__init__(master, "Avatar - Rings")
        self._t0 = time.perf_counter()
        self._tick()

    def _tick(self):
        if not self._running:
            return
        self.redraw()
        self._animation_timer = self.after(50, self._tick)

    def _ring_color(self, k, rings):
        t = (time.perf_counter()-self._t0)*0.05
        return self._hsv_to_hex(((k/max(1,rings-1))+t)%1.0, 0.9, 1.0)

    def redraw(self):
        cx, cy, r = self._circle_geom()
        self.canvas.delete("all")
        self._draw_bg(cx, cy, r)
        rings   = max(1, int((self.level/float(self.LEVELS-1))*self.MAX_RINGS+0.5))
        r_min   = max(1, int(r*0.05))
        r_max   = int(r*0.95)
        r_outer = int(r_min+(r_max-r_min)*(self.level/float(self.LEVELS-1)))
        stroke  = max(2, int(r*0.02))
        if rings == 1:
            col = self._ring_color(0, 1)
            self.canvas.create_oval(cx-r_min,cy-r_min,cx+r_min,cy+r_min,fill=col,outline=col)
            return
        for k in range(rings):
            rk = int(r_outer*(1.0-k/float(rings)))
            if rk <= 1:
                continue
            self.canvas.create_oval(cx-rk,cy-rk,cx+rk,cy+rk,
                                    outline=self._ring_color(k,rings),width=stroke)


# ═════════════════════════════════════════════════════════════════════════════
# RECTANGLES H
# ═════════════════════════════════════════════════════════════════════════════
class RectAvatarWindow(BaseAvatarWindow):
    MAX_PARTICLES    = 450
    SPAWN_AT_MAX_LVL = 60
    RECT_MIN_LEN_F   = 0.03
    RECT_MAX_LEN_F   = 0.22
    RECT_THICK_F     = 0.012
    RECT_LIFETIME    = 0.9
    DRIFT_PIX_F      = 0.01
    LEVEL_DEADZONE   = 2
    SPAWN_GAMMA      = 1.8
    MIN_SPAWN        = 0

    def __init__(self, master):
        super().__init__(master, "Avatar - Rectangles H")
        self._particles = []
        self._last_time = time.perf_counter()
        self._tick()

    def _tick(self):
        if not self._running:
            return
        self.redraw()
        self._animation_timer = self.after(16, self._tick)

    def _spawn_count(self):
        if self.level <= self.LEVEL_DEADZONE:
            return 0
        usable = self.LEVELS-1-self.LEVEL_DEADZONE
        if usable <= 0:
            return 0
        x = max(0.0, min(1.0, (self.level-self.LEVEL_DEADZONE)/float(usable)))
        return int(0.5+self.MIN_SPAWN+(self.SPAWN_AT_MAX_LVL-self.MIN_SPAWN)*(x**self.SPAWN_GAMMA))

    def _uniform_point_in_disc(self, cx, cy, r):
        inner_r = max(2, r*0.85)
        theta   = 2*math.pi*np.random.random()
        rho     = inner_r*math.sqrt(np.random.random())
        return int(cx+rho*math.cos(theta)), int(cy+rho*math.sin(theta))

    def _spawn(self, n):
        cx, cy, r = self._circle_geom()
        if r <= 4:
            return
        d       = 2*r
        min_len = max(6, int(d*self.RECT_MIN_LEN_F))
        max_len = max(min_len+2, int(d*self.RECT_MAX_LEN_F))
        thick   = max(3, int(r*self.RECT_THICK_F))
        drift_p = max(1, int(r*self.DRIFT_PIX_F))
        now     = time.perf_counter()
        for _ in range(n):
            x0, y0 = self._uniform_point_in_disc(cx, cy, r)
            L  = np.random.randint(min_len, max_len)
            dy = abs(y0-cy)
            ch = int(math.sqrt(max(0, r*r-dy*dy))*0.95)
            hL = min(L//2, ch)
            self._particles.append({
                "x1": x0-hL, "y1": y0-thick//2, "x2": x0+hL, "y2": y0+thick//2,
                "vx": np.random.randint(-drift_p, drift_p),
                "vy": np.random.randint(-drift_p, drift_p),
                "birth": now, "life": self.RECT_LIFETIME,
                "color": self._hsv_to_hex(np.random.random(), 0.95, 1.0),
                "vertical": False
            })
        if len(self._particles) > self.MAX_PARTICLES:
            self._particles = self._particles[-self.MAX_PARTICLES:]

    def redraw(self):
        now = time.perf_counter()
        dt  = max(0.0, now-self._last_time)
        self._last_time = now
        cx, cy, r = self._circle_geom()
        self.canvas.delete("all")
        self._draw_bg(cx, cy, r)
        if self.level <= 0:
            self._particles.clear()
            return
        sc = self._spawn_count()
        if sc > 0:
            self._spawn(sc)
        alive = []
        stipples = ("","gray12","gray25","gray50","gray75")
        for p in self._particles:
            age = now-p["birth"]
            if age > p["life"]:
                continue
            p["x1"]+=p["vx"]*dt; p["x2"]+=p["vx"]*dt
            p["y1"]+=p["vy"]*dt; p["y2"]+=p["vy"]*dt
            mx = 0.5*(p["x1"]+p["x2"]); my = 0.5*(p["y1"]+p["y2"])
            dy  = my-cy
            mht = max(0, int(math.sqrt(max(0, r*r-dy*dy))))
            ht  = min(max(1, int((p["y2"]-p["y1"])*0.5)), mht)
            p["y1"],p["y2"] = my-ht, my+ht
            ch  = max(0, int(math.sqrt(max(0, r*r-dy*dy))*0.95))
            hL  = min(int((p["x2"]-p["x1"])*0.5), ch)
            p["x1"],p["x2"] = mx-hL, mx+hL
            t  = age/p["life"]
            st = stipples[min(len(stipples)-1, int(t*len(stipples)))]
            self.canvas.create_rectangle(
                int(p["x1"]),int(p["y1"]),int(p["x2"]),int(p["y2"]),
                fill=p["color"],outline=p["color"],stipple=st if st else None)
            alive.append(p)
        self._particles = alive


# ═════════════════════════════════════════════════════════════════════════════
# RECTANGLES H+V
# ═════════════════════════════════════════════════════════════════════════════
class RectAvatarWindow2(RectAvatarWindow):
    BASE_DIAMETER       = 900
    VERTICAL_PROPORTION = 0.40
    CENTER_PULL         = 0.07
    EDGE_INSET_F        = 1.00

    def __init__(self, master):
        super().__init__(master)
        self.title("Avatar - Rectangles H+V")

    def _spawn(self, n):
        cx, cy, r = self._circle_geom()
        if r <= 4:
            return
        d       = 2*r
        min_len = max(6, int(d*self.RECT_MIN_LEN_F))
        max_len = max(min_len+2, int(d*self.RECT_MAX_LEN_F))
        thick   = max(3, int(r*self.RECT_THICK_F))
        drift_p = max(1, int(r*self.DRIFT_PIX_F))
        now     = time.perf_counter()
        for _ in range(n):
            x0, y0   = self._uniform_point_in_disc(cx, cy, r)
            vertical = np.random.random() < self.VERTICAL_PROPORTION
            if vertical:
                L  = np.random.randint(min_len, max_len)
                dx = abs(x0-cx)
                ch = int(math.sqrt(max(0, r*r-dx*dx))*self.EDGE_INSET_F)
                hL = min(L//2, ch)
                x1,x2 = x0-thick//2, x0+thick//2
                y1,y2 = y0-hL, y0+hL
            else:
                L  = np.random.randint(min_len, max_len)
                dy = abs(y0-cy)
                ch = int(math.sqrt(max(0, r*r-dy*dy))*self.EDGE_INSET_F)
                hL = min(L//2, ch)
                x1,x2 = x0-hL, x0+hL
                y1,y2 = y0-thick//2, y0+thick//2
            self._particles.append({
                "x1":x1,"y1":y1,"x2":x2,"y2":y2,
                "vx":np.random.randint(-drift_p,drift_p),
                "vy":np.random.randint(-drift_p,drift_p),
                "birth":now,"life":self.RECT_LIFETIME,
                "color":self._hsv_to_hex(np.random.random(),0.95,1.0),
                "vertical":bool(vertical)
            })
        if len(self._particles) > self.MAX_PARTICLES:
            self._particles = self._particles[-self.MAX_PARTICLES:]

    def redraw(self):
        now = time.perf_counter()
        dt  = max(0.0, now-self._last_time)
        self._last_time = now
        cx, cy, r = self._circle_geom()
        self.canvas.delete("all")
        self._draw_bg(cx, cy, r)
        if self.level <= 0:
            self._particles.clear()
            return
        sc = self._spawn_count()
        if sc > 0:
            self._spawn(sc)
        alive = []
        stipples = ("","gray12","gray25","gray50","gray75")
        for p in self._particles:
            age = now-p["birth"]
            if age > p["life"]:
                continue
            p["x1"]+=p["vx"]*dt; p["x2"]+=p["vx"]*dt
            p["y1"]+=p["vy"]*dt; p["y2"]+=p["vy"]*dt
            if self.CENTER_PULL > 0:
                mx = 0.5*(p["x1"]+p["x2"]); my = 0.5*(p["y1"]+p["y2"])
                pull = self.CENTER_PULL*dt
                dx=(cx-mx)*pull; dy=(cy-my)*pull
                p["x1"]+=dx;p["x2"]+=dx;p["y1"]+=dy;p["y2"]+=dy
            mx = 0.5*(p["x1"]+p["x2"]); my = 0.5*(p["y1"]+p["y2"])
            if p.get("vertical",False):
                ddx = mx-cx
                mht = max(0,int(math.sqrt(max(0,r*r-ddx*ddx))))
                ht  = min(max(1,int((p["x2"]-p["x1"])*0.5)),mht)
                p["x1"],p["x2"] = mx-ht,mx+ht
                ch  = max(0,int(math.sqrt(max(0,r*r-ddx*ddx))*self.EDGE_INSET_F))
                hL  = min(int((p["y2"]-p["y1"])*0.5),ch)
                p["y1"],p["y2"] = my-hL,my+hL
            else:
                ddy = my-cy
                mht = max(0,int(math.sqrt(max(0,r*r-ddy*ddy))))
                ht  = min(max(1,int((p["y2"]-p["y1"])*0.5)),mht)
                p["y1"],p["y2"] = my-ht,my+ht
                ch  = max(0,int(math.sqrt(max(0,r*r-ddy*ddy))*self.EDGE_INSET_F))
                hL  = min(int((p["x2"]-p["x1"])*0.5),ch)
                p["x1"],p["x2"] = mx-hL,mx+hL
            t  = age/p["life"]
            st = stipples[min(len(stipples)-1, int(t*len(stipples)))]
            self.canvas.create_rectangle(
                int(p["x1"]),int(p["y1"]),int(p["x2"]),int(p["y2"]),
                fill=p["color"],outline=p["color"],stipple=st if st else None)
            alive.append(p)
        self._particles = alive


# ═════════════════════════════════════════════════════════════════════════════
# RADIAL PULSE
# ═════════════════════════════════════════════════════════════════════════════
class RadialPulseAvatar(BaseAvatarWindow):
    DOT_COLOR       = "#FF0000"
    LINE_COLOR      = "#FF3333"
    MAX_LINES       = 24
    MAX_LINE_LENGTH = 0.8
    PULSE_SMOOTHING = 0.3

    def __init__(self, master):
        super().__init__(master, "Avatar - Radial Pulse")
        self._smoothed = 0.0
        self._tick()

    def _tick(self):
        if not self._running:
            return
        self.redraw()
        self._animation_timer = self.after(16, self._tick)

    def redraw(self):
        target = self.level/float(self.LEVELS-1)
        self._smoothed += (target-self._smoothed)*self.PULSE_SMOOTHING
        self.canvas.delete("all")
        cx, cy, r = self._circle_geom()
        self._draw_bg(cx, cy, r)
        pulse = self._smoothed*(0.8+0.4*math.sin(time.perf_counter()*8))
        dr = max(2, int(4+pulse*6))
        self.canvas.create_oval(cx-dr,cy-dr,cx+dr,cy+dr,
                                fill=self.DOT_COLOR,outline=self.DOT_COLOR)
        if pulse > 0.05:
            mll = min(self.canvas.winfo_width(),
                      self.canvas.winfo_height())*self.MAX_LINE_LENGTH*pulse
            for i in range(self.MAX_LINES):
                angle = (2*math.pi*i)/self.MAX_LINES
                ll    = mll*(0.7+0.6*math.sin(angle*3+time.perf_counter()*6))
                ex    = cx+ll*math.cos(angle)
                ey    = cy+ll*math.sin(angle)
                lw    = max(1, int(1+pulse*3))
                self.canvas.create_line(cx,cy,ex,ey,
                                        fill=self.LINE_COLOR,width=lw,capstyle=tk.ROUND)


# ═════════════════════════════════════════════════════════════════════════════
# STRING GRID
# ═════════════════════════════════════════════════════════════════════════════
class StringGridAvatar(BaseAvatarWindow):
    BASE_DIAMETER  = 900

    def __init__(self, master):
        super().__init__(master, "Avatar - String Grid")
        self.visual_intensity = 0.5
        self.grid_size        = 50
        self.total_points     = self.grid_size*self.grid_size
        self.grid_center      = self.grid_size//2
        self.speech_amplitude = 0
        self.draw_threshold   = 0.05
        self.grid_positions   = []
        self.grid_colors      = []
        self.grid_frequencies = []
        self.grid_phases      = []
        np.random.seed(42)
        for y in range(self.grid_size):
            for x in range(self.grid_size):
                dx   = (x-self.grid_center)/self.grid_center
                dy   = (y-self.grid_center)/self.grid_center
                dist = math.sqrt(dx*dx+dy*dy)
                self.grid_positions.append((x, y, dist))
                hue  = y/self.grid_size
                sat  = 0.7+0.3*(1.0-dist)
                val  = 0.5+0.5*(1.0-dist)
                rv,gv,bv = colorsys.hsv_to_rgb(hue, sat, val)
                self.grid_colors.append(f"#{int(rv*255):02x}{int(gv*255):02x}{int(bv*255):02x}")
                self.grid_frequencies.append(1.0+(1.0-dist)*2.0+np.random.random()*0.5)
                self.grid_phases.append(np.random.random()*2*math.pi)
        self._tick()

    def set_level(self, level: int):
        super().set_level(level)
        if level >= 2:
            n = level/float(self.LEVELS-1)
            self.speech_amplitude = min(1.0, n*self.visual_intensity*2.0)
        else:
            self.speech_amplitude = 0

    def _tick(self):
        if not self._running:
            return
        self.redraw()
        self._animation_timer = self.after(33, self._tick)

    def _point_height(self, x, y, dist, idx):
        if self.speech_amplitude <= 0.001:
            return 0.0
        if self.speech_amplitude < dist*0.8:
            return 0.0
        base = self.speech_amplitude*(1.0-dist*0.7)
        tf   = time.time()*2.0
        w    = (math.sin(x*0.3+tf*self.grid_frequencies[idx]+self.grid_phases[idx])*0.2 +
                math.cos(y*0.3+tf*self.grid_frequencies[idx]*1.3)*0.15)
        return max(0.0, min(1.0, base+w+np.random.normal(0, 0.03)*(1.0-dist)))

    def redraw(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 100 or h < 100:
            return
        cx, cy, r = self._circle_geom()
        self._draw_bg(cx, cy, r)
        if self.speech_amplitude < self.draw_threshold:
            return
        cw      = w/self.grid_size
        ch_cell = h/self.grid_size
        ratio   = ((self.speech_amplitude-self.draw_threshold)/(1.0-self.draw_threshold))**0.7
        n_pts   = int(self.total_points*ratio)
        if n_pts == 0:
            return
        sorted_idx = np.argsort([d for _,_,d in self.grid_positions])
        for idx in sorted_idx[:n_pts]:
            gx, gy, dist = self.grid_positions[idx]
            sx = gx*cw+cw/2
            sy = gy*ch_cell+ch_cell/2
            hv = self._point_height(gx, gy, dist, idx)
            if hv > 0:
                sz = max(1, int(2.0+(hv*4)+((1.0-dist)*3)))
                vy = sy-hv*ch_cell*3
                self.canvas.create_oval(sx-sz,vy-sz,sx+sz,vy+sz,
                    fill=self.grid_colors[idx],outline=self.grid_colors[idx],width=0)


# ═════════════════════════════════════════════════════════════════════════════
# HAL 9000
# ═════════════════════════════════════════════════════════════════════════════
class Hal9000Avatar(BaseAvatarWindow):
    SILVER          = "#C0C0C0"
    SPIKE_COLOR     = "#FF3333"
    SPIKE_HIGHLIGHT = "#FF6666"

    def __init__(self, master):
        super().__init__(master, "Avatar - HAL 9000")
        self._smoothed = 0.0
        self._phase    = 0.0
        self._tick()

    def _tick(self):
        if not self._running:
            return
        self.redraw()
        self._animation_timer = self.after(16, self._tick)

    def set_level(self, level: int):
        super().set_level(level)
        target = min(1.0, (level/float(self.LEVELS-1))*1.5)
        self._smoothed += (target-self._smoothed)*0.3
        self._phase = (self._phase+0.1)%(math.pi*2)

    def redraw(self):
        self.canvas.delete("all")
        cx, cy, r = self._circle_geom()
        self._draw_bg(cx, cy, r)
        sr = int(r*0.95); sw = max(3, int(r*0.07))
        self.canvas.create_oval(cx-sr,cy-sr,cx+sr,cy+sr,outline=self.SILVER,width=sw)
        if self._smoothed > 0.05:
            n  = max(3, int(24*self._smoothed))
            ml = r*0.8*self._smoothed
            for i in range(n):
                angle = (2*math.pi*i)/n
                var   = 0.7+0.6*math.sin(angle*3+self._phase*2)
                ll    = ml*var
                ex    = cx+ll*math.cos(angle); ey = cy+ll*math.sin(angle)
                lw    = max(1, int((1+self._smoothed*3)*(0.8+0.4*math.sin(angle*2+self._phase))))
                col   = self.SPIKE_HIGHLIGHT if var>0.9 else self.SPIKE_COLOR
                self.canvas.create_line(cx,cy,ex,ey,fill=col,width=lw,capstyle=tk.ROUND)
        cb  = max(3, int(r*0.1))
        pls = 1.0+0.3*math.sin(self._phase*2) if self._smoothed>0.1 else 0.8+0.2*math.sin(self._phase*0.5)
        cr2 = int(cb*pls); gr = int(cr2*1.5)
        gi  = int(100+155*self._smoothed)
        self.canvas.create_oval(cx-gr,cy-gr,cx+gr,cy+gr,fill=f"#{gi:02x}0000",outline=f"#{gi:02x}0000")
        ri  = min(255, int(200+55*self._smoothed))
        self.canvas.create_oval(cx-cr2,cy-cr2,cx+cr2,cy+cr2,fill=f"#{ri:02x}0000",outline=f"#{ri:02x}0000")
        hs  = max(1, int(cr2*0.3)); hx = int(-cr2*0.2); hy = int(-cr2*0.2)
        self.canvas.create_oval(cx+hx-hs,cy+hy-hs,cx+hx+hs,cy+hy+hs,fill="#FFFFFF",outline="#FFFFFF")


# ═════════════════════════════════════════════════════════════════════════════
# ORBS
# ═════════════════════════════════════════════════════════════════════════════
class OrbAvatarWindow(BaseAvatarWindow):
    MAX_PARTICLES    = 600
    SPAWN_AT_MAX_LVL = 80
    ORB_MIN_R_F      = 0.004
    ORB_MAX_R_F      = 0.014
    ORB_LIFETIME     = 1.2
    DRIFT_PIX_F      = 0.015
    LEVEL_DEADZONE   = 2
    SPAWN_GAMMA      = 1.7
    MIN_SPAWN        = 0

    def __init__(self, master):
        super().__init__(master, "Avatar - Orbs")
        self._particles = []
        self._last_time = time.perf_counter()
        self._tick()

    def _tick(self):
        if not self._running:
            return
        self.redraw()
        self._animation_timer = self.after(16, self._tick)

    def _spawn_count(self):
        if self.level <= self.LEVEL_DEADZONE:
            return 0
        usable = self.LEVELS-1-self.LEVEL_DEADZONE
        x = (self.level-self.LEVEL_DEADZONE)/float(usable)
        return int(0.5+self.MIN_SPAWN+(self.SPAWN_AT_MAX_LVL-self.MIN_SPAWN)*(x**self.SPAWN_GAMMA))

    def _spawn(self, n):
        cx, cy, max_r = self._circle_geom()
        cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
        rmin  = max(2, int(min(cw,ch)*self.ORB_MIN_R_F))
        rmax  = max(rmin+1, int(min(cw,ch)*self.ORB_MAX_R_F))
        drift = max(1, int(min(cw,ch)*self.DRIFT_PIX_F))
        now   = time.perf_counter()
        for _ in range(n):
            rv   = np.random.randint(rmin, rmax)
            ang  = np.random.random()*2*math.pi
            dist = np.random.random()*(max_r-rv)
            self._particles.append({
                "cx": cx+dist*math.cos(ang), "cy": cy+dist*math.sin(ang), "r": rv,
                "vx": np.random.uniform(-drift,drift), "vy": np.random.uniform(-drift,drift),
                "birth": now, "life": self.ORB_LIFETIME
            })
        if len(self._particles) > self.MAX_PARTICLES:
            self._particles = self._particles[-self.MAX_PARTICLES:]

    def redraw(self):
        now = time.perf_counter(); dt = max(0.0,now-self._last_time); self._last_time = now
        cx, cy, max_r = self._circle_geom()
        self.canvas.delete("all")
        self._draw_bg(cx, cy, max_r)
        if self.level <= 0:
            self._particles.clear()
            return
        sc = self._spawn_count()
        if sc > 0:
            self._spawn(sc)
        boost = 1.0+(self.level/31.0)*0.5; alive = []
        for p in self._particles:
            age = now-p["birth"]
            if age > p["life"]:
                continue
            p["cx"]+=p["vx"]*dt; p["cy"]+=p["vy"]*dt
            dx = p["cx"]-cx; dy = p["cy"]-cy; d = math.sqrt(dx*dx+dy*dy)
            if d+p["r"] > max_r:
                nx,ny = dx/max(d,1), dy/max(d,1)
                dot   = p["vx"]*nx+p["vy"]*ny
                p["vx"]-=1.5*dot*nx; p["vy"]-=1.5*dot*ny
                ov     = (d+p["r"])-max_r
                p["cx"]-=ov*nx; p["cy"]-=ov*ny
            t  = 1.0-(age/p["life"]); br = max(0.3,min(1.0,0.4+0.6*t))
            br2,bg2,bb2 = (255,200,0) if self.level>15 else (255,215,0)
            col = f"#{min(255,int(br2*br*boost)):02x}{min(255,int(bg2*br)):02x}{min(255,int(bb2*br*0.8)):02x}"
            rv  = p["r"]
            self.canvas.create_oval(int(p["cx"]-rv),int(p["cy"]-rv),
                                    int(p["cx"]+rv),int(p["cy"]+rv),fill=col,outline=col)
            alive.append(p)
        self._particles = alive


# ═════════════════════════════════════════════════════════════════════════════
# NEURAL NET
# ═════════════════════════════════════════════════════════════════════════════
class NeuralNetAvatarWindow(BaseAvatarWindow):
    BASE_DIAMETER = 440
    MAX_LAYERS    = 8
    LAYER_COLORS  = ["#FFFFFF","#C0C0C0","#00C8FF","#7A5CFF",
                     "#00FF9C","#FFD700","#FF6A00","#FF004C"]

    def __init__(self, master):
        super().__init__(master, "Avatar - Neural Net")
        self._tick()

    def _tick(self):
        if not self._running:
            return
        self.redraw()
        self._animation_timer = self.after(50, self._tick)

    def redraw(self):
        self.canvas.delete("all")
        cx, cy, r = self._circle_geom()
        self._draw_bg(cx, cy, r)
        layers  = max(1, int((self.level/(self.LEVELS-1))*self.MAX_LAYERS+0.5))
        spacing = r/(layers+1)
        for i in range(layers):
            radius = spacing*(i+1)
            color  = self.LAYER_COLORS[i%len(self.LAYER_COLORS)]
            nodes  = int(6+radius*0.12)
            node_r = max(2, int(radius*0.04))
            for n in range(nodes):
                ang = (2*math.pi/nodes)*n+random.uniform(-0.08,0.08)
                x   = cx+math.cos(ang)*radius
                y   = cy+math.sin(ang)*radius
                self.canvas.create_oval(x-node_r,y-node_r,x+node_r,y+node_r,fill=color,outline="")


# ═════════════════════════════════════════════════════════════════════════════
# DNA HELIX
# ═════════════════════════════════════════════════════════════════════════════
class DNAHelixAvatar(BaseAvatarWindow):
    def __init__(self, master):
        super().__init__(master, "Avatar - DNA Helix")
        self._t           = 0.0
        self._last        = time.perf_counter()
        self._rot_speed   = 0.5
        self._rung_bright = [0.0] * 20
        self._tick()

    def _tick(self):
        if not self._running:
            return
        now = time.perf_counter()
        dt  = min(now - self._last, 0.05)
        self._last = now
        self._t   += dt
        amp = self.level / float(self.LEVELS - 1)
        self._rot_speed += (0.5 + amp * 1.5 - self._rot_speed) * dt * 3
        for i in range(20):
            if math.sin(self._t * 3 + i * 0.3) > 0.7 and amp > 0.2:
                self._rung_bright[i] = min(1.0, self._rung_bright[i] + amp * 0.5)
            else:
                self._rung_bright[i] *= 0.93
        self.redraw()
        self._animation_timer = self.after(33, self._tick)

    def redraw(self):
        self.canvas.delete("all")
        cx, cy, r = self._circle_geom()
        amp = self.level / float(self.LEVELS - 1)
        self._draw_bg(cx, cy, r)
        num_rungs = 20
        helix_h   = r * 1.8
        sw        = max(2, int(4 + amp * 3))
        angle_off = self._t * self._rot_speed
        x1p = x2p = yp = None
        for i in range(num_rungs):
            frac  = i / (num_rungs - 1)
            y     = cy - r * 0.9 + frac * helix_h
            angle = frac * math.pi * 4 + angle_off
            x1    = cx + math.cos(angle)           * r * 0.55
            x2    = cx + math.cos(angle + math.pi) * r * 0.55
            d1    = (math.sin(angle)           + 1) / 2
            d2    = (math.sin(angle + math.pi) + 1) / 2
            c1 = "#%02x%02x%02x" % (0, int(d1*255 + (1-d1)*50), int(d1*255 + (1-d1)*255))
            c2 = "#%02x%02x%02x" % (int(d2*255 + (1-d2)*100), 0, int(d2*204 + (1-d2)*255))
            if x1p is not None:
                self.canvas.create_line(int(x1p), int(yp), int(x1), int(y),
                                        fill=c1, width=max(1, sw - 1))
                self.canvas.create_line(int(x2p), int(yp), int(x2), int(y),
                                        fill=c2, width=max(1, sw - 1))
            rb   = self._rung_bright[i]
            rw   = max(1, int(2 + rb * 6))
            rv   = int(60 + rb * 195)
            rcol = "#%02x%02x%02x" % (rv, rv, min(255, rv + 30))
            self.canvas.create_line(int(x1), int(y), int(x2), int(y), fill=rcol, width=rw)
            self.canvas.create_oval(int(x1)-sw, int(y)-sw, int(x1)+sw, int(y)+sw,
                                    fill=c1, outline="")
            self.canvas.create_oval(int(x2)-sw, int(y)-sw, int(x2)+sw, int(y)+sw,
                                    fill=c2, outline="")
            x1p, x2p, yp = x1, x2, y


# ═════════════════════════════════════════════════════════════════════════════
# TESLA COIL
# ═════════════════════════════════════════════════════════════════════════════
class TeslaCoilAvatar(BaseAvatarWindow):
    def __init__(self, master):
        super().__init__(master, "Avatar - Tesla Coil")
        self._t            = 0.0
        self._last         = time.perf_counter()
        self._bolts        = []
        self._bolt_timer   = 0.0
        self._glow_phase   = 0.0
        self._corona       = [{'angle': random.uniform(0, math.pi * 2),
                               'speed': random.uniform(0.3, 1.0)} for _ in range(12)]
        self._tick()

    def _midpoint(self, x1, y1, x2, y2, roughness, depth):
        if depth == 0:
            return [(x1, y1), (x2, y2)]
        mx = (x1 + x2) / 2 + random.uniform(-roughness, roughness)
        my = (y1 + y2) / 2 + random.uniform(-roughness, roughness)
        L  = self._midpoint(x1, y1, mx, my, roughness * 0.6, depth - 1)
        R  = self._midpoint(mx, my, x2, y2, roughness * 0.6, depth - 1)
        return L[:-1] + R

    def _tick(self):
        if not self._running:
            return
        now = time.perf_counter()
        dt  = min(now - self._last, 0.05)
        self._last   = now
        self._t     += dt
        self._glow_phase = (self._glow_phase + dt * 0.8) % (math.pi * 2)
        amp = self.level / float(self.LEVELS - 1)
        for sp in self._corona:
            sp['angle'] = (sp['angle'] + sp['speed'] * dt) % (math.pi * 2)
        self._bolt_timer += dt
        if amp > 0.15 and self._bolt_timer > 0.033:
            self._bolt_timer = 0.0
            cx, cy, r = self._circle_geom()
            sph_r     = r * 0.28
            sph_cy    = cy - r * 0.15
            self._bolts = []
            for _ in range(max(1, int(1 + amp * 4))):
                sa = random.uniform(0, math.pi * 2)
                sx = cx + math.cos(sa) * sph_r
                sy = sph_cy + math.sin(sa) * sph_r
                ea = random.uniform(-math.pi * 0.7, math.pi * 0.7)
                er = r * random.uniform(0.6, 0.95)
                ex = cx + math.cos(ea) * er
                ey = sph_cy + math.sin(ea) * er * 0.8
                pts  = self._midpoint(sx, sy, ex, ey, 20 + amp * 30, 5)
                branches = []
                for bi in range(0, len(pts) - 2, 3):
                    if random.random() < 0.4:
                        bx   = pts[bi][0] + random.uniform(-30, 30)
                        by   = pts[bi][1] + random.uniform(-40, 10)
                        branches.append(
                            self._midpoint(pts[bi][0], pts[bi][1], bx, by, 10, 3))
                self._bolts.append({'pts': pts, 'branches': branches})
        self.redraw()
        self._animation_timer = self.after(33, self._tick)

    def redraw(self):
        self.canvas.delete("all")
        cx, cy, r = self._circle_geom()
        amp = self.level / float(self.LEVELS - 1)
        self._draw_bg(cx, cy, r)
        sph_r  = int(r * 0.28)
        sph_cy = cy + int(r * 0.15)
        gv = (math.sin(self._glow_phase) + 1) / 2
        for gr in range(sph_r + 20, sph_r, -4):
            frac = 1 - (gr - sph_r) / 20.0
            bri  = int(35 * frac * (0.3 + gv * 0.7))
            gcol = "#%02x%02x%02x" % (bri, bri, min(255, bri * 4))
            self.canvas.create_oval(cx - gr, sph_cy - gr, cx + gr, sph_cy + gr,
                                    fill=gcol, outline="")
        off = int(sph_r * 0.2)
        for ri in range(sph_r, 0, -2):
            frac   = ri / sph_r
            bright = int(255 * (1 - frac * 0.8))
            col    = "#%02x%02x%02x" % (bright, bright, min(255, bright + 15))
            self.canvas.create_oval(cx - off - ri, sph_cy - off - ri,
                                    cx - off + ri, sph_cy - off + ri,
                                    fill=col, outline="")
        for sp in self._corona:
            sx = cx  + math.cos(sp['angle']) * (sph_r + 8)
            sy = sph_cy + math.sin(sp['angle']) * (sph_r + 8)
            self.canvas.create_oval(int(sx) - 2, int(sy) - 2,
                                    int(sx) + 2, int(sy) + 2, fill="#c8c8ff", outline="")
        for bolt in self._bolts:
            flat = [c for p in bolt['pts'] for c in p]
            if len(flat) >= 4:
                self.canvas.create_line(*flat, fill="#ffffff", width=2)
            for bpts in bolt['branches']:
                bf = [c for p in bpts for c in p]
                if len(bf) >= 4:
                    self.canvas.create_line(*bf, fill="#00ffff", width=1)


# ═════════════════════════════════════════════════════════════════════════════
# TEXTURE SPHERE  (PIL only)
# ═════════════════════════════════════════════════════════════════════════════
if PIL_OK:
    class TextureMappedSphere(BaseAvatarWindow):
        BASE_DIAMETER = 600

        def __init__(self, master):
            super().__init__(master, "Texture Sphere")
            self.tw = 256; self.th = 256
            self.max_points  = 800; self.base_points = 300
            self.redraw_interval = 0.05
            self.rotation_x = 0; self.rotation_y = 0
            self.base_rot   = 0.015; self.cur_rot = 0.0
            self.rot_dx = 1; self.rot_dy = 1
            self.last_redraw = 0
            self.sphere_radius = 0.8
            self.light_pos = (2,2,3); self.ambient = 0.4; self.diffuse = 0.6
            self.sphere_points = []; self._lf = []
            self._create_default_texture()
            self._create_sphere_tex()
            self._gen_points(800)
            self._tick()

        def _create_default_texture(self):
            img = Image.new('RGB',(self.tw,self.th))
            draw = ImageDraw.Draw(img)
            cx,cy = self.tw//2, self.th//2
            md = math.sqrt(cx*cx+cy*cy)
            for x in range(0,self.tw,4):
                for y in range(0,self.th,4):
                    angle = math.atan2(y-cy,x-cx)
                    dist  = math.sqrt((x-cx)**2+(y-cy)**2)/md
                    rv,gv,bv = colorsys.hsv_to_rgb((angle/(2*math.pi))%1.0, 0.8, 0.9-dist*0.3)
                    color = (int(rv*255),int(gv*255),int(bv*255))
                    for bx in range(x,min(x+4,self.tw)):
                        for by in range(y,min(y+4,self.th)):
                            draw.point((bx,by),fill=color)
            self.tex_img = img; self.tex_px = img.load()

        def _create_sphere_tex(self):
            si = Image.new('RGB',(self.tw,self.th)); sp = si.load()
            cx,cy = self.tw//2,self.th//2; rad = min(cx,cy)*0.9
            for x in range(self.tw):
                for y in range(self.th):
                    nx=(x-cx)/rad; ny=(y-cy)/rad
                    if math.sqrt(nx*nx+ny*ny)<=1.0:
                        theta=math.asin(math.sqrt(nx*nx+ny*ny)); phi=math.atan2(ny,nx)
                        u=(phi+math.pi)/(2*math.pi); v=(theta+math.pi/2)/math.pi
                        tx=max(0,min(self.tw-1,int(u*(self.tw-1))))
                        ty=max(0,min(self.th-1,int(v*(self.th-1))))
                        sp[x,y]=self.tex_px[tx,ty]
                    else:
                        sp[x,y]=(0,0,0)
            self.sph_tex=si; self.sph_px=sp

        def _gen_points(self, density=800):
            self.sphere_points=[]
            nl=int(math.sqrt(density)*0.8); nm=int(math.sqrt(density)*1.2)
            for i in range(nl):
                theta=(i/max(1,nl-1)-0.5)*math.pi; ct=math.cos(theta); st=math.sin(theta)
                for j in range(nm):
                    phi=(j/max(1,nm-1))*2*math.pi
                    x=math.cos(phi)*ct; y=st; z=math.sin(phi)*ct
                    u=(phi+math.pi)/(2*math.pi); v=(theta+math.pi/2)/math.pi
                    tx=max(0,min(self.tw-1,int(u*(self.tw-1))))
                    ty=max(0,min(self.th-1,int(v*(self.th-1))))
                    self.sphere_points.append((x,y,z,self.tex_px[tx,ty]))
            ll=math.sqrt(sum(v*v for v in self.light_pos))
            lx,ly,lz=[v/ll for v in self.light_pos]
            self._lf=[]
            for x,y,z,_ in self.sphere_points:
                nm2=math.sqrt(x*x+y*y+z*z)
                if nm2>0:
                    d=max(0,x/nm2*lx+y/nm2*ly+z/nm2*lz)
                    self._lf.append(self.ambient+d*self.diffuse)
                else:
                    self._lf.append(self.ambient)

        def set_level(self, level: int):
            super().set_level(level)
            if level > 2:
                self.cur_rot = self.base_rot*(level/31.0)*1.5
                if not hasattr(self,'_rot_init'):
                    self._rot_init=True
                    self.rot_dx=random.choice([-1,1]); self.rot_dy=random.choice([-1,1])
            else:
                self.cur_rot = max(0, self.cur_rot-0.0005)

        def _rotate(self,x,y,z):
            cx=math.cos(self.rotation_x); sx=math.sin(self.rotation_x)
            cy=math.cos(self.rotation_y); sy=math.sin(self.rotation_y)
            y1=y*cx-z*sx; z1=y*sx+z*cx
            x1=x*cy+z1*sy; z2=-x*sy+z1*cy
            return x1,y1,z2

        def _tick(self):
            if not self._running: return
            if self.cur_rot > 0:
                self.rotation_x+=self.cur_rot*self.rot_dx*0.6
                self.rotation_y+=self.cur_rot*self.rot_dy*0.9
            else:
                self.rotation_x+=0.0005; self.rotation_y+=0.0007
            now=time.perf_counter()
            if now-self.last_redraw>=self.redraw_interval:
                self.redraw(); self.last_redraw=now
            self._animation_timer=self.after(40,self._tick)

        def show(self):
            super().show()
            self.after(300, self._open_controls)

        def _open_controls(self):
            if hasattr(self,'_ctrl') and self._ctrl and self._ctrl.winfo_exists():
                return
            self._ctrl = tk.Toplevel(self)
            self._ctrl.title("Sphere Texture")
            self._ctrl.configure(bg="#0a0a0a")
            self._ctrl.resizable(False,False)
            self.update_idletasks()
            self._ctrl.geometry(f"+{self.winfo_x()+self.winfo_width()+8}+{self.winfo_y()}")
            tk.Label(self._ctrl,text="TEXTURE CONTROLS",font=("Courier New",10,"bold"),
                     fg="#ff3c3c",bg="#0a0a0a").pack(pady=(10,6))
            tk.Button(self._ctrl,text="Random Texture",font=("Courier New",10),
                      fg="white",bg="#1a0000",activebackground="#ff3c3c",
                      relief="flat",padx=8,pady=4,
                      command=self._random_texture).pack(fill="x",padx=14,pady=3)
            tk.Button(self._ctrl,text="Default Texture",font=("Courier New",10),
                      fg="white",bg="#1a0000",activebackground="#ff3c3c",
                      relief="flat",padx=8,pady=4,
                      command=self._reset_texture).pack(fill="x",padx=14,pady=3)
            tk.Button(self._ctrl,text="Close",font=("Courier New",9),
                      fg="#ff3c3c",bg="#0a0a0a",relief="flat",
                      command=self._ctrl.destroy).pack(pady=(6,10))

        def _random_texture(self):
            img  = Image.new('RGB',(self.tw,self.th))
            draw = ImageDraw.Draw(img)
            pattern = random.choice(['gradient','stripes','dots','circular','checker'])
            cx,cy = self.tw//2,self.th//2
            md    = math.sqrt(cx*cx+cy*cy)
            if pattern == 'circular':
                hs = random.random()
                for x in range(self.tw):
                    for y in range(self.th):
                        d = math.sqrt((x-cx)**2+(y-cy)**2)/md
                        rv,gv,bv = colorsys.hsv_to_rgb((hs+d*0.5)%1.0,0.8,0.9-d*0.3)
                        draw.point((x,y),fill=(int(rv*255),int(gv*255),int(bv*255)))
            elif pattern == 'gradient':
                c1=(random.randint(0,255),random.randint(0,255),random.randint(0,255))
                c2=(random.randint(0,255),random.randint(0,255),random.randint(0,255))
                for x in range(self.tw):
                    for y in range(self.th):
                        t2=(x+y)/(self.tw+self.th)
                        draw.point((x,y),fill=(int(c1[0]*(1-t2)+c2[0]*t2),
                                               int(c1[1]*(1-t2)+c2[1]*t2),
                                               int(c1[2]*(1-t2)+c2[2]*t2)))
            elif pattern == 'stripes':
                sw = random.randint(10,40)
                for x in range(self.tw):
                    c = self._hsv_to_hex(random.random(),0.9,1.0) if (x//sw)%2==0 else "#000000"
                    r2,g2,b2 = int(c[1:3],16),int(c[3:5],16),int(c[5:7],16)
                    for y in range(self.th):
                        draw.point((x,y),fill=(r2,g2,b2))
            elif pattern == 'dots':
                ds = random.randint(6,20); sp2 = ds*3
                bc = (random.randint(30,180),random.randint(30,180),random.randint(30,180))
                dc = (random.randint(0,255),random.randint(0,255),random.randint(0,255))
                draw.rectangle([0,0,self.tw,self.th],fill=bc)
                for x in range(0,self.tw,sp2):
                    for y in range(0,self.th,sp2):
                        draw.ellipse([x,y,x+ds,y+ds],fill=dc)
            else:  # checker
                ts = random.randint(20,40)
                c1=(random.randint(0,255),random.randint(0,255),random.randint(0,255))
                c2=(random.randint(0,255),random.randint(0,255),random.randint(0,255))
                for x in range(0,self.tw,ts):
                    for y in range(0,self.th,ts):
                        draw.rectangle([x,y,x+ts,y+ts],fill=c1 if (x//ts+y//ts)%2==0 else c2)
            self.tex_img=img; self.tex_px=img.load()
            self._create_sphere_tex(); self._gen_points(800)

        def _reset_texture(self):
            self._create_default_texture()
            self._create_sphere_tex(); self._gen_points(800)

        def destroy(self):
            if hasattr(self,'_ctrl') and self._ctrl:
                try: self._ctrl.destroy()
                except Exception: pass
            super().destroy()

        def redraw(self):
            self.canvas.delete("all")
            w=self.canvas.winfo_width(); h=self.canvas.winfo_height()
            if w<100 or h<100: return
            cx,cy,r=self._circle_geom()
            self._draw_bg(cx, cy, r)
            sf   = min(w,h)*0.45
            n_pts= min(len(self.sphere_points),
                       self.base_points+int((self.level/31.0)*(self.max_points-self.base_points)))
            step = max(1,len(self.sphere_points)//max(1,n_pts))
            for i in range(0,len(self.sphere_points),step):
                x,y,z,color=self.sphere_points[i]
                rx,ry,rz=self._rotate(x*self.sphere_radius,y*self.sphere_radius,z*self.sphere_radius)
                if rz+5>0:
                    f=4.0/(rz+5.0)
                    if f>0.3:
                        sx2=cx+rx*f*sf; sy2=cy+ry*f*sf
                        br=self._lf[i] if i<len(self._lf) else 0.7
                        br=min(1.5,br*(1.0+self.level/124.0))
                        lit=(min(255,int(color[0]*br)),min(255,int(color[1]*br)),min(255,int(color[2]*br)))
                        ps=max(1,int(2.0*f*(1+self.level/155.0)))
                        ch=f"#{lit[0]:02x}{lit[1]:02x}{lit[2]:02x}"
                        self.canvas.create_oval(sx2-ps,sy2-ps,sx2+ps,sy2+ps,fill=ch,outline=ch)


# ═════════════════════════════════════════════════════════════════════════════
# FACE RADIAL AVATAR  (PIL only — needs face.png next to script)
# ═════════════════════════════════════════════════════════════════════════════
if PIL_OK:
    class FaceRadialAvatar(tk.Toplevel):
        LEVELS          = LEVELS
        MASK_COLOR      = "#00FF00"
        BG              = "#000000"
        SCALE_MIN       = 0.3
        SCALE_MAX       = 2.0
        SCALE_STEP      = 0.1
        BASE_HEIGHT     = 600
        BASE_WIDTH      = 480
        DOT_COLOR       = "#FF0000"
        LINE_COLOR      = "#FF3333"
        MAX_LINES       = 24
        MAX_LINE_LENGTH = 0.95
        PULSE_SMOOTHING = 0.3

        def __init__(self, master):
            super().__init__(master)
            self.title("Avatar - Face")
            self._scale_factor    = 1.0
            self.level            = 0
            self._running         = True
            self.pad              = 8
            self._smoothed        = 0.0
            self._rect_mode       = False
            self._animation_timer = None
            self._drag_data       = {"x": 0, "y": 0}
            try:
                self.overrideredirect(True)
                self.wm_attributes("-transparentcolor", self.MASK_COLOR)
                self.configure(bg=self.MASK_COLOR)
            except Exception:
                pass
            self.wm_attributes("-topmost", True)
            self._update_size()
            self._center()
            self.bind("<Button-1>",   self._start_drag)
            self.bind("<B1-Motion>",  self._do_drag)
            self.bind("<MouseWheel>", self._on_wheel)
            self.bind("<Button-4>",   self._on_wheel)
            self.bind("<Button-5>",   self._on_wheel)
            self.canvas = tk.Canvas(self, bg=self.MASK_COLOR, highlightthickness=0)
            self.canvas.pack(fill="both", expand=True)
            self.canvas.bind("<Configure>",  lambda e: self._reload_face())
            self.canvas.bind("<MouseWheel>", self._on_wheel)
            self.canvas.bind("<Button-4>",   self._on_wheel)
            self.canvas.bind("<Button-5>",   self._on_wheel)
            self.face_img   = None
            self.face_photo = None
            self._load_face()
            self._tick()

        def _draw_bg(self, cx, cy, rx, ry, color=None):
            fill = color if color else self.BG
            if self._rect_mode:
                w = max(1, self.canvas.winfo_width())
                h = max(1, self.canvas.winfo_height())
                self.canvas.create_rectangle(0, 0, w, h, fill=fill, outline=fill)
            else:
                self.canvas.create_oval(cx-rx, cy-ry, cx+rx, cy+ry, fill=fill, outline=fill)

        def set_rect_mode(self, val: bool):
            self._rect_mode = val
            bg = self.BG if val else self.MASK_COLOR
            self.configure(bg=bg)
            self.canvas.configure(bg=bg)

        def _update_size(self):
            w = int(self.BASE_WIDTH  * self._scale_factor)
            h = int(self.BASE_HEIGHT * self._scale_factor)
            try:
                g = self.geometry()
                if '+' in g:
                    parts = g.split('+')
                    if len(parts) == 3:
                        self.geometry(f"{w}x{h}+{parts[1]}+{parts[2]}")
                        return
            except Exception:
                pass
            self.geometry(f"{w}x{h}")

        def _center(self):
            self.update_idletasks()
            w,h = self.winfo_width(), self.winfo_height()
            x = (self.winfo_screenwidth()  // 2) - (w // 2)
            y = (self.winfo_screenheight() // 2) - (h // 2)
            self.geometry(f"{w}x{h}+{x}+{y}")

        def _start_drag(self, e):
            self._drag_data["x"] = e.x_root - self.winfo_x()
            self._drag_data["y"] = e.y_root - self.winfo_y()

        def _do_drag(self, e):
            self.geometry(f"+{e.x_root-self._drag_data['x']}+{e.y_root-self._drag_data['y']}")

        def _on_wheel(self, event):
            ns = min(self.SCALE_MAX, self._scale_factor + self.SCALE_STEP) \
                 if (event.delta > 0 or event.num == 4) \
                 else max(self.SCALE_MIN, self._scale_factor - self.SCALE_STEP)
            if ns != self._scale_factor:
                self._scale_factor = ns
                self._update_size()
                self._reload_face()

        def _load_face(self):
            candidates = [
                os.path.join(os.path.dirname(os.path.abspath(__file__)), "readme_images/face.png"),
                "face.png",
            ]
            for path in candidates:
                if os.path.exists(path):
                    try:
                        self.face_img = Image.open(path).convert("RGBA")
                        print(f"Face image loaded: {path}")
                        self._reload_face()
                        return
                    except Exception as e:
                        print(f"Face load error: {e}")
            print("face.png not found — face avatar will show radial lines only.")

        def _reload_face(self):
            if self.face_img is None:
                return
            cw = max(1, self.canvas.winfo_width())
            ch = max(1, self.canvas.winfo_height())
            dw = cw - self.pad*2
            dh = ch - self.pad*2
            if dw > 0 and dh > 0:
                resized = self.face_img.resize((dw, dh), Image.Resampling.LANCZOS)
                self.face_photo = ImageTk.PhotoImage(resized)

        def _ellipse_geom(self):
            cw = max(1, self.canvas.winfo_width())
            ch = max(1, self.canvas.winfo_height())
            cx, cy = cw//2, ch//2
            rx = max(1, cw//2 - self.pad)
            ry = max(1, ch//2 - self.pad)
            return cx, cy, rx, ry

        def set_level(self, level: int):
            self.level = max(0, min(self.LEVELS-1, int(level)))

        def show(self):
            self.deiconify(); self.lift()

        def hide(self):
            self.withdraw()

        def destroy(self):
            self._running = False
            try:
                if self._animation_timer is not None:
                    self.after_cancel(self._animation_timer)
            except Exception:
                pass
            super().destroy()

        def _tick(self):
            if not self._running:
                return
            self.redraw()
            self._animation_timer = self.after(16, self._tick)

        def redraw(self):
            target = self.level / float(self.LEVELS-1)
            self._smoothed += (target - self._smoothed) * self.PULSE_SMOOTHING
            self.canvas.delete("all")
            cx, cy, rx, ry = self._ellipse_geom()
            self._draw_bg(cx, cy, rx, ry)
            if self.face_photo:
                self.canvas.create_image(cx-self.face_photo.width()//2,
                                         cy-self.face_photo.height()//2,
                                         anchor="nw", image=self.face_photo)
            pulse = self._smoothed * (0.8 + 0.4*math.sin(time.perf_counter()*8))
            dr = max(2, int(4+pulse*6))
            self.canvas.create_oval(cx-dr,cy-dr,cx+dr,cy+dr,
                                    fill=self.DOT_COLOR,outline=self.DOT_COLOR)
            if pulse > 0.05:
                avg_r = (rx+ry)/2
                mll   = avg_r * self.MAX_LINE_LENGTH * pulse
                for i in range(self.MAX_LINES):
                    angle = (2*math.pi*i)/self.MAX_LINES
                    ll    = mll*(0.7+0.6*math.sin(angle*3+time.perf_counter()*6))
                    ex    = cx+ll*math.cos(angle)
                    ey    = cy+ll*math.sin(angle)
                    lw    = max(1, int(1+pulse*3))
                    self.canvas.create_line(cx,cy,ex,ey,
                                            fill=self.LINE_COLOR,width=lw,capstyle=tk.ROUND)


# ═════════════════════════════════════════════════════════════════════════════
# OCEAN DEPTH
# ═════════════════════════════════════════════════════════════════════════════
class OceanDepthAvatar(BaseAvatarWindow):
    def __init__(self, master):
        super().__init__(master, "Avatar - Ocean Depth")
        self._last = time.perf_counter()
        self._t = 0.0
        self._blooms = []
        self._motes  = []
        self._pinpricks = [{'x': RADIUS+random.uniform(-RADIUS*.6,RADIUS*.6),
                            'y': RADIUS+random.uniform(-RADIUS*.6,RADIUS*.6),
                            'phase': random.uniform(0,2*math.pi)} for _ in range(4)]
        self._tick()

    def _tick(self):
        if not self._running: return
        now = time.perf_counter()
        dt = min(now - self._last, 0.05)
        self._last = now
        self._t += dt
        self._dt = dt
        self.redraw()
        self._animation_timer = self.after(33, self._tick)

    def _new_bloom(self, amp):
        cx, cy, r = self._circle_geom()
        a = random.uniform(0, 2 * math.pi)
        d = random.uniform(0, r * .6)
        return {'x': cx + d * math.cos(a), 'y': cy + d * math.sin(a),
                'base_r': random.uniform(15, 40) * (0.5 + amp),
                'phase': random.uniform(0, 2 * math.pi), 'pulse_speed': random.uniform(0.7, 1.5),
                'life': random.uniform(0.6, 1.0), 'max_life': random.uniform(0.6, 1.0),
                'tendril_angle': random.uniform(-0.3, 0.3),
                'tendril_sway_phase': random.uniform(0, 2 * math.pi)}

    def _new_mote(self):
        cx, cy, r = self._circle_geom()
        a = random.uniform(0, 2 * math.pi)
        d = random.uniform(0, r * .9)
        return {'x': cx + d * math.cos(a), 'y': cy + d * math.sin(a),
                'vy': random.uniform(-0.8, -0.2), 'vx': random.uniform(-0.2, 0.2),
                'life': 1.0, 'speed': random.uniform(0.3, 1.0)}

    def redraw(self):
        amp = self.level / float(self.LEVELS-1)
        dt  = getattr(self, '_dt', 0.033)
        cx, cy, r = self._circle_geom()
        self.canvas.delete("all")
        bg = _blend_hex('#000000','#020818', amp)
        self._draw_bg(cx, cy, r, bg)
        if amp > 0.3:
            gr = int(r*amp*0.8)
            for g in range(gr,0,-max(1,gr//8)):
                v = amp*0.6*(1-g/gr)*0.4
                self.canvas.create_oval(cx-g,cy-g,cx+g,cy+g,
                    fill=self._hsv_to_hex(0.6,0.8,v),outline='')
        for pp in self._pinpricks:
            blink = 0.03+0.02*math.sin(self._t*0.3+pp['phase'])
            self.canvas.create_oval(pp['x']-1,pp['y']-1,pp['x']+1,pp['y']+1,
                fill=self._hsv_to_hex(0.5,0.8,blink),outline='')
        while len(self._blooms) < int(amp*30):
            self._blooms.append(self._new_bloom(amp))
        alive = []
        for b in self._blooms:
            b['life'] -= dt*0.3
            if b['life'] <= 0: continue
            lf = b['life']/b['max_life']
            pulse = 1.0+0.15*math.sin(self._t*b['pulse_speed']*2*math.pi/1.2+b['phase'])
            br = b['base_r']*pulse*lf
            for ri, rc in enumerate(['#00FFCC','#00E5FF','#E0F7FF']):
                rr = br*(1-ri*0.25)
                if rr < 2: continue
                af = lf*(1-ri*0.2)
                st = _stipple(af*0.8)
                kw = {'outline':rc,'width':1}
                if st: kw['stipple']=st
                self.canvas.create_oval(b['x']-rr,b['y']-rr,b['x']+rr,b['y']+rr,**kw)
            sway = 0.3*math.sin(self._t*0.8+b['tendril_sway_phase'])
            for ti in range(3):
                ta = math.pi/2+(ti-1)*0.4+sway+b['tendril_angle']
                tl = br*1.8*lf
                pts = []
                for s in range(9):
                    frac=s/8
                    pts.extend([b['x']+frac*tl*math.sin(ta+frac*sway*2),
                                 b['y']+frac*tl*math.cos(ta)])
                if len(pts)>=4:
                    self.canvas.create_line(*pts,fill='#00FFAA',
                                           width=max(1,int(3*lf)),smooth=True)
            alive.append(b)
        self._blooms = alive
        while len(self._motes) < int(80+amp*120):
            self._motes.append(self._new_mote())
        alive = []
        for m in self._motes:
            m['x']+=m['vx']; m['y']+=m['vy']*m['speed']
            m['life']-=dt*0.4
            dx=m['x']-cx; dy=m['y']-cy
            if m['life']<=0 or dx*dx+dy*dy>r*r: continue
            st=_stipple(m['life'])
            kw={'fill':'#AAFFEE','outline':''}
            if st: kw['stipple']=st
            self.canvas.create_oval(m['x']-1,m['y']-1,m['x']+1,m['y']+1,**kw)
            alive.append(m)
        self._motes = alive


# ═════════════════════════════════════════════════════════════════════════════
# STORM CELL
# ═════════════════════════════════════════════════════════════════════════════
class StormCellAvatar(BaseAvatarWindow):
    def __init__(self, master):
        super().__init__(master, "Avatar - Storm Cell")
        self._last   = time.perf_counter()
        self._rot    = 0.0
        self._bolts  = []
        self._rain   = [self._new_rain() for _ in range(120)]
        self._tick()

    def _tick(self):
        if not self._running: return
        now = time.perf_counter()
        dt = min(now-self._last, 0.05)
        self._last = now; self._dt = dt
        self.redraw()
        self._animation_timer = self.after(33, self._tick)

    def _new_rain(self):
        cx, cy, r = self._circle_geom()
        a = random.uniform(0, 2 * math.pi)
        d = random.uniform(0, r)
        return {'x': cx + d * math.cos(a), 'y': cy + d * math.sin(a),
                'length': random.uniform(8, 22), 'speed': random.uniform(3, 7)}

    def _new_bolt(self, cx, cy, start_r):
        angle = random.uniform(0, 2 * math.pi)
        segments = random.randint(4, 7)
        pts = []
        x = cx + start_r * math.cos(angle)
        y = cy + start_r * math.sin(angle)
        pts.extend([x, y])
        r = self._circle_geom()[2]
        seg_len = max(1, (r - start_r)) / segments
        for _ in range(segments):
            angle += random.uniform(-0.6, 0.6)
            x += seg_len * math.cos(angle) + random.uniform(-10, 10)
            y += seg_len * math.sin(angle) + random.uniform(-10, 10)
            pts.extend([x, y])
        return {'pts': pts, 'life': 1}

    def redraw(self):
        amp = self.level/float(self.LEVELS-1)
        cx, cy, r = self._circle_geom()
        self.canvas.delete("all")
        self._draw_bg(cx, cy, r, '#0A0A0A')
        self._rot += _lerp(0.3,4.5,amp)
        colors = ['#AAFF00','#F0F0FF','#6600AA','#FF6600','#FFFFFF']
        num_e = int(1+amp*17)
        for i in range(num_e):
            t = i/max(num_e-1,1)
            rx = int(r*(0.15+t*0.75)); ry = int(rx*(0.6+t*0.3))
            ao = math.radians(self._rot+i*(360/max(num_e,1)))
            pts = []
            for s in range(48):
                a=2*math.pi*s/48
                ex=rx*math.cos(a); ey=ry*math.sin(a)
                pts.extend([cx+ex*math.cos(ao)-ey*math.sin(ao),
                             cy+ex*math.sin(ao)+ey*math.cos(ao)])
            if len(pts)>=4:
                self.canvas.create_polygon(*pts,outline=colors[i%len(colors)],
                                           fill='',width=max(1,int(1+amp*2)),smooth=True)
        for _ in range(int(amp*12)):
            self._bolts.append(self._new_bolt(cx,cy,r*random.uniform(0.1,0.5)))
        alive=[]
        for bolt in self._bolts:
            bolt['life']-=1
            if bolt['life']>0 and len(bolt['pts'])>=4:
                self.canvas.create_line(*bolt['pts'],fill='#FFFFFF',width=2)
                alive.append(bolt)
        self._bolts=alive
        for rain in self._rain:
            rain['x']+=rain['speed']*0.7; rain['y']+=rain['speed']
            dx=rain['x']-cx; dy=rain['y']-cy
            if dx*dx+dy*dy>r*r:
                self._rain[self._rain.index(rain)]=self._new_rain()
                continue
            self.canvas.create_line(rain['x'],rain['y'],
                rain['x']-rain['length']*0.7,rain['y']-rain['length'],
                fill='#FFFFFF',width=1,stipple='gray12')


# ═════════════════════════════════════════════════════════════════════════════
# CRYSTAL MATRIX
# ═════════════════════════════════════════════════════════════════════════════
class CrystalMatrixAvatar(BaseAvatarWindow):
    def __init__(self, master):
        super().__init__(master, "Avatar - Crystal Matrix")
        self._last = time.perf_counter()
        self._t = 0.0
        self._shards = []
        self._tris = []
        self.after(100, self._build_lattice)
        self._tick()

    def _build_lattice(self):
        cx, cy, r = self._circle_geom()
        seeds = [(cx, cy)]
        for _ in range(79):
            a = random.uniform(0, 2 * math.pi)
            d = random.uniform(0, r * .92)
            seeds.append((cx + d * math.cos(a), cy + d * math.sin(a)))
        used = set()
        for i, (xi, yi) in enumerate(seeds):
            dists = sorted([((seeds[j][0] - xi) ** 2 + (seeds[j][1] - yi) ** 2, j)
                            for j in range(len(seeds)) if j != i])
            nbrs = [d[1] for d in dists[:6]]
            for ni in range(len(nbrs) - 1):
                j, k = nbrs[ni], nbrs[ni + 1]
                key = tuple(sorted([i, j, k]))
                if key in used: continue
                used.add(key)
                xj, yj = seeds[j]
                xk, yk = seeds[k]
                mx = (xi + xj + xk) / 3
                my = (yi + yj + yk) / 3
                if (mx - cx) ** 2 + (my - cy) ** 2 < r ** 2 * 0.9:
                    self._tris.append({
                        'pts': [(xi, yi), (xj, yj), (xk, yk)],
                        'dist': math.sqrt((mx - cx) ** 2 + (my - cy) ** 2),
                        'hue': random.random(), 'active': False})

    def _tick(self):
        if not self._running: return
        now=time.perf_counter()
        dt=min(now-self._last,0.05)
        self._last=now; self._t+=dt
        self.redraw()
        self._animation_timer=self.after(33,self._tick)

    def redraw(self):
        amp=self.level/float(self.LEVELS-1)
        cx,cy,r=self._circle_geom()
        self.canvas.delete("all")
        self._draw_bg(cx, cy, r)
        hs=(self._t*0.8/360.0)%1.0
        for tri in self._tris:
            tri['active']=amp>(tri['dist']/RADIUS)*0.9
            hue=(tri['hue']+hs)%1.0
            pts_flat=[c for pt in tri['pts'] for c in pt]
            if tri['active']:
                fc=self._hsv_to_hex(hue,_lerp(0.7,1.0,amp),_lerp(0.4,1.0,amp))
                oc='#FFFFFF' if amp>0.7 else self._hsv_to_hex(hue,0.5,0.6)
                ow=2 if amp>0.7 else 1
            else:
                fc=''; oc='#1A1A1A'; ow=1
            if len(pts_flat)>=6:
                self.canvas.create_polygon(*pts_flat,fill=fc,outline=oc,width=ow)
        if amp>0.6:
            active=[t for t in self._tris if t['active']]
            if active and random.random()<amp:
                tri=random.choice(active)
                pts=tri['pts']; ei=random.randint(0,2)
                p1=pts[ei]; p2=pts[(ei+1)%3]
                mx=(p1[0]+p2[0])/2; my=(p1[1]+p2[1])/2
                angle=math.atan2(my-cy,mx-cx); length=random.uniform(20,60)
                self._shards.append({'x1':mx,'y1':my,
                    'x2':mx+length*math.cos(angle),'y2':my+length*math.sin(angle),
                    'life':8,'w':random.randint(2,4)})
        alive=[]
        for s in self._shards:
            s['life']-=1
            if s['life']>0:
                st=_stipple(s['life']/8.0)
                kw={'fill':'#FFFFFF','width':s['w']}
                if st: kw['stipple']=st
                self.canvas.create_line(s['x1'],s['y1'],s['x2'],s['y2'],**kw)
                alive.append(s)
        self._shards=alive


# ═════════════════════════════════════════════════════════════════════════════
# EVENT HORIZON
# ═════════════════════════════════════════════════════════════════════════════
class EventHorizonAvatar(BaseAvatarWindow):
    def __init__(self, master):
        super().__init__(master, "Avatar - Event Horizon")
        self._last        = time.perf_counter()
        self._t           = 0.0
        self._ring_angles = [0.0]*7
        self._jets        = []
        self._breath      = 0.0
        self._tick()

    def _tick(self):
        if not self._running: return
        now=time.perf_counter()
        dt=min(now-self._last,0.05)
        self._last=now; self._t+=dt; self._dt=dt
        self.redraw()
        self._animation_timer=self.after(33,self._tick)

    def _new_jet(self, cx, cy, pole):
        angle=math.pi*1.5 if pole==0 else math.pi*0.5
        speed=random.uniform(1.5,3.5)
        spread=random.uniform(-0.15,0.15)
        return {'x':cx+random.uniform(-5,5),'y':cy,
                'vx':speed*math.cos(angle+spread),'vy':speed*math.sin(angle+spread),
                'life':1.0,'max_life':0.8,'size':random.uniform(3,8)}

    def redraw(self):
        amp=self.level/float(self.LEVELS-1)
        dt=getattr(self,'_dt',0.033)
        cx,cy,r=self._circle_geom()
        self.canvas.delete("all")
        self._draw_bg(cx, cy, r)
        self._breath+=dt*math.pi
        bh_r=int(r*(0.12+0.06*(0.5+0.5*math.sin(self._breath))))
        speeds=[2*math.pi/(1.2*(i+1)*0.5) for i in range(7)]
        for i in range(7): self._ring_angles[i]+=speeds[i]*dt
        colors=['#CCE0FF','#FFFACC','#FFAA44','#FF6600','#DD3300','#AA1100','#880000']
        for i in range(max(1,int(1+amp*6))):
            ri=bh_r+10+i*18; ro=ri+12
            if ro>r: continue
            col=colors[min(6-i,6)]
            ao=self._ring_angles[i%7]
            pts=[]
            for deg in range(-100,101,5):
                a=math.radians(deg)+ao
                pts.extend([cx+ri*math.cos(a),cy+ri*math.sin(a)*0.35])
            if len(pts)>=4:
                self.canvas.create_line(*pts,fill=col,width=2,smooth=True)
        flicker=1.0+0.1*math.sin(self._t*2*math.pi/0.4)
        gc=self._hsv_to_hex(0.08,0.9,min(1.0,0.7*flicker))
        gw=int(4+amp*4)
        self.canvas.create_oval(cx-bh_r-gw,cy-bh_r-gw,cx+bh_r+gw,cy+bh_r+gw,
                                outline=gc,width=gw)
        self.canvas.create_oval(cx-bh_r,cy-bh_r,cx+bh_r,cy+bh_r,fill='#000000',outline='')
        if amp>0.3:
            for _ in range(int((amp-0.3)/0.7*8)):
                self._jets.append(self._new_jet(cx,cy,0))
                self._jets.append(self._new_jet(cx,cy,1))
        alive=[]
        for p in self._jets:
            p['x']+=p['vx']; p['y']+=p['vy']
            p['life']-=dt/p['max_life']
            if p['life']<=0: continue
            dx=p['x']-cx; dy=p['y']-cy
            if dx*dx+dy*dy>r*r: continue
            tf=1-p['life']
            col='#FFFFFF' if tf<0.3 else '#FFFFAA' if tf<0.6 else '#FF4400'
            pr=max(1,int(p['size']*p['life']))
            self.canvas.create_oval(p['x']-pr,p['y']-pr,p['x']+pr,p['y']+pr,
                                    fill=col,outline='')
            alive.append(p)
        self._jets=alive


# ═════════════════════════════════════════════════════════════════════════════
# PLASMA MEMBRANE
# ═════════════════════════════════════════════════════════════════════════════
class PlasmaMembrane(BaseAvatarWindow):
    def __init__(self, master):
        super().__init__(master, "Avatar - Plasma Membrane")
        self._last = time.perf_counter()
        self._t = 0.0
        self._organelles = []
        self._conns = []
        self._exo = []
        self._mem_phases = [random.uniform(0, 2 * math.pi) for _ in range(32)]
        self.after(100, self._init_organelles)
        self._tick()

    def _init_organelles(self):
        self._organelles = [self._new_org(i) for i in range(6)]

    def _new_org(self, idx):
        cx, cy, r = self._circle_geom()
        types = ['mitochondria', 'nucleus', 'vesicle']
        otype = types[idx % 3]
        a = random.uniform(0, 2 * math.pi)
        d = random.uniform(0, r * .55)
        return {'x': cx + d * math.cos(a), 'y': cy + d * math.sin(a),
                'vx': random.uniform(-0.3, 0.3), 'vy': random.uniform(-0.3, 0.3),
                'type': otype, 'num_v': random.randint(8, 12),
                'radii': [random.uniform(18, 35) for _ in range(12)],
                'phase': random.uniform(0, 2 * math.pi), 'squash': 1.0, 'squash_v': 0.0}

    def _tick(self):
        if not self._running: return
        now=time.perf_counter()
        dt=min(now-self._last,0.05)
        self._last=now; self._t+=dt; self._dt=dt
        self.redraw()
        self._animation_timer=self.after(33,self._tick)

    def redraw(self):
        amp=self.level/float(self.LEVELS-1)
        dt=getattr(self,'_dt',0.033)
        cx,cy,r=self._circle_geom()
        self.canvas.delete("all")
        self._draw_bg(cx, cy, r, '#020D02')
        mem_freq=_lerp(0.3,1.8,amp)
        mem_pts=[]
        for i in range(32):
            a=2*math.pi*i/32
            disp=12*math.sin(self._t*mem_freq*2*math.pi+self._mem_phases[i])
            mr=r-8+disp
            mem_pts.extend([cx+mr*math.cos(a),cy+mr*math.sin(a)])
        if len(mem_pts)>=6:
            self.canvas.create_polygon(*mem_pts,fill='',outline='#004422',width=2,smooth=True)
        colors={'mitochondria':('#882200','#AA3300'),
                'nucleus':('#220044','#6600CC'),
                'vesicle':('#004422','#006633')}
        for org in self._organelles:
            org['x']+=org['vx']; org['y']+=org['vy']
            dx=org['x']-cx; dy=org['y']-cy
            if math.sqrt(dx*dx+dy*dy)>r*.75:
                org['vx']*=-1; org['vy']*=-1; org['squash_v']=0.3
            org['squash']+=org['squash_v']*dt*5
            org['squash_v']-=(org['squash']-1.0)*8*dt
            org['squash_v']*=0.85
            org['squash']=_clamp(org['squash'],0.7,1.4)
            fc,oc=colors[org['type']]
            pts=[]
            for i in range(org['num_v']):
                a=2*math.pi*i/org['num_v']
                rv2=org['radii'][i]*org['squash']
                pts.extend([org['x']+rv2*math.cos(a),org['y']+rv2*math.sin(a)])
            if len(pts)>=6:
                self.canvas.create_polygon(*pts,fill=fc,outline=oc,width=1,smooth=True)
        if random.random()<amp*20*dt and len(self._organelles)>=2:
            o1,o2=random.sample(self._organelles,2)
            self._conns.append({'x1':o1['x'],'y1':o1['y'],'x2':o2['x'],'y2':o2['y'],
                                'life':1.0,'decay':random.uniform(1.5,2.5)})
        alive=[]
        for c in self._conns:
            c['life']-=dt*c['decay']
            if c['life']>0:
                st=_stipple(c['life'])
                kw={'fill':'#00FF44','width':1}
                if st: kw['stipple']=st
                self.canvas.create_line(c['x1'],c['y1'],c['x2'],c['y2'],**kw)
                alive.append(c)
        self._conns=alive
        if amp>0.85 and random.random()<0.1:
            nearest=min(self._organelles,key=lambda o:(o['x']-cx)**2+(o['y']-cy)**2)
            for _ in range(random.randint(40,100)):
                self._exo.append({'x':nearest['x'],'y':nearest['y'],
                                  'vx':random.uniform(-2,2),'vy':random.uniform(-2,2),'life':1.0})
        alive=[]
        for p in self._exo:
            p['x']+=p['vx']; p['y']+=p['vy']; p['life']-=dt/0.5
            if p['life']<=0: continue
            dx=p['x']-cx; dy=p['y']-cy
            if dx*dx+dy*dy>r*r: continue
            st=_stipple(p['life'])
            kw={'fill':'#AAFFAA','outline':''}
            if st: kw['stipple']=st
            self.canvas.create_oval(p['x']-2,p['y']-2,p['x']+2,p['y']+2,**kw)
            alive.append(p)
        self._exo=alive


# ═════════════════════════════════════════════════════════════════════════════
# REGISTRY
# ═════════════════════════════════════════════════════════════════════════════
AVATARS = [
    ("Rings",          CircleAvatarWindow),
    ("Rectangles H",   RectAvatarWindow),
    ("Rectangles H+V", RectAvatarWindow2),
    ("Radial Pulse",   RadialPulseAvatar),
    ("String Grid",    StringGridAvatar),
    ("HAL 9000",       Hal9000Avatar),
    ("Orbs",           OrbAvatarWindow),
    ("Neural Net",     NeuralNetAvatarWindow),
    ("DNA Helix",      DNAHelixAvatar),
    ("Tesla Coil",     TeslaCoilAvatar),
    ("Ocean Depth",    OceanDepthAvatar),
    ("Storm Cell",     StormCellAvatar),
    ("Crystal Matrix", CrystalMatrixAvatar),
    ("Event Horizon",  EventHorizonAvatar),
    ("Plasma Membrane",PlasmaMembrane),
]

if PIL_OK:
    AVATARS.append(("Texture Sphere", TextureMappedSphere))
    AVATARS.append(("Face Radial",    FaceRadialAvatar))


# ═════════════════════════════════════════════════════════════════════════════
# CONTROL PANEL
# ═════════════════════════════════════════════════════════════════════════════
class ControlPanel(tk.Tk):
    def __init__(self, stream, pa):
        super().__init__()
        self._stream = stream
        self._pa     = pa
        self._avatar = None

        self.title("AvatarEcho")
        self.configure(bg="#0a0a0a")
        self.resizable(False, False)

        tk.Label(self, text="AvatarEcho",
                 font=("Courier New",13,"bold"),fg="#ff3c3c",bg="#0a0a0a").pack(pady=(14,2))
        tk.Label(self, text="AVATAR SOUND-TO-LIGHT",
                 font=("Courier New",10),fg="#881111",bg="#0a0a0a").pack(pady=(0,6))

        # ── VU meter ─────────────────────────────────────────────────────
        self._vu = tk.Canvas(self,width=240,height=14,bg="#111111",highlightthickness=0)
        self._vu.pack(pady=(0,4))
        self._vu_bar = self._vu.create_rectangle(0,0,0,14,fill="#ff3c3c",outline="")

        src_col = "#ff3c3c" if stream else "#886600"
        src_txt = "SRC: WASAPI LOOPBACK" if stream else "SRC: NO AUDIO"
        tk.Label(self,text=src_txt,font=("Courier New",9),fg=src_col,bg="#0a0a0a").pack(pady=(0,4))

        # ── Sensitivity slider ────────────────────────────────────────────
        tk.Label(self, text="SENSITIVITY", font=("Courier New", 9, "bold"),
                 fg="#cc2222", bg="#0a0a0a").pack()
        self._sens_var = tk.DoubleVar(value=1.0)
        tk.Scale(self, variable=self._sens_var,
                 from_=0.5, to=8.0, resolution=0.1,
                 orient="horizontal", length=240,
                 bg="#0a0a0a", fg="white", troughcolor="#330000",
                 highlightthickness=0, showvalue=True).pack(pady=(0, 8))

        # ── Window shape toggle ───────────────────────────────────────────
        tk.Frame(self, height=1, bg="#441111").pack(fill="x", padx=20, pady=(0, 4))
        self._rect_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self, text="Rectangular window  (unchecked = circular)",
                       variable=self._rect_var,
                       font=("Courier New", 9),
                       fg="white", bg="#0a0a0a",
                       selectcolor="#330000",
                       activebackground="#0a0a0a",
                       command=self._on_shape_toggle).pack(pady=(2, 6))
        tk.Frame(self, height=1, bg="#441111").pack(fill="x", padx=20, pady=(0, 6))

        # ── Avatar buttons ────────────────────────────────────────────────
        tk.Label(self,text="SELECT AVATAR",font=("Courier New",9,"bold"),fg="#cc2222",bg="#0a0a0a").pack()

        btn_frame = tk.Frame(self,bg="#0a0a0a")
        btn_frame.pack(pady=6,padx=20,fill="x")
        for name, cls in AVATARS:
            tk.Button(btn_frame,text=name,font=("Courier New",10,"bold"),
                      fg="white",bg="#1a0000",
                      activeforeground="black",activebackground="#ff3c3c",
                      relief="flat",bd=0,padx=8,pady=4,
                      command=lambda c=cls,n=name: self._launch(c,n)
                      ).pack(fill="x",pady=2)

        # ── separator ────────────────────────────────────────────────────
        tk.Frame(self,height=1,bg="#441111").pack(fill="x",padx=20,pady=8)

        # ── Echo Engine ───────────────────────────────────────────────────
        self._echo = None
        if stream and pa:
            try:
                self._echo = EchoInjector(pa, _pcm_sr, intensity=0.47, delay_ms=144.0)
            except Exception as e:
                print(f"EchoInjector init failed: {e}")

        tk.Label(self,text="ECHO",font=("Courier New",9,"bold"),
                 fg="#cc2222",bg="#0a0a0a").pack()

        self._echo_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self,text="Enable echo injection",
                       variable=self._echo_var,font=("Courier New",9),
                       fg="white",bg="#0a0a0a",selectcolor="#330000",
                       activebackground="#0a0a0a",
                       command=self._on_echo_toggle).pack()

        ctrl = tk.Frame(self,bg="#0a0a0a")
        ctrl.pack(padx=16,fill="x")

        tk.Label(ctrl,text="Intensity",font=("Courier New",8),
                 fg="#cc2222",bg="#0a0a0a").grid(row=0,column=0,sticky="w")
        self._intensity_sl = tk.Scale(ctrl,from_=0.0,to=1.0,resolution=0.01,
                                      orient="horizontal",length=180,
                                      bg="#0a0a0a",fg="white",troughcolor="#330000",
                                      highlightthickness=0,showvalue=True,
                                      command=self._on_intensity)
        self._intensity_sl.set(0.47)
        self._intensity_sl.grid(row=0,column=1)

        tk.Label(ctrl,text="Delay (ms)",font=("Courier New",8),
                 fg="#cc2222",bg="#0a0a0a").grid(row=1,column=0,sticky="w")
        self._delay_sl = tk.Scale(ctrl,from_=60.0,to=480.0,resolution=1.0,
                                  orient="horizontal",length=180,
                                  bg="#0a0a0a",fg="white",troughcolor="#330000",
                                  highlightthickness=0,showvalue=True,
                                  command=self._on_delay)
        self._delay_sl.set(144.0)
        self._delay_sl.grid(row=1,column=1)

        # ── Output device selector ────────────────────────────────────────
        tk.Label(self, text="ECHO OUTPUT", font=("Courier New", 9, "bold"),
                 fg="#cc2222", bg="#0a0a0a").pack()

        self._out_devices = self._list_output_devices(pa)
        out_names = [f"[{i}] {name}" for i, name in self._out_devices]

        self._out_var = tk.StringVar()
        self._out_combo = tk.OptionMenu(self, self._out_var, *out_names,
                                        command=self._on_out_device_change)
        self._out_combo.config(bg="#1a0000", fg="white", font=("Courier New", 9),
                               activebackground="#ff3c3c", highlightthickness=0)
        self._out_combo["menu"].config(bg="#1a0000", fg="white")
        self._out_combo.pack(fill="x", padx=20, pady=(2, 8))

        for entry in out_names:
            if "cable" not in entry.lower():
                self._out_var.set(entry)
                break

        # ── separator ────────────────────────────────────────────────────
        tk.Frame(self,height=1,bg="#441111").pack(fill="x",padx=20,pady=8)

        tk.Button(self,text="CLOSE AVATAR",font=("Courier New",10),
                  fg="#ff3c3c",bg="#0a0a0a",relief="flat",
                  command=self._close_avatar).pack(pady=2)
        tk.Button(self,text="QUIT",font=("Courier New",10),
                  fg="#ff3c3c",bg="#0a0a0a",relief="flat",
                  command=self._quit).pack(pady=(2,14))

        self.protocol("WM_DELETE_WINDOW", self._quit)
        self._update()

    # ── shape toggle ──────────────────────────────────────────────────────
    def _on_shape_toggle(self):
        if self._avatar:
            self._avatar.set_rect_mode(self._rect_var.get())

    # ── echo callbacks ─────────────────────────────────────────────────────
    def _on_echo_toggle(self):
        if self._echo:
            self._echo.set_enabled(self._echo_var.get())

    def _on_intensity(self, val):
        if self._echo:
            self._echo.set_intensity(float(val))

    def _on_delay(self, val):
        if self._echo:
            self._echo.set_delay(float(val))

    def _list_output_devices(self, pa):
        devices = []
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev['maxOutputChannels'] > 0:
                devices.append((i, dev['name'][:40]))
        return devices

    # ── avatar management ─────────────────────────────────────────────────
    def _launch(self, cls, name):
        self._close_avatar()
        self._avatar = cls(self)
        self._avatar.set_rect_mode(self._rect_var.get())
        self._avatar.show()
        print(f"Avatar: {name}")

    def _close_avatar(self):
        if self._avatar:
            try:   self._avatar.destroy()
            except Exception: pass
            self._avatar = None

    def _on_out_device_change(self, selection):
        idx = int(selection.split("]")[0].replace("[", "").strip())
        if self._echo:
            was_enabled = self._echo.enabled
            if was_enabled:
                self._echo.set_enabled(False)
            self._echo._out_idx = idx
            print(f"Echo output changed to: {selection}")
            if was_enabled:
                self._echo.set_enabled(True)

    # ── VU / level update loop ────────────────────────────────────────────
    def _update(self):
        with _lock:
            amp = _smooth_amp
        # Apply sensitivity scaling — clamped to [0, 1] before level conversion
        scaled = min(1.0, amp * self._sens_var.get())
        level = int(scaled * (LEVELS - 1))
        if self._avatar:
            try:   self._avatar.set_level(level)
            except Exception: self._avatar = None
        w = int(240 * amp)   # VU bar still shows raw amp so you can see true signal level
        self._vu.coords(self._vu_bar, 0, 0, w, 14)
        r2 = int(255*min(1.0, amp*2)); g2 = int(255*min(1.0, (1.0-amp)*2))
        self._vu.itemconfig(self._vu_bar, fill=f"#{r2:02x}{g2:02x}00")
        self.after(30, self._update)

    # ── quit ──────────────────────────────────────────────────────────────
    def _quit(self):
        if self._echo:
            self._echo.set_enabled(False)
        self._close_avatar()
        if self._stream:
            try: self._stream.stop_stream(); self._stream.close()
            except Exception: pass
        if self._pa:
            try: self._pa.terminate()
            except Exception: pass
        self.destroy()


# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("AvatarEcho - Complete Edition with DNA Helix, Tesla Coil, and Sci-Fi Echo")
    stream, pa = _start_loopback()
    app = ControlPanel(stream, pa)
    app.mainloop()