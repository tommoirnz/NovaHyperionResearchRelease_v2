
# All avatars + WASAPI loopback + Schroeder reverb injection
# pip install pyaudiowpatch numpy pillow

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
# Audio callback  (single definition)
# ─────────────────────────────────────────────
def _audio_callback(in_data, frame_count, time_info, status):
    global _smooth_amp
    pcm = np.frombuffer(in_data, dtype=np.float32).copy()

    # --- feed reverb ring-buffer (mono mix) ---
    if len(pcm) >= frame_count:
        mono = pcm[:frame_count * _pcm_ch]
        if _pcm_ch == 2 and len(mono) == frame_count * 2:
            mono = mono.reshape(-1, 2).mean(axis=1)
        elif len(mono) > frame_count:
            mono = mono[:frame_count]
        with _pcm_buf_lock:
            _pcm_buf.extend(mono.tolist())
            max_len = _pcm_sr * 2          # cap at 2 s
            while len(_pcm_buf) > max_len:
                _pcm_buf.popleft()

    # --- amplitude for visuals ---
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
# Loopback start  (single definition)
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


# ═════════════════════════════════════════════════════════════════════════════
# REVERB ENGINE
# ═════════════════════════════════════════════════════════════════════════════
class SingleCombReverb:
    """
    One feedback comb filter + pre-delay.
    Unconditionally stable provided g < 1.0 — which is enforced hard.
    Sci-fi echo character; sounds like the echo engine but driven in real-time.
    """

    def __init__(self, sample_rate=44100, delay_ms=144.0, decay=0.53):
        self.sr       = sample_rate
        self.delay_ms = delay_ms
        self._build(decay)

    def _build(self, decay: float):
        # Hard clamp — above 0.97 risks audible infinite sustain
        self._g = float(np.clip(decay, 0.0, 0.97))

        # Comb delay buffer
        sz = max(2, int(self.sr * self.delay_ms / 1000.0))
        self._buf     = np.zeros(sz, dtype=np.float32)
        self._buf_idx = 0

        # Pre-delay (30 ms) so the echo sits after the dry transient
        pre_sz = max(1, int(self.sr * 0.030))
        self._pre_buf = np.zeros(pre_sz, dtype=np.float32)
        self._pre_idx = 0

    def update_decay(self, decay: float):
        # Only update g — no need to rebuild buffers
        self._g = float(np.clip(decay, 0.0, 0.97))

    def update_delay(self, delay_ms: float):
        self.delay_ms = delay_ms
        # Rebuild comb buffer at new length; pre-delay stays
        sz = max(2, int(self.sr * delay_ms / 1000.0))
        self._buf     = np.zeros(sz, dtype=np.float32)
        self._buf_idx = 0

    def process(self, block: np.ndarray) -> np.ndarray:
        # 1. Pre-delay
        pre_sz  = len(self._pre_buf)
        delayed = np.empty(len(block), dtype=np.float32)
        for n in range(len(block)):
            delayed[n]                   = self._pre_buf[self._pre_idx]
            self._pre_buf[self._pre_idx] = block[n]
            self._pre_idx                = (self._pre_idx + 1) % pre_sz

        # 2. Feedback comb
        buf  = self._buf
        sz   = len(buf)
        idx  = self._buf_idx
        g    = self._g
        out  = np.empty(len(block), dtype=np.float32)
        for n in range(len(delayed)):
            y      = buf[idx]
            buf[idx] = delayed[n] + g * y
            out[n]   = y
            idx      = (idx + 1) % sz
        self._buf_idx = idx
        return out


class ReverbInjector:
    """
    Pulls mono PCM from _pcm_buf, applies SingleCombReverb,
    writes wet signal to the default output device.
    Stability is guaranteed by the comb g < 1 constraint alone.
    """
    CHUNK = 512

    def __init__(self, pa, sample_rate, wet_gain=0.53, decay=0.53):
        self._pa       = pa
        self._sr       = sample_rate
        self._wet_gain = float(np.clip(wet_gain, 0.0, 2.0))
        self._enabled  = False
        self._thread   = None
        self._stop_evt = threading.Event()
        self._reverb   = SingleCombReverb(sample_rate=sample_rate, decay=decay)
        self._out_idx  = pa.get_default_output_device_info()["index"]
        print(f"Reverb output device index: {self._out_idx}")

    @property
    def enabled(self):
        return self._enabled

    def set_enabled(self, value: bool):
        if value and not self._enabled:
            self._start()
        elif not value and self._enabled:
            self._stop()
        self._enabled = value

    def set_wet_gain(self, v: float):
        self._wet_gain = float(np.clip(v, 0.0, 2.0))

    def set_decay(self, v: float):
        # Clamp enforced inside update_decay — no caller can break it
        self._reverb.update_decay(v)

    def _start(self):
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        print("ReverbInjector: started")

    def _stop(self):
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=2)
        print("ReverbInjector: stopped")

    def _run(self):
        try:
            stream_out = self._pa.open(
                format=pyaudio.paFloat32, channels=1, rate=self._sr,
                output=True, output_device_index=self._out_idx,
                frames_per_buffer=self.CHUNK,
            )
        except Exception as e:
            print(f"ReverbInjector: cannot open output stream: {e}")
            return

        while not self._stop_evt.is_set():
            with _pcm_buf_lock:
                if len(_pcm_buf) >= self.CHUNK:
                    samples = [_pcm_buf.popleft() for _ in range(self.CHUNK)]
                else:
                    samples = None

            if samples is None:
                time.sleep(self.CHUNK / self._sr * 0.5)
                continue

            block = np.array(samples, dtype=np.float32)
            wet   = self._reverb.process(block) * self._wet_gain
            # Safety clip — catches any upstream pathology, not the comb itself
            wet   = np.clip(wet, -0.95, 0.95)
            try:
                stream_out.write(wet.tobytes())
            except Exception:
                break

        try:
            stream_out.stop_stream()
            stream_out.close()
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
        self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=self.BG,outline=self.BG)
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
        self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=self.BG,outline=self.BG)
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
        self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=self.BG,outline=self.BG)
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
        self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=self.BG,outline=self.BG)
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
        self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=self.BG,outline=self.BG)
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
        self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill="#000000",outline="#000000")
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
        self.canvas.create_oval(cx-max_r,cy-max_r,cx+max_r,cy+max_r,fill=self.BG,outline=self.BG)
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
        self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=self.BG,outline=self.BG)
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
            self.canvas.create_oval(cx-r,cy-r,cx+r,cy+r,fill=self.BG,outline=self.BG)
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
            self.canvas.create_oval(cx-rx, cy-ry, cx+rx, cy+ry,
                                    fill=self.BG, outline=self.BG)
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
                 font=("Courier New",10),fg="#881111",bg="#0a0a0a").pack(pady=(0,8))

        self._vu = tk.Canvas(self,width=240,height=14,bg="#111111",highlightthickness=0)
        self._vu.pack(pady=(0,4))
        self._vu_bar = self._vu.create_rectangle(0,0,0,14,fill="#ff3c3c",outline="")

        src_col = "#ff3c3c" if stream else "#886600"
        src_txt = "SRC: WASAPI LOOPBACK" if stream else "SRC: NO AUDIO"
        tk.Label(self,text=src_txt,font=("Courier New",9),fg=src_col,bg="#0a0a0a").pack(pady=(0,8))
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

        # ── Reverb ───────────────────────────────────────────────────────
        self._reverb = None
        if stream and pa:
            try:
                self._reverb = ReverbInjector(pa, _pcm_sr)
            except Exception as e:
                print(f"ReverbInjector init failed: {e}")

        tk.Label(self,text="ECHO",font=("Courier New",9,"bold"),
                 fg="#cc2222",bg="#0a0a0a").pack()

        self._reverb_var = tk.BooleanVar(value=False)
        tk.Checkbutton(self,text="Enable reverb injection",
                       variable=self._reverb_var,font=("Courier New",9),
                       fg="white",bg="#0a0a0a",selectcolor="#330000",
                       activebackground="#0a0a0a",
                       command=self._on_reverb_toggle).pack()

        ctrl = tk.Frame(self,bg="#0a0a0a")
        ctrl.pack(padx=16,fill="x")

        tk.Label(ctrl,text="Wet  ",font=("Courier New",8),
                 fg="#cc2222",bg="#0a0a0a").grid(row=0,column=0,sticky="w")
        self._wet_sl = tk.Scale(ctrl,from_=0.0,to=2.0,resolution=0.01,
                                orient="horizontal",length=180,
                                bg="#0a0a0a",fg="white",troughcolor="#330000",
                                highlightthickness=0,showvalue=True,
                                command=self._on_wet)
        self._wet_sl.set(0.34)
        self._wet_sl.grid(row=0,column=1)

        tk.Label(ctrl,text="Decay",font=("Courier New",8),
                 fg="#cc2222",bg="#0a0a0a").grid(row=1,column=0,sticky="w")
        self._decay_sl = tk.Scale(ctrl,from_=0.0,to=0.92,resolution=0.01,
                                  orient="horizontal",length=180,
                                  bg="#0a0a0a",fg="white",troughcolor="#330000",
                                  highlightthickness=0,showvalue=True,
                                  command=self._on_decay)
        self._decay_sl.set(0.53)
        self._decay_sl.grid(row=1,column=1)

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

    # ── reverb callbacks ─────────────────────────────────────────────────
    def _on_reverb_toggle(self):
        if self._reverb:
            self._reverb.set_enabled(self._reverb_var.get())

    def _on_wet(self, val):
        if self._reverb:
            self._reverb.set_wet_gain(float(val))

    def _on_decay(self, val):
        if self._reverb:
            self._reverb.set_decay(float(val))

    # ── avatar management ────────────────────────────────────────────────
    def _launch(self, cls, name):
        self._close_avatar()
        self._avatar = cls(self)
        self._avatar.show()
        print(f"Avatar: {name}")

    def _close_avatar(self):
        if self._avatar:
            try:   self._avatar.destroy()
            except Exception: pass
            self._avatar = None

    # ── VU / level update loop ───────────────────────────────────────────
    def _update(self):
        with _lock:
            amp = _smooth_amp
        level = int(amp*(LEVELS-1))
        if self._avatar:
            try:   self._avatar.set_level(level)
            except Exception: self._avatar = None
        w = int(240*amp)
        self._vu.coords(self._vu_bar, 0, 0, w, 14)
        r2 = int(255*min(1.0, amp*2)); g2 = int(255*min(1.0, (1.0-amp)*2))
        self._vu.itemconfig(self._vu_bar, fill=f"#{r2:02x}{g2:02x}00")
        self.after(30, self._update)

    # ── quit ─────────────────────────────────────────────────────────────
    def _quit(self):
        if self._reverb:
            self._reverb.set_enabled(False)
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
    print("AvatarEcho")
    stream, pa = _start_loopback()
    app = ControlPanel(stream, pa)
    app.mainloop()