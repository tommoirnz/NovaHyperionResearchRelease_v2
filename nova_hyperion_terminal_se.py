# ─────────────────────────────────────────────────────────────────────────────
# NOVA HYPERION TERMINAL — SPECIAL EDITION
# Wired to Nova's HTTP web API (nova_web.py / nova_web_lcars.py)
# Polls /api/history · Sends via /api/send · Voice via /api/voice
# TTS via /api/speak (edge_tts MP3) · Upload via /api/upload
# This is text only, no images and fancy stuff. Use nova_web.py for that!
# ─────────────────────────────────────────────────────────────────────────────

import tkinter as tk
from tkinter import filedialog
import threading
import time
import math
import random
import sounddevice as sd
import numpy as np
from datetime import datetime
import queue
import sys
import os
import json
import wave
import io
import struct

# ── External deps ─────────────────────────────────────────────────────────────
try:
    import requests
    requests.packages.urllib3.disable_warnings()   # suppress self-signed cert noise
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False
    print("WARNING: 'requests' not installed — pip install requests")

try:
    from pydub import AudioSegment
    PYDUB_OK = True
except ImportError:
    PYDUB_OK = False
    print("INFO: pydub not installed — TTS playback disabled (pip install pydub)")

# ═════════════════════════════════════════════════════════════════════════════
# CONFIG  — edit BASE_URL to match your Nova server. If you don't use https it won't work on wireless based devices and phones
# ═════════════════════════════════════════════════════════════════════════════
BASE_URL   = "https://192.168.178.58:8080" # change to https://192.168.178.58:8080 for LAN
POLL_MS    = 1500                        # history poll interval
PING_MS    = 4000                        # online status check interval
VERIFY_SSL = False                       # False for self-signed cert

# ─────────────────────────────────────────────────────────────────────────────
# COLOR PALETTE
# ─────────────────────────────────────────────────────────────────────────────
C = {
    "void":       "#020408",
    "amber":      "#FFB300",
    "coral":      "#FF5500",
    "teal":       "#00FFD4",
    "indigo":     "#4400FF",
    "violet":     "#2A0845",
    "cobalt":     "#0D1B4B",
    "panel_user": "#0A0E14",
    "panel_ai":   "#060C12",
    "text_main":  "#C8E8FF",
    "text_dim":   "#3A6080",
    "green_ph":   "#00FF88",
    "red_alert":  "#CC2200",
    "gold":       "#FFB300",
    "white_hot":  "#FFFFFF",
    "star1":      "#FFFFFF",
    "star2":      "#AAD4FF",
    "star3":      "#6688AA",
    "health_on":  "#00FFD4",
    "health_off": "#CC2200",
    "amber_dim":  "#7A5500",
    "teal_dim":   "#004433",
    "coral_dim":  "#7A2800",
}

print("NOVA HYPERION SE — Initializing...")
print(f"STARDATE: {datetime.now().strftime('%Y.%j.%H%M')}")
print(f"Target API: {BASE_URL}")


# ═════════════════════════════════════════════════════════════════════════════
# NOVA HTTP CLIENT
# ═════════════════════════════════════════════════════════════════════════════
class NovaClient:
    """Thin wrapper around Nova's HTTP web API."""

    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url.rstrip('/')
        self._timeout_short = 3
        self._timeout_long  = 60

    def _get(self, path, timeout=None):
        if not REQUESTS_OK:
            return None
        try:
            r = requests.get(
                f"{self.base_url}{path}",
                verify=VERIFY_SSL,
                timeout=timeout or self._timeout_short,
            )
            return r if r.ok else None
        except Exception as e:
            return None

    def _post(self, path, json_data=None, data=None, files=None,
              headers=None, timeout=None):
        if not REQUESTS_OK:
            return None
        try:
            r = requests.post(
                f"{self.base_url}{path}",
                json=json_data,
                data=data,
                files=files,
                headers=headers,
                verify=VERIFY_SSL,
                timeout=timeout or self._timeout_short,
            )
            return r if r.ok else None
        except Exception:
            return None

    # ── Public API calls ──────────────────────────────────────────────────────

    def ping(self) -> bool:
        r = self._get("/api/ping", timeout=2)
        return r is not None

    def get_history(self):
        """Returns list of {role, content} or None on error."""
        r = self._get("/api/history", timeout=3)
        if r is None:
            return None
        try:
            return r.json()
        except Exception:
            return None

    def get_state(self) -> dict:
        r = self._get("/api/state", timeout=2)
        if r is None:
            return {}
        try:
            return r.json()
        except Exception:
            return {}

    def send_message(self, text: str) -> bool:
        r = self._post("/api/send", json_data={"message": text}, timeout=5)
        return r is not None

    def send_imagine(self, text: str) -> bool:
        r = self._post("/api/imagine", json_data={"message": text}, timeout=5)
        return r is not None

    def send_voice(self, wav_bytes: bytes) -> dict:
        """POST raw WAV bytes; returns {transcript: ...} or {error: ...}."""
        r = self._post(
            "/api/voice",
            data=wav_bytes,
            headers={"Content-Type": "audio/wav"},
            timeout=30,
        )
        if r is None:
            return {"error": "No response from server"}
        try:
            return r.json()
        except Exception:
            return {"error": "Bad JSON from /api/voice"}

    def speak(self, text: str):
        """Returns raw MP3 bytes or None."""
        r = self._post("/api/speak", json_data={"text": text}, timeout=15)
        if r is None or r.status_code == 204:
            return None
        return r.content if r.content else None

    def toggle_tts(self) -> dict:
        r = self._post("/api/tts", timeout=3)
        try:
            return r.json() if r else {}
        except Exception:
            return {}

    def clear(self) -> bool:
        r = self._post("/api/clear", timeout=5)
        return r is not None

    def upload_files(self, file_paths: list) -> dict:
        """Upload one or more local file paths; returns server JSON."""
        try:
            files_payload = []
            handles = []
            for p in file_paths:
                h = open(p, "rb")
                handles.append(h)
                files_payload.append(("files", (os.path.basename(p), h)))
            r = self._post("/api/upload", files=files_payload, timeout=30)
            for h in handles:
                h.close()
            if r is None:
                return {"error": "Upload failed"}
            return r.json()
        except Exception as e:
            return {"error": str(e)}


# ═════════════════════════════════════════════════════════════════════════════
# AUDIO ENGINE  (local chirps + TTS playback from edge_tts MP3)
# ═════════════════════════════════════════════════════════════════════════════
class AudioEngine:
    def __init__(self):
        self.sample_rate = 44100
        self.enabled     = False
        self.hum_active  = False
        self.hum_thread  = None
        self.stream      = None
        self._lock       = threading.Lock()
        self._tts_playing = False
        print("AudioEngine: Ready (chirps + edge_tts MP3 playback)")

    # ── Ambient hum ──────────────────────────────────────────────────────────
    def enable(self):
        if self.enabled:
            return
        self.enabled    = True
        self.hum_active = True
        self.hum_thread = threading.Thread(target=self._hum_loop, daemon=True)
        self.hum_thread.start()

    def disable(self):
        self.hum_active = False
        self.enabled    = False
        if self.stream:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

    def _hum_loop(self):
        t_idx = 0
        try:
            def callback(outdata, frames, time_info, status):
                nonlocal t_idx
                t     = (np.arange(frames) + t_idx) / self.sample_rate
                t_idx += frames
                base  = 0.018 * np.sin(2 * np.pi * 40  * t)
                harm  = 0.012 * np.sin(2 * np.pi * 400 * t)
                sub   = 0.008 * np.sin(2 * np.pi * 80  * t)
                mod   = 1.0 + 0.05 * np.sin(2 * np.pi * 0.25 * t)
                sig   = (base + harm + sub) * mod
                outdata[:, 0] = sig
                if outdata.shape[1] > 1:
                    outdata[:, 1] = sig

            self.stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=2,
                blocksize=1024,
                callback=callback,
                dtype="float32",
            )
            self.stream.start()
            while self.hum_active:
                time.sleep(0.1)
            self.stream.stop()
            self.stream.close()
        except Exception as e:
            print(f"AudioEngine: Hum error — {e}")

    # ── Chirps ───────────────────────────────────────────────────────────────
    def chirp(self, freq=880, duration=0.06, vol=0.12):
        if not self.enabled:
            return
        def _play():
            try:
                t   = np.linspace(0, duration, int(self.sample_rate * duration), endpoint=False)
                env = np.exp(-t / (duration * 0.4))
                wav = (vol * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)
                sd.play(wav, self.sample_rate)
            except Exception as e:
                print(f"AudioEngine: Chirp error — {e}")
        threading.Thread(target=_play, daemon=True).start()

    def alert_chirp(self):
        self.chirp(freq=1200, duration=0.08, vol=0.15)
        threading.Timer(0.12, lambda: self.chirp(freq=900, duration=0.08, vol=0.12)).start()

    def send_chirp(self):
        self.chirp(freq=660, duration=0.05, vol=0.10)
        threading.Timer(0.07, lambda: self.chirp(freq=1100, duration=0.07, vol=0.12)).start()

    def upload_chirp(self):
        self.chirp(freq=550, duration=0.04, vol=0.09)
        threading.Timer(0.06,  lambda: self.chirp(freq=770,  duration=0.04, vol=0.09)).start()
        threading.Timer(0.12,  lambda: self.chirp(freq=1050, duration=0.06, vol=0.11)).start()

    def response_chirp(self):
        """Three-tone descending: Nova finished responding."""
        self.chirp(freq=1100, duration=0.06, vol=0.11)
        threading.Timer(0.09,  lambda: self.chirp(freq=880, duration=0.06, vol=0.10)).start()
        threading.Timer(0.18,  lambda: self.chirp(freq=660, duration=0.09, vol=0.12)).start()

    # ── TTS MP3 playback ─────────────────────────────────────────────────────
    def play_mp3_bytes(self, mp3_bytes: bytes):
        """Decode edge_tts MP3 response and play via sounddevice."""
        if not PYDUB_OK:
            print("AudioEngine: pydub not available — skipping TTS playback")
            return
        def _decode_play():
            try:
                self._tts_playing = True
                seg = AudioSegment.from_file(io.BytesIO(mp3_bytes), format="mp3")
                seg = seg.set_frame_rate(44100).set_channels(2)
                samples = np.array(seg.get_array_of_samples(), dtype=np.float32) / 32768.0
                samples = samples.reshape(-1, 2)
                sd.play(samples, 44100)
                sd.wait()
            except Exception as e:
                print(f"AudioEngine: TTS playback error — {e}")
            finally:
                self._tts_playing = False
        threading.Thread(target=_decode_play, daemon=True).start()

    def stop_tts(self):
        if self._tts_playing:
            try:
                sd.stop()
            except Exception:
                pass
            self._tts_playing = False


# ═════════════════════════════════════════════════════════════════════════════
# STAR FIELD
# ═════════════════════════════════════════════════════════════════════════════
class StarField:
    def __init__(self, canvas, width, height):
        self.canvas = canvas
        self.width  = width
        self.height = height
        self.layers = []
        self.shooting_stars = []
        self.nebulae = []
        self._build_stars()
        self._build_nebulae()
        self.offset_x  = [0.0, 0.0, 0.0]
        self.offset_y  = [0.0, 0.0, 0.0]
        self.target_ox = [0.0, 0.0, 0.0]
        self.target_oy = [0.0, 0.0, 0.0]
        self.parallax_factors = [0.008, 0.018, 0.032]
        self.star_ids  = [[], [], []]
        self.nebula_ids = []
        self.shoot_timer = 0
        self._draw_nebulae()
        self._draw_stars()

    def _build_stars(self):
        counts = [120, 80, 40]
        colors = [C["star3"], C["star2"], C["star1"]]
        sizes  = [(1, 1), (1, 2), (1, 3)]
        for i in range(3):
            layer = []
            for _ in range(counts[i]):
                x     = random.uniform(0, self.width)
                y     = random.uniform(0, self.height)
                r     = random.uniform(*sizes[i])
                layer.append({
                    "x": x, "y": y, "r": r, "color": colors[i],
                    "twinkle":       random.uniform(0, math.pi * 2),
                    "twinkle_speed": random.uniform(0.02, 0.08),
                })
            self.layers.append(layer)

    def _build_nebulae(self):
        for _ in range(3):
            self.nebulae.append({
                "x": random.choice([
                    random.uniform(0, self.width * 0.25),
                    random.uniform(self.width * 0.75, self.width),
                ]),
                "y": random.choice([
                    random.uniform(0, self.height * 0.25),
                    random.uniform(self.height * 0.75, self.height),
                ]),
                "r":     random.uniform(80, 160),
                "color": random.choice(["#2A0845", "#0D1B4B", "#1A0535"]),
            })

    def _draw_nebulae(self):
        for neb in self.nebulae:
            for step in range(8, 0, -1):
                r  = int(neb["r"] * step / 8)
                oid = self.canvas.create_oval(
                    neb["x"] - r, neb["y"] - r,
                    neb["x"] + r, neb["y"] + r,
                    fill=neb["color"], outline="", stipple="gray12",
                )
                self.nebula_ids.append(oid)

    def _draw_stars(self):
        for i, layer in enumerate(self.layers):
            for star in layer:
                x, y, r = star["x"], star["y"], star["r"]
                sid = self.canvas.create_oval(
                    x - r, y - r, x + r, y + r,
                    fill=star["color"], outline="",
                )
                self.star_ids[i].append(sid)

    def on_mouse_move(self, mx, my):
        cx, cy = self.width / 2, self.height / 2
        dx = (mx - cx) / cx
        dy = (my - cy) / cy
        for i in range(3):
            self.target_ox[i] = dx * self.parallax_factors[i] * self.width
            self.target_oy[i] = dy * self.parallax_factors[i] * self.height

    def update(self):
        for i in range(3):
            self.offset_x[i] += (self.target_ox[i] - self.offset_x[i]) * 0.05
            self.offset_y[i] += (self.target_oy[i] - self.offset_y[i]) * 0.05

        for i, layer in enumerate(self.layers):
            for j, star in enumerate(layer):
                star["twinkle"] += star["twinkle_speed"]
                brightness = 0.5 + 0.5 * math.sin(star["twinkle"])
                x = star["x"] + self.offset_x[i]
                y = star["y"] + self.offset_y[i]
                r = star["r"] * (0.7 + 0.3 * brightness)
                self.canvas.coords(self.star_ids[i][j], x - r, y - r, x + r, y + r)

        self.shoot_timer += 1
        if self.shoot_timer > random.randint(180, 400):
            self.shoot_timer = 0
            self._spawn_shooting_star()

        dead = []
        for ss in self.shooting_stars:
            ss["progress"] += ss["speed"]
            if ss["progress"] >= 1.0:
                for sid in ss["ids"]:
                    try:
                        self.canvas.delete(sid)
                    except Exception:
                        pass
                dead.append(ss)
            else:
                for k, sid in enumerate(ss["ids"]):
                    frac = ss["progress"] - k * 0.04
                    if frac < 0:
                        self.canvas.itemconfig(sid, state="hidden")
                        continue
                    self.canvas.itemconfig(sid, state="normal")
                    x = ss["x0"] + frac * ss["dx"]
                    y = ss["y0"] + frac * ss["dy"]
                    r = max(0.5, 2.0 - k * 0.3)
                    self.canvas.coords(sid, x - r, y - r, x + r, y + r)
        for ss in dead:
            self.shooting_stars.remove(ss)

    def _spawn_shooting_star(self):
        x0     = random.uniform(0, self.width * 0.6)
        y0     = random.uniform(0, self.height * 0.4)
        length = random.uniform(200, 400)
        angle  = random.uniform(20, 50)
        rad    = math.radians(angle)
        dx, dy = length * math.cos(rad), length * math.sin(rad)
        ids = [
            self.canvas.create_oval(x0, y0, x0 + 2, y0 + 2, fill="#CCEEFF", outline="")
            for _ in range(8)
        ]
        self.shooting_stars.append({
            "x0": x0, "y0": y0, "dx": dx, "dy": dy,
            "ids": ids, "progress": 0.0,
            "speed": random.uniform(0.012, 0.025),
        })


# ═════════════════════════════════════════════════════════════════════════════
# UI COMPONENTS  (unchanged from original — layout / visual only)
# ═════════════════════════════════════════════════════════════════════════════
class MessageBubble(tk.Frame):
    def __init__(self, parent, role, text, **kwargs):
        super().__init__(parent, bg=C["void"], **kwargs)
        self.role      = role
        self.full_text = text
        self._build()

    def _build(self):
        is_user      = self.role == "user"
        border_color = C["amber"] if is_user else C["teal"]
        bg_color     = C["panel_user"] if is_user else C["panel_ai"]
        anchor_side = tk.RIGHT if is_user else tk.LEFT
        label_text   = "CREW MEMBER" if is_user else "NOVA HYPERION CORE"
        label_color  = C["amber"] if is_user else C["teal"]

        outer = tk.Frame(self, bg=border_color, padx=2, pady=2)
        outer.pack(side=anchor_side, padx=12, pady=4,
                   fill=tk.X if not is_user else tk.NONE)

        inner = tk.Frame(outer, bg=bg_color, padx=10, pady=8)
        inner.pack(fill=tk.BOTH, expand=True)

        tk.Label(inner, text=label_text, font=("Courier", 8, "bold"),
                 fg=label_color, bg=bg_color, anchor="w").pack(fill=tk.X)
        tk.Frame(inner, bg=border_color, height=1).pack(fill=tk.X, pady=(2, 4))

        self.text_var = tk.StringVar(value="")
        self.text_lbl = tk.Label(
            inner, textvariable=self.text_var,
            font=("Courier", 11), fg=C["text_main"], bg=bg_color,
            wraplength=520, justify=tk.LEFT, anchor="w",
        )
        self.text_lbl.pack(fill=tk.X)

        ts = datetime.now().strftime("%H:%M:%S")
        tk.Label(
            inner,
            text=f"STARDATE {datetime.now().strftime('%Y.%j')} · {ts}",
            font=("Courier", 7), fg=C["text_dim"], bg=bg_color, anchor="e",
        ).pack(fill=tk.X)

        if self.role == "assistant":
            self._reveal_text()
        else:
            self.text_var.set(self.full_text)

    def _reveal_text(self):
        self._reveal_idx   = 0
        self._reveal_delay = int(1000 / 22)
        self._do_reveal()

    def _do_reveal(self):
        if self._reveal_idx <= len(self.full_text):
            shown  = self.full_text[: self._reveal_idx]
            cursor = "█" if (self._reveal_idx % 6 < 3) else " "
            self.text_var.set(shown + cursor)
            self._reveal_idx += 1
            self.after(self._reveal_delay, self._do_reveal)
        else:
            self.text_var.set(self.full_text)


class WarpCoreIndicator(tk.Frame):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=C["void"], **kwargs)
        self.bar_colors = [C["amber"], C["coral"], C["teal"], C["indigo"], C["amber"],
                           C["coral"], C["teal"]]
        self.phase = 0
        self._build()
        self._animate()

    def _build(self):
        container = tk.Frame(self, bg=C["void"])
        container.pack(pady=4)

        self.label_var = tk.StringVar(value="NEURAL SYNTHESIS IN PROGRESS")
        tk.Label(container, textvariable=self.label_var,
                 font=("Courier", 8, "bold"), fg=C["teal"], bg=C["void"]).pack()

        bar_frame = tk.Frame(container, bg=C["void"])
        bar_frame.pack(pady=2)

        self.bar_canvases = []
        for _ in range(7):
            c = tk.Canvas(bar_frame, width=8, height=30,
                          bg=C["void"], highlightthickness=0)
            c.pack(side=tk.LEFT, padx=2)
            self.bar_canvases.append(c)

        self.dode_canvas = tk.Canvas(container, width=30, height=30,
                                     bg=C["void"], highlightthickness=0)
        self.dode_canvas.pack()
        self.dode_angle = 0.0

    def _animate(self):
        self.phase += 0.3
        heights = [int(8 + 18 * abs(math.sin(self.phase + i * 0.9))) for i in range(7)]
        for i, (c, h) in enumerate(zip(self.bar_canvases, heights)):
            c.delete("all")
            color = self.bar_colors[(i + int(self.phase / 0.5)) % len(self.bar_colors)]
            y0 = 30 - h
            c.create_rectangle(1, y0, 7, 30, fill=color,   outline="")
            c.create_rectangle(3, y0 + 2, 5, 30, fill="#FFFFFF", outline="")

        self.dode_angle += 3.0
        self.dode_canvas.delete("all")
        cx, cy, r = 15, 15, 10
        angle_rad = math.radians(self.dode_angle)
        pts = [(cx + r * math.cos(angle_rad + k * math.pi / 3),
                cy + r * 0.5 * math.sin(angle_rad + k * math.pi / 3))
               for k in range(6)]
        for k in range(6):
            x1, y1 = pts[k]
            x2, y2 = pts[(k + 1) % 6]
            self.dode_canvas.create_line(x1, y1, x2, y2, fill=C["teal"], width=1)
        for a, b in [(0, 3), (1, 4), (2, 5)]:
            self.dode_canvas.create_line(
                pts[a][0], pts[a][1], pts[b][0], pts[b][1], fill=C["teal"], width=1)

        if random.random() < 0.15:
            self.label_var.set(
                "NEURAL SYNTHESIS IN PROGRESS" if random.random() > 0.5
                else "N E U R A L  S Y N T H E S I S . . ."
            )
        self.after(80, self._animate)


class HealthConduit(tk.Canvas):
    def __init__(self, parent, **kwargs):
        super().__init__(parent, width=80, height=16,
                         bg=C["void"], highlightthickness=0, **kwargs)
        self.status      = "online"
        self.phase       = 0.0
        self.dash_offset = 0
        self._animate()

    def set_status(self, status):
        self.status = status

    def _animate(self):
        self.delete("all")
        self.phase       += 0.08
        self.dash_offset  = (self.dash_offset + 1) % 20

        if self.status == "online":
            for y in [5, 11]:
                self.create_line(0, y, 80, y, fill=C["teal_dim"], width=1)
            for x in range(-20 + self.dash_offset, 80, 20):
                self.create_line(x, 5,  x + 10, 5,  fill=C["teal"], width=2)
                self.create_line(x, 11, x + 10, 11, fill=C["teal"], width=2)
            r = 3 + int(2 * abs(math.sin(self.phase)))
            self.create_oval(70 - r, 8 - r, 70 + r, 8 + r,
                             fill=C["teal"], outline=C["health_on"])

        elif self.status == "processing":
            intensity = abs(math.sin(self.phase * 0.5))
            for y in [5, 11]:
                self.create_line(0, y, 80, y, fill=C["amber_dim"], width=1)
            seg_x = int(80 * intensity)
            self.create_line(0, 5,  seg_x, 5,  fill=C["amber"], width=2)
            self.create_line(0, 11, seg_x, 11, fill=C["amber"], width=2)

        else:
            for i in range(4):
                x = i * 20
                self.create_line(x, 5,  x + 12, 5,  fill=C["red_alert"], width=2)
                self.create_line(x, 11, x + 12, 11, fill=C["red_alert"], width=2)

        self.after(50, self._animate)


class LCARSDivider(tk.Canvas):
    def __init__(self, parent, width, **kwargs):
        super().__init__(parent, width=width, height=40,
                         bg=C["void"], highlightthickness=0, **kwargs)
        self._draw(width)

    def _draw(self, w):
        self.create_oval(0, 5, 30, 35, fill=C["coral"], outline="")
        self.create_rectangle(30, 12, w - 30, 28, fill=C["amber"], outline="")
        for i in range(3):
            x = w // 2 - 30 + i * 25
            self.create_rectangle(x, 8, x + 18, 32, fill=C["teal"], outline="")
        self.create_oval(w - 30, 5, w, 35, fill=C["coral"], outline="")
        self.create_line(30, 20, w - 30, 20, fill=C["void"], width=2)


# ═════════════════════════════════════════════════════════════════════════════
# STATUS BAR  — live online/offline + model + token display
# ═════════════════════════════════════════════════════════════════════════════
class StatusBar(tk.Frame):
    def __init__(self, parent, audio, client, **kwargs):
        super().__init__(parent, bg=C["void"], **kwargs)
        self.audio  = audio
        self.client = client
        self.muted  = False
        self.waveform_phase = 0.0
        self._model_str = "NOVA-HYPERION"
        self._build()
        self._animate_waveform()
        self._animate_plasma()

    def _pill(self, parent, text, bg, fg, width=None):
        f   = tk.Frame(parent, bg=bg, padx=8, pady=3)
        f.pack(side=tk.LEFT, padx=4)
        kw  = {}
        if width:
            kw["width"] = width
        lbl = tk.Label(f, text=text, font=("Courier", 8, "bold"), fg=fg, bg=bg, **kw)
        lbl.pack()
        return f, lbl

    def _build(self):
        # Online egg pill
        online_frame = tk.Frame(self, bg=C["teal_dim"], padx=6, pady=3)
        online_frame.pack(side=tk.LEFT, padx=4)
        self.plasma_canvas = tk.Canvas(online_frame, width=16, height=16,
                                       bg=C["teal_dim"], highlightthickness=0)
        self.plasma_canvas.pack(side=tk.LEFT)
        self.conn_lbl = tk.Label(online_frame, text="CONNECTING…",
                                 font=("Courier", 8, "bold"),
                                 fg=C["teal"], bg=C["teal_dim"])
        self.conn_lbl.pack(side=tk.LEFT, padx=4)

        # Health conduit
        self.health = HealthConduit(self)
        self.health.pack(side=tk.LEFT, padx=8)

        # Stardate pill
        _, self.stardate_lbl = self._pill(self, "", C["amber_dim"], C["amber"])
        self._update_stardate()

        # Model + tokens pill
        _, self.model_lbl = self._pill(self, self._model_str, C["cobalt"], C["star2"])

        # Tokens pill
        _, self.token_lbl = self._pill(self, "TOK: ---", C["violet"], C["teal"])

        # Spacer
        tk.Frame(self, bg=C["void"]).pack(side=tk.LEFT, expand=True, fill=tk.X)

        # TTS waveform toggle
        self.tts_frame = tk.Frame(self, bg=C["teal_dim"], padx=6, pady=3)
        self.tts_frame.pack(side=tk.RIGHT, padx=4)
        self.tts_canvas = tk.Canvas(self.tts_frame, width=50, height=16,
                                    bg=C["teal_dim"], highlightthickness=0)
        self.tts_canvas.pack(side=tk.LEFT)
        self.tts_btn = tk.Button(
            self.tts_frame, text="AUDIO",
            font=("Courier", 8, "bold"),
            fg=C["teal"], bg=C["teal_dim"],
            relief=tk.FLAT, cursor="hand2",
            command=self._toggle_audio,
        )
        self.tts_btn.pack(side=tk.LEFT, padx=4)




    def set_online(self, online: bool):
        color = C["teal"] if online else C["red_alert"]
        text  = "ONLINE" if online else "OFFLINE"
        self.conn_lbl.config(text=text, fg=color)

    def set_model(self, model: str):
        short = model.split("/")[-1].upper()[:20]
        self.model_lbl.config(text=short)

    def set_tokens(self, text: str):
        self.token_lbl.config(text=f"TOK: {text}")

    def _update_stardate(self):
        self.stardate_lbl.config(text=f"STARDATE {datetime.now().strftime('%Y.%j.%H%M')}")
        self.after(60000, self._update_stardate)

    def _animate_plasma(self):
        self.plasma_canvas.delete("all")
        t = time.time()
        for ring in range(4, 0, -1):
            spread = ring * 3 + int(2 * math.sin(t * 2.6 + ring))
            r = 6 + spread
            self.plasma_canvas.create_oval(8 - r, 8 - r, 8 + r, 8 + r,
                                           outline=C["teal"], width=1)
        self.plasma_canvas.create_oval(2, 2, 14, 14,
                                       fill="#880000", outline=C["red_alert"])
        self.plasma_canvas.create_oval(4, 3, 8, 7, fill="#FFAAAA", outline="")
        self.after(40, self._animate_plasma)

    def _animate_waveform(self):
        self.tts_canvas.delete("all")
        self.waveform_phase += 0.2
        if not self.muted:
            for i in range(5):
                h = int(4 + 12 * abs(math.sin(self.waveform_phase + i * 0.7)))
                x = 5 + i * 9
                y0 = 16 - h
                self.tts_canvas.create_line(x, 16, x, y0 + h // 2,
                                            fill=C["amber"], width=3)
                self.tts_canvas.create_line(x, y0 + h // 2, x, y0,
                                            fill=C["teal"], width=3)
        else:
            for i in range(5):
                x = 5 + i * 9
                self.tts_canvas.create_line(x, 14, x, 16, fill=C["red_alert"], width=3)
        self.after(80, self._animate_waveform)

    def _toggle_audio(self):
        self.muted = not self.muted
        if self.muted:
            self.audio.disable()
            self.tts_btn.config(text="MUTED", fg=C["red_alert"])
            # Also mute server-side TTS
            threading.Thread(
                target=lambda: self.client.toggle_tts(), daemon=True
            ).start()
        else:
            self.audio.enable()
            self.tts_btn.config(text="AUDIO", fg=C["teal"])
            threading.Thread(
                target=lambda: self.client.toggle_tts(), daemon=True
            ).start()
        self.audio.chirp(freq=440, duration=0.05)


# ═════════════════════════════════════════════════════════════════════════════
# INPUT CONSOLE  — voice recording wired
# ═════════════════════════════════════════════════════════════════════════════
class InputConsole(tk.Frame):
    def __init__(self, parent, on_send, on_imagine, on_voice_toggle,
                 on_upload, audio, **kwargs):
        super().__init__(parent, bg=C["void"], **kwargs)
        self.on_send         = on_send
        self.on_imagine      = on_imagine
        self.on_voice_toggle = on_voice_toggle
        self.on_upload       = on_upload
        self.audio           = audio
        self._has_placeholder = True
        self._placeholder = "TRANSMIT NEURAL QUERY TO NOVA..."
        self._build()

    def _build(self):
        # Text area
        text_frame = tk.Frame(self, bg=C["teal_dim"], padx=2, pady=2)
        text_frame.pack(fill=tk.X, padx=8, pady=4)

        self.text_area = tk.Text(
            text_frame, height=3, font=("Courier", 12),
            fg=C["green_ph"], bg="#010A06",
            insertbackground=C["teal"],
            relief=tk.FLAT, padx=10, pady=8, wrap=tk.WORD,
        )
        self.text_area.pack(fill=tk.X)
        self._show_placeholder()
        self.text_area.bind("<FocusIn>",   self._on_focus_in)
        self.text_area.bind("<FocusOut>",  self._on_focus_out)
        self.text_area.bind("<Return>",    self._on_enter)

        # Button row
        btn_row = tk.Frame(self, bg=C["void"])
        btn_row.pack(fill=tk.X, padx=8, pady=(0, 4))

        # Voice button
        self.voice_btn = tk.Button(
            btn_row, text="[ VOICE ]",
            font=("Courier", 10, "bold"),
            fg=C["teal"], bg=C["teal_dim"],
            relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
            command=self._voice_click,
        )
        self.voice_btn.pack(side=tk.LEFT, padx=4)

        # Upload button
        self.upload_btn = tk.Button(
            btn_row, text="[ CARGO BAY ]",
            font=("Courier", 10, "bold"),
            fg=C["amber"], bg=C["amber_dim"],
            relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
            command=self._upload_click,
        )
        self.upload_btn.pack(side=tk.LEFT, padx=4)

        # Imagine button (Aesthetic mode)
        self.imagine_btn = tk.Button(
            btn_row, text="[ AESTHETIC ]",
            font=("Courier", 10, "bold"),
            fg="#CCAAFF", bg=C["violet"],
            relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
            command=self._imagine_click,
        )
        self.imagine_btn.pack(side=tk.LEFT, padx=4)

        self.hum_btn = tk.Button(
            btn_row, text="[ HUM ON ]",
            font=("Courier", 10, "bold"),
            fg=C["amber"], bg=C["amber_dim"],
            relief=tk.FLAT, padx=12, pady=6, cursor="hand2",
            command=self._hum_click,
        )
        self.hum_btn.pack(side=tk.LEFT, padx=4)

        tk.Frame(btn_row, bg=C["void"]).pack(side=tk.LEFT, expand=True, fill=tk.X)

        # TRANSMIT button
        self.send_btn = tk.Button(
            btn_row, text="[ TRANSMIT ]",
            font=("Courier", 11, "bold"),
            fg="#FFCCAA", bg=C["red_alert"],
            relief=tk.FLAT, padx=16, pady=6, cursor="hand2",
            activebackground="#FF3300",
            command=self._send_click,
        )
        self.send_btn.pack(side=tk.RIGHT, padx=4)
        self.send_btn.bind("<Enter>", lambda e: self.send_btn.config(bg="#FF3300"))
        self.send_btn.bind("<Leave>", lambda e: self.send_btn.config(bg=C["red_alert"]))

    def _show_placeholder(self):
        self.text_area.config(fg=C["text_dim"])
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", self._placeholder)
        self._has_placeholder = True

    def _on_focus_in(self, event=None):
        if self._has_placeholder:
            self.text_area.delete("1.0", tk.END)
            self.text_area.config(fg=C["green_ph"])
            self._has_placeholder = False
        self.text_area.master.config(bg=C["teal"])

    def _on_focus_out(self, event=None):
        if not self.text_area.get("1.0", tk.END).strip():
            self._show_placeholder()
        self.text_area.master.config(bg=C["teal_dim"])

    def _on_enter(self, event):
        if not event.state & 0x1:
            self._send_click()
            return "break"

    def _send_click(self):
        if self._has_placeholder:
            return
        text = self.text_area.get("1.0", tk.END).strip()
        if not text:
            return
        self.send_btn.config(text="[ TRANSMITTING... ]")
        self.audio.send_chirp()
        self.text_area.delete("1.0", tk.END)
        self._show_placeholder()
        self.after(300, lambda: self.send_btn.config(text="[ TRANSMIT ]"))
        self.on_send(text)

    def _imagine_click(self):
        if self._has_placeholder:
            return
        text = self.text_area.get("1.0", tk.END).strip()
        if not text:
            return
        self.imagine_btn.config(text="[ TRANSMITTING... ]")
        self.audio.chirp(freq=550, duration=0.08, vol=0.12)
        self.text_area.delete("1.0", tk.END)
        self._show_placeholder()
        self.after(400, lambda: self.imagine_btn.config(text="[ AESTHETIC ]"))
        self.on_imagine(text)

    def _hum_click(self):
        if self.audio.enabled:
            self.audio.disable()
            self.hum_btn.config(text="[ HUM OFF ]", fg=C["red_alert"], bg=C["coral_dim"])
        else:
            self.audio.enable()
            self.hum_btn.config(text="[ HUM ON ]", fg=C["amber"], bg=C["amber_dim"])

    def _voice_click(self):
        self.on_voice_toggle()

    def set_voice_state(self, recording: bool):
        if recording:
            self.voice_btn.config(text="[ ● REC ]", fg=C["red_alert"],
                                  bg="#330000")
        else:
            self.voice_btn.config(text="[ VOICE ]", fg=C["teal"],
                                  bg=C["teal_dim"])

    def _upload_click(self):
        self.audio.upload_chirp()
        files = filedialog.askopenfilenames(title="CARGO BAY — SELECT FILES")
        if files:
            self.on_upload(list(files))

    def insert_text(self, text: str):
        """Insert transcribed voice text into the input field."""
        self.text_area.delete("1.0", tk.END)
        self.text_area.insert("1.0", text)
        self.text_area.config(fg=C["green_ph"])
        self._has_placeholder = False


# ═════════════════════════════════════════════════════════════════════════════
# WELCOME SCREEN
# ═════════════════════════════════════════════════════════════════════════════
class WelcomeScreen(tk.Frame):
    def __init__(self, parent, on_dismiss, **kwargs):
        super().__init__(parent, bg=C["void"], **kwargs)
        self.on_dismiss = on_dismiss
        self._build()

    def _build(self):
        plaque_outer = tk.Frame(self, bg=C["amber"], padx=3, pady=3)
        plaque_outer.pack(pady=30)
        plaque_inner = tk.Frame(plaque_outer, bg="#1A1200", padx=30, pady=20)
        plaque_inner.pack()

        tk.Label(plaque_inner, text="U . S . S .  N O V A",
                 font=("Courier", 18, "bold"), fg=C["amber"], bg="#1A1200").pack()
        tk.Label(plaque_inner, text="NCC-74657 — INTREPID CLASS",
                 font=("Courier", 10), fg=C["coral"], bg="#1A1200").pack(pady=(0, 8))
        tk.Frame(plaque_inner, bg=C["amber"], height=1).pack(fill=tk.X)
        tk.Label(plaque_inner, text="NOVA HYPERION — SPECIAL EDITION",
                 font=("Courier", 9), fg=C["teal"], bg="#1A1200").pack(pady=(8, 0))
        tk.Label(plaque_inner,
                 text=f"STARDATE {datetime.now().strftime('%Y.%j')}",
                 font=("Courier", 8), fg=C["text_dim"], bg="#1A1200").pack()

        tk.Label(self, text="— SELECT HOLODECK PROGRAM —",
                 font=("Courier", 9), fg=C["text_dim"], bg=C["void"]).pack(pady=(10, 4))

        chips_frame = tk.Frame(self, bg=C["void"])
        chips_frame.pack()
        for text, color in [
            ("STELLAR CARTOGRAPHY", C["teal"]),
            ("WARP CORE ANALYSIS",  C["amber"]),
            ("TACTICAL ASSESSMENT", C["coral"]),
            ("NOVA SELF-EVOLVE",    C["indigo"]),
        ]:
            chip = tk.Frame(chips_frame, bg=color, padx=2, pady=2)
            chip.pack(side=tk.LEFT, padx=6)
            inner = tk.Frame(chip, bg="#0A0A14", padx=10, pady=6)
            inner.pack()
            tk.Label(inner, text=text, font=("Courier", 9, "bold"),
                     fg=color, bg="#0A0A14", cursor="hand2").pack()

        tk.Button(
            self, text="[ ENTER BRIDGE ]",
            font=("Courier", 12, "bold"), fg=C["void"], bg=C["teal"],
            relief=tk.FLAT, padx=20, pady=10, cursor="hand2",
            command=self._dismiss,
        ).pack(pady=20)

    def _dismiss(self):
        self.destroy()
        self.on_dismiss()


# ═════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═════════════════════════════════════════════════════════════════════════════
class NovaHyperionTerminal:
    def __init__(self):
        self.root   = tk.Tk()
        self.root.title("NOVA HYPERION — SPECIAL EDITION")
        self.root.configure(bg=C["void"])
        self.root.geometry("900x700")
        self.root.minsize(700, 500)

        self.client = NovaClient(BASE_URL)
        self.audio  = AudioEngine()

        # State
        self.messages         = []
        self.typing_indicator = None
        self.glow_phase       = 0.0
        self.shimmer_x        = -200
        self._is_thinking     = False
        self._last_hist_len   = 0
        self._last_hist_tail  = ""
        self._tts_enabled     = True

        # Voice recording state
        self._voice_recording  = False
        self._voice_frames     = []
        self._voice_thread     = None

        self._build_ui()
        self._start_animations()
        self._show_welcome()

        print("NovaHyperionTerminal SE: UI constructed")

    # ── Build UI ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = self.root

        # Header / logotype
        header_frame = tk.Frame(root, bg=C["void"], pady=6)
        header_frame.pack(fill=tk.X, padx=12, pady=(8, 0))
        self.logo_canvas = tk.Canvas(header_frame, height=50,
                                     bg=C["void"], highlightthickness=0)
        self.logo_canvas.pack(fill=tk.X)
        self._draw_logo()

        # Status bar
        self.status_bar = StatusBar(root, self.audio, self.client)
        self.status_bar.pack(fill=tk.X, padx=12, pady=2)

        # Main border frame
        border_frame = tk.Frame(root, bg=C["void"])
        border_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Starfield canvas (background layer)
        self.bg_canvas = tk.Canvas(border_frame, bg=C["void"], highlightthickness=0)
        self.bg_canvas.place(x=0, y=0, relwidth=1.0, relheight=1.0)

        # Content on top
        content_frame = tk.Frame(border_frame, bg=C["void"])
        content_frame.place(x=0, y=0, relwidth=1.0, relheight=1.0)

        # Chat scroll area
        chat_outer = tk.Frame(content_frame, bg=C["void"])
        chat_outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        self.chat_canvas = tk.Canvas(chat_outer, bg=C["void"], highlightthickness=0)
        scrollbar = tk.Scrollbar(chat_outer, orient=tk.VERTICAL,
                                 command=self.chat_canvas.yview,
                                 bg=C["void"], troughcolor=C["void"],
                                 activebackground=C["teal"])
        self.chat_canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.chat_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.chat_frame  = tk.Frame(self.chat_canvas, bg=C["void"])
        self.chat_window = self.chat_canvas.create_window(
            (0, 0), window=self.chat_frame, anchor="nw")
        self.chat_frame.bind("<Configure>", self._on_chat_configure)
        self.chat_canvas.bind("<Configure>", self._on_canvas_configure)
        self.chat_canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # LCARS divider
        self.divider = LCARSDivider(content_frame, width=860)
        self.divider.pack(fill=tk.X, padx=8)

        # Input console  — wired to our handlers
        self.input_console = InputConsole(
            content_frame,
            on_send         = self._on_send,
            on_imagine      = self._on_imagine,
            on_voice_toggle = self._on_voice_toggle,
            on_upload       = self._on_upload,
            audio           = self.audio,
        )
        self.input_console.pack(fill=tk.X, padx=8, pady=4)

        root.bind("<Motion>", self._on_mouse_move)
        root.after(200, self._init_starfield)

    # ── Logo drawing ──────────────────────────────────────────────────────────
    def _draw_logo(self):
        self.logo_canvas.delete("all")
        w    = self.logo_canvas.winfo_width() or 860
        text = "N O V A   H Y P E R I O N   —   S P E C I A L   E D I T I O N"
        for offset, color in [(12, "#7A2800"), (4, "#AA5500"), (0, C["amber"])]:
            self.logo_canvas.create_text(
                w // 2, 25 + offset // 3,
                text=text, font=("Courier", 18, "bold"),
                fill=color, anchor="center",
            )
        sx = self.shimmer_x
        if 0 <= sx <= w:
            self.logo_canvas.create_rectangle(
                sx - 30, 0, sx + 30, 50,
                fill="#FFFFFF", outline="", stipple="gray25",
            )

    # ── Starfield ─────────────────────────────────────────────────────────────
    def _init_starfield(self):
        w = self.bg_canvas.winfo_width()
        h = self.bg_canvas.winfo_height()
        if w < 10 or h < 10:
            self.root.after(200, self._init_starfield)
            return
        self.starfield = StarField(self.bg_canvas, w, h)
        print(f"StarField: {w}x{h} initialized")

    # ── Chat scroll helpers ───────────────────────────────────────────────────
    def _on_chat_configure(self, event):
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.chat_canvas.itemconfig(self.chat_window, width=event.width)

    def _on_mousewheel(self, event):
        self.chat_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mouse_move(self, event):
        if hasattr(self, "starfield"):
            self.starfield.on_mouse_move(event.x_root, event.y_root)

    # ── Welcome + greeting ────────────────────────────────────────────────────
    def _show_welcome(self):
        self.welcome_overlay = tk.Toplevel(self.root)
        self.welcome_overlay.title("NOVA HYPERION SE")
        self.welcome_overlay.configure(bg=C["void"])
        self.welcome_overlay.geometry("600x500")
        self.welcome_overlay.transient(self.root)
        self.welcome_overlay.grab_set()
        ws = WelcomeScreen(self.welcome_overlay, on_dismiss=self._on_welcome_dismiss)
        ws.pack(fill=tk.BOTH, expand=True)

    def _on_welcome_dismiss(self):
        self.welcome_overlay.destroy()
        self.audio.enable()
        self.audio.chirp(freq=880, duration=0.06)
        # Start background polling loops
        self.root.after(500, self._poll_history_tick)
        self.root.after(500, self._poll_ping_tick)
        # Sync state (model name etc.)
        threading.Thread(target=self._sync_state, daemon=True).start()
        # Show greeting
        self.root.after(800, self._show_greeting)

    def _show_greeting(self):
        self._add_local_message(
            "assistant",
            "NOVA HYPERION SPECIAL EDITION ONLINE.\n"
            f"Connected to {BASE_URL}\n"
            "All neural pathways nominal. Whisper ASR ready. "
            "edge_tts standing by. How may I assist you, crew member?"
        )

    # ═════════════════════════════════════════════════════════════════════════
    # SEND / IMAGINE
    # ═════════════════════════════════════════════════════════════════════════
    def _on_send(self, text: str):
        self._add_local_message("user", text)
        self._set_thinking(True)
        self._last_hist_len += 1        # pre-increment so poll doesn't echo back user msg
        threading.Thread(target=self._do_send, args=(text,), daemon=True).start()

    def _do_send(self, text: str):
        ok = self.client.send_message(text)
        if not ok:
            self.root.after(0, lambda: self._handle_send_fail())
        # Poll loop will detect the reply when it arrives

    def _on_imagine(self, text: str):
        self._add_local_message("user", f"✨ [AESTHETIC] {text}")
        self._set_thinking(True)
        self._last_hist_len += 1
        threading.Thread(
            target=lambda: self.client.send_imagine(text), daemon=True
        ).start()

    def _handle_send_fail(self):
        self._set_thinking(False)
        self._add_local_message(
            "assistant",
            "⚠ COMMS FAILURE — Cannot reach Nova server.\n"
            f"Check that nova_web.py is running at {BASE_URL}",
        )
        self.audio.alert_chirp()

    # ═════════════════════════════════════════════════════════════════════════
    # VOICE RECORDING → /api/voice → transcript
    # ═════════════════════════════════════════════════════════════════════════
    def _on_voice_toggle(self):
        if self._voice_recording:
            self._stop_voice()
        else:
            self._start_voice()

    def _start_voice(self):
        self._voice_frames    = []
        self._voice_recording = True
        self.input_console.set_voice_state(True)
        self.audio.alert_chirp()
        self._voice_thread = threading.Thread(target=self._record_loop, daemon=True)
        self._voice_thread.start()
        print("Voice: Recording started (16 kHz mono)")

    def _record_loop(self):
        try:
            with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                                blocksize=1024) as stream:
                while self._voice_recording:
                    data, _ = stream.read(1024)
                    self._voice_frames.append(data.copy())
        except Exception as e:
            print(f"Voice: Record error — {e}")

    def _stop_voice(self):
        self._voice_recording = False
        self.input_console.set_voice_state(False)
        if self._voice_thread:
            self._voice_thread.join(timeout=2)
        if not self._voice_frames:
            return
        # Convert frames to WAV bytes
        wav_bytes = self._frames_to_wav(self._voice_frames)
        self._voice_frames = []
        print(f"Voice: Sending {len(wav_bytes)} bytes to /api/voice")
        threading.Thread(target=self._send_voice, args=(wav_bytes,), daemon=True).start()

    def _frames_to_wav(self, frames) -> bytes:
        pcm    = np.concatenate(frames, axis=0).flatten()
        pcm16  = (pcm * 32767).clip(-32768, 32767).astype(np.int16)
        buf    = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(pcm16.tobytes())
        return buf.getvalue()

    def _send_voice(self, wav_bytes: bytes):
        result = self.client.send_voice(wav_bytes)
        transcript = result.get("transcript", "").strip()
        error      = result.get("error", "")
        def _ui():
            if transcript:
                self.input_console.insert_text(transcript)
                self.audio.chirp(freq=880, duration=0.05)
                print(f"Voice: Transcript → '{transcript}'")
            elif error:
                print(f"Voice: Error — {error}")
                self.audio.alert_chirp()
        self.root.after(0, _ui)

    # ═════════════════════════════════════════════════════════════════════════
    # FILE UPLOAD → /api/upload
    # ═════════════════════════════════════════════════════════════════════════
    def _on_upload(self, file_paths: list):
        print(f"Upload: {len(file_paths)} file(s) → /api/upload")
        threading.Thread(
            target=self._do_upload, args=(file_paths,), daemon=True
        ).start()

    def _do_upload(self, file_paths: list):
        result = self.client.upload_files(file_paths)
        def _ui():
            if result.get("status") == "success":
                files = result.get("files", [])
                summary = ", ".join(f["original_name"] for f in files)
                self._add_local_message(
                    "assistant",
                    f"CARGO BAY: {len(files)} file(s) staged — {summary}\n"
                    "Add a comment then TRANSMIT to analyse.",
                )
                self.audio.upload_chirp()
                # Pre-fill message box with file attachment payload
                payload = self._build_file_payload(files)
                # Store for next send
                self._pending_file_payload = payload
            else:
                self._add_local_message(
                    "assistant",
                    f"⚠ UPLOAD FAILURE: {result.get('error', 'Unknown error')}",
                )
        self.root.after(0, _ui)
        self._pending_file_payload = None

    def _build_file_payload(self, files: list) -> str:
        p = f"I've attached {len(files)} file(s):\n\n"
        for f in files:
            p += (
                f"**File: {f['original_name']}**\n"
                f"Size: {f['size'] / 1024:.1f} KB\n"
                f"Content:\n```\n{f.get('preview', '[binary]')}\n```\n\n"
            )
        return p

    # ═════════════════════════════════════════════════════════════════════════
    # HISTORY POLLING  — detects new assistant replies
    # ═════════════════════════════════════════════════════════════════════════
    def _poll_history_tick(self):
        threading.Thread(target=self._fetch_history, daemon=True).start()
        self.root.after(POLL_MS, self._poll_history_tick)

    def _fetch_history(self):
        hist = self.client.get_history()
        if hist is None:
            return
        new_len  = len(hist)
        new_tail = hist[-1]["content"] if hist else ""

        if new_len != self._last_hist_len or new_tail != self._last_hist_tail:
            # Something changed — check if a new assistant message arrived
            prev_len = self._last_hist_len
            self._last_hist_len  = new_len
            self._last_hist_tail = new_tail

            # Find messages we haven't shown yet
            new_msgs = hist[prev_len:] if new_len > prev_len else []
            for msg in new_msgs:
                if msg["role"] == "assistant":
                    self.root.after(0, lambda m=msg: self._on_new_assistant_msg(m["content"]))
                elif msg["role"] == "user":
                    pass   # We already showed the user message locally

    def _on_new_assistant_msg(self, content: str):
        self._set_thinking(False)
        self._add_local_message("assistant", content)
        self.audio.response_chirp()

        # Fetch TTS audio from server
        if self._tts_enabled:
            threading.Thread(
                target=self._fetch_and_play_tts, args=(content,), daemon=True
            ).start()

    def _fetch_and_play_tts(self, text: str):
        mp3 = self.client.speak(text)
        if mp3:
            self.audio.play_mp3_bytes(mp3)

    # ═════════════════════════════════════════════════════════════════════════
    # PING / ONLINE STATUS
    # ═════════════════════════════════════════════════════════════════════════
    def _poll_ping_tick(self):
        threading.Thread(target=self._check_ping, daemon=True).start()
        self.root.after(PING_MS, self._poll_ping_tick)

    def _check_ping(self):
        online = self.client.ping()
        self.root.after(0, lambda: self.status_bar.set_online(online))
        if not online:
            self.root.after(0, lambda: self.status_bar.health.set_status("offline"))
        elif not self._is_thinking:
            self.root.after(0, lambda: self.status_bar.health.set_status("online"))

    def _sync_state(self):
        state = self.client.get_state()
        if state.get("model"):
            self.root.after(0, lambda: self.status_bar.set_model(state["model"]))

    # ═════════════════════════════════════════════════════════════════════════
    # THINKING STATE
    # ═════════════════════════════════════════════════════════════════════════
    def _set_thinking(self, thinking: bool):
        self._is_thinking = thinking
        if thinking:
            self.status_bar.health.set_status("processing")
            self._show_typing()
        else:
            self.status_bar.health.set_status("online")
            self._hide_typing()

    def _show_typing(self):
        if self.typing_indicator:
            return
        self.typing_indicator = WarpCoreIndicator(self.chat_frame)
        self.typing_indicator.pack(pady=4, padx=8, anchor="w")
        self.root.after(100, self._scroll_to_bottom)

    def _hide_typing(self):
        if self.typing_indicator:
            self.typing_indicator.destroy()
            self.typing_indicator = None

    # ═════════════════════════════════════════════════════════════════════════
    # LOCAL MESSAGE DISPLAY
    # ═════════════════════════════════════════════════════════════════════════
    def _add_local_message(self, role: str, text: str):
        bubble = MessageBubble(self.chat_frame, role, text)
        bubble.pack(
            fill=tk.X, pady=2,
            padx=(4 if role == "assistant" else 60,
                  4 if role == "user" else 60),
        )
        self.messages.append(bubble)
        self.root.after(100, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        self.chat_canvas.update_idletasks()
        self.chat_canvas.yview_moveto(1.0)

    # ═════════════════════════════════════════════════════════════════════════
    # ANIMATION LOOP
    # ═════════════════════════════════════════════════════════════════════════
    def _start_animations(self):
        self._animate_loop()

    def _animate_loop(self):
        self.glow_phase += 0.04
        self.shimmer_x  += 8
        if self.shimmer_x > (self.logo_canvas.winfo_width() or 860) + 200:
            self.shimmer_x = -200
        self._draw_logo()

        if hasattr(self, "starfield"):
            self.starfield.update()

        dw = self.root.winfo_width() - 32
        if dw > 100:
            self.divider.config(width=dw)

        self.root.after(33, self._animate_loop)   # ~30 fps

    # ═════════════════════════════════════════════════════════════════════════
    # RUN
    # ═════════════════════════════════════════════════════════════════════════
    def run(self):
        print("=" * 60)
        print("NOVA HYPERION TERMINAL — SPECIAL EDITION")
        print(f"API endpoint: {BASE_URL}")
        print(f"pydub (TTS):  {'YES' if PYDUB_OK else 'NO  (pip install pydub)'}")
        print(f"requests:     {'YES' if REQUESTS_OK else 'NO  (pip install requests)'}")
        print("=" * 60)
        self.root.mainloop()
        print("NovaHyperionTerminal SE: Session ended.")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("NOVA HYPERION SE — BOOT SEQUENCE")
    print(f"Python {sys.version.split()[0]}")
    print(f"API target: {BASE_URL}")
    print("=" * 60)

    if not REQUESTS_OK:
        print("CRITICAL: pip install requests")
        sys.exit(1)

    try:
        devs = sd.query_devices()
        print(f"sounddevice: {len(devs)} audio device(s)")
    except Exception as e:
        print(f"sounddevice: {e}")

    app = NovaHyperionTerminal()
    app.run()
