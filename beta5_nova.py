# ─────────────────────────────────────────────────────────────────────────────
# BETA 5 COMPUTER SYSTEM — Wired to Nova's HTTP web API
# Voice input · File upload · TTS playback · History polling
# Just plain text only. For the fancy stuff use nova_web.py
# ─────────────────────────────────────────────────────────────────────────────

import pygame
import sys
import random
import time
import threading
import math
import os
import io
import wave

import numpy as np

# ── External deps ─────────────────────────────────────────────────────────────
try:
    import requests
    requests.packages.urllib3.disable_warnings()
    REQUESTS_OK = True
except ImportError:
    REQUESTS_OK = False
    print("WARNING: pip install requests")

try:
    import sounddevice as sd
    SD_OK = True
except ImportError:
    SD_OK = False
    print("WARNING: pip install sounddevice")

try:
    from pydub import AudioSegment
    PYDUB_OK = True
except ImportError:
    PYDUB_OK = False

# ═════════════════════════════════════════════════════════════════════════════
# CONFIG
# ═════════════════════════════════════════════════════════════════════════════
BASE_URL   = "https://192.168.178.58:8080"
POLL_MS    = 1500
VERIFY_SSL = False

# ═════════════════════════════════════════════════════════════════════════════
# NOVA HTTP CLIENT
# ═════════════════════════════════════════════════════════════════════════════
class NovaClient:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url.rstrip('/')

    def _get(self, path, timeout=3):
        if not REQUESTS_OK: return None
        try:
            r = requests.get(f"{self.base_url}{path}", verify=VERIFY_SSL, timeout=timeout)
            return r if r.ok else None
        except Exception:
            return None

    def _post(self, path, json_data=None, data=None, files=None, headers=None, timeout=5):
        if not REQUESTS_OK: return None
        try:
            r = requests.post(f"{self.base_url}{path}", json=json_data, data=data,
                              files=files, headers=headers, verify=VERIFY_SSL, timeout=timeout)
            return r if r.ok else None
        except Exception:
            return None

    def ping(self):
        return self._get("/api/ping", timeout=2) is not None

    def get_history(self):
        r = self._get("/api/history", timeout=3)
        if r is None: return None
        try: return r.json()
        except: return None

    def get_state(self):
        r = self._get("/api/state", timeout=2)
        if r is None: return {}
        try: return r.json()
        except: return {}

    def send_message(self, text):
        r = self._post("/api/send", json_data={"message": text}, timeout=5)
        return r is not None

    def send_voice(self, wav_bytes):
        r = self._post("/api/voice", data=wav_bytes,
                       headers={"Content-Type": "audio/wav"}, timeout=30)
        if r is None: return {"error": "No response"}
        try: return r.json()
        except: return {"error": "Bad JSON"}

    def speak(self, text):
        r = self._post("/api/speak", json_data={"text": text}, timeout=15)
        if r is None or r.status_code == 204: return None
        return r.content if r.content else None

    def stop_speaking(self):
        self._post("/api/stop_speaking", timeout=3)

    def upload_files(self, file_paths):
        try:
            files_payload = []
            handles = []
            for p in file_paths:
                h = open(p, "rb")
                handles.append(h)
                files_payload.append(("files", (os.path.basename(p), h)))
            r = self._post("/api/upload", files=files_payload, timeout=30)
            for h in handles: h.close()
            if r is None: return {"error": "Upload failed"}
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def clear(self):
        self._post("/api/clear", timeout=5)

# ═════════════════════════════════════════════════════════════════════════════
# AUDIO ENGINE
# ═════════════════════════════════════════════════════════════════════════════
class AudioEngine:
    def __init__(self):
        self.sample_rate  = 44100
        self.enabled      = True
        self._tts_playing = False

    def chirp(self, freq=880, duration=0.06, vol=0.12):
        if not SD_OK: return
        def _play():
            t   = np.linspace(0, duration, int(self.sample_rate * duration), endpoint=False)
            env = np.exp(-t / (duration * 0.4))
            wav = (vol * env * np.sin(2 * np.pi * freq * t)).astype(np.float32)
            sd.play(wav, self.sample_rate)
        threading.Thread(target=_play, daemon=True).start()

    def beep(self):   self.chirp(freq=800, duration=0.05, vol=0.1)

    def alert(self):
        self.chirp(freq=1200, duration=0.08, vol=0.15)
        threading.Timer(0.12, lambda: self.chirp(freq=900, duration=0.08, vol=0.12)).start()

    def response_beep(self):
        self.chirp(freq=1100, duration=0.06, vol=0.11)
        threading.Timer(0.09, lambda: self.chirp(freq=880, duration=0.06, vol=0.10)).start()
        threading.Timer(0.18, lambda: self.chirp(freq=660, duration=0.09, vol=0.12)).start()

    def play_mp3_bytes(self, mp3_bytes):
        if not PYDUB_OK or not SD_OK: return
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
                print(f"TTS error: {e}")
            finally:
                self._tts_playing = False
        threading.Thread(target=_decode_play, daemon=True).start()

# ═════════════════════════════════════════════════════════════════════════════
# PYGAME SETUP
# ═════════════════════════════════════════════════════════════════════════════
pygame.init()
pygame.font.init()

WIDTH, HEIGHT = 1280, 800
FPS = 60

BLACK    = (0,   0,   0)
WHITE    = (255, 255, 255)
RED      = (255, 0,   0)
IBM_BLUE = (232, 240, 255)
CHARCOAL = (26,  26,  26)
DIM_RED  = (120, 0,   0)
GREEN    = (0,   200, 0)
YELLOW   = (255, 220, 0)

HEADER_H  = 90
DIVIDER_Y = HEADER_H + 4
STATUS_H  = 28
CHAT_TOP  = DIVIDER_Y + 14
CHAT_BOT  = HEIGHT - STATUS_H - 110
INPUT_H   = 44
INPUT_Y   = HEIGHT - STATUS_H - INPUT_H - 60
BTN_Y     = HEIGHT - STATUS_H - 50

def load_mono(size):
    for name in ["Courier New", "Courier", "DejaVu Sans Mono"]:
        try: return pygame.font.SysFont(name, size, bold=True)
        except: pass
    return pygame.font.Font(None, size)

FONT_TITLE  = load_mono(18)
FONT_SUB    = load_mono(11)
FONT_CHAT   = load_mono(13)
FONT_STATUS = load_mono(11)
FONT_BTN    = load_mono(11)
FONT_COORD  = load_mono(9)
FONT_CURSOR = load_mono(14)
RAIN_FONT   = load_mono(11)

RAIN_COLS   = 80
RAIN_CHAR_W = WIDTH // RAIN_COLS

# ─── BINARY RAIN ──────────────────────────────────────────────────────────────
class BinaryRain:
    def __init__(self):
        self.positions   = [random.randint(-HEIGHT, 0) for _ in range(RAIN_COLS)]
        self.speeds      = [random.uniform(0.4, 1.2)   for _ in range(RAIN_COLS)]
        self.flash_row   = -1
        self.flash_timer = 0
        self.next_flash  = random.randint(120, 300)
        self.frame       = 0

    def update(self):
        self.frame += 1
        for i in range(RAIN_COLS):
            self.positions[i] += self.speeds[i]
            if self.positions[i] > HEIGHT:
                self.positions[i] = random.randint(-60, 0)
                self.speeds[i] = random.uniform(0.4, 1.2)
        if self.flash_timer > 0: self.flash_timer -= 1
        else: self.flash_row = -1
        self.next_flash -= 1
        if self.next_flash <= 0:
            self.flash_row   = random.randint(0, HEIGHT // 12)
            self.flash_timer = 1
            self.next_flash  = random.randint(90, 240)

    def draw(self, surf):
        char_h = 12
        for col in range(RAIN_COLS):
            x = col * RAIN_CHAR_W
            y_start = int(self.positions[col])
            for row in range(HEIGHT // char_h + 2):
                y = y_start + row * char_h
                if y < 0 or y > HEIGHT: continue
                ch = "0" if (col + row + self.frame // 8) % 2 == 0 else "1"
                if random.random() < 0.05: ch = str(random.randint(0, 1))
                col_color = WHITE if (self.flash_row >= 0 and row == self.flash_row
                                      and self.flash_timer > 0) else CHARCOAL
                surf.blit(RAIN_FONT.render(ch, True, col_color), (x, y))

# ─── SCANNING LINE ────────────────────────────────────────────────────────────
class ScanLine:
    def __init__(self, y, x_start, x_end):
        self.y = y; self.x_start = x_start; self.x_end = x_end
        self.x = x_start; self.speed = 3.0

    def update(self):
        self.x += self.speed
        if self.x > self.x_end: self.x = self.x_start

    def draw(self, surf):
        pygame.draw.line(surf, RED, (self.x_start, self.y), (self.x_end, self.y), 1)
        x1 = max(self.x_start, int(self.x) - 40)
        x2 = min(self.x_end, int(self.x))
        if x2 > x1:
            pygame.draw.line(surf, WHITE, (x1, self.y), (x2, self.y), 1)

# ─── MESSAGE ──────────────────────────────────────────────────────────────────
class Message:
    def __init__(self, text, role):
        self.text      = text
        self.role      = role
        self.chars_shown = 0
        self.done      = False
        self.flash_timer = 0
        self.last_char_time = time.time()
        self.char_delay = 0.006

    def update(self):
        if self.done: return
        now = time.time()
        if now - self.last_char_time >= self.char_delay:
            steps = max(1, int((now - self.last_char_time) / self.char_delay))
            for _ in range(steps):
                if self.chars_shown < len(self.text):
                    self.flash_timer = 3
                    self.chars_shown += 1
                else:
                    self.done = True; break
            self.last_char_time = now
        if self.flash_timer > 0: self.flash_timer -= 1

    def get_display_text(self): return self.text[:self.chars_shown]

# ─── CHAT RENDERER ────────────────────────────────────────────────────────────
CHAT_MARGIN_L = 20; CHAT_MARGIN_R = 20
CHAT_LINE_H   = 18; BLOCK_PAD_V  = 8; BLOCK_PAD_H = 10

def wrap_text(text, font, max_w):
    words = text.split(' '); lines = []; current = ""
    for word in words:
        test = (current + " " + word).strip()
        if font.size(test)[0] <= max_w: current = test
        else:
            if current: lines.append(current)
            current = word
    if current: lines.append(current)
    return lines or [""]

def render_messages(surf, messages, scroll_y, chat_rect):
    x0    = chat_rect.left + CHAT_MARGIN_L
    max_w = chat_rect.width - CHAT_MARGIN_L - CHAT_MARGIN_R - BLOCK_PAD_H * 2 - 4
    y     = chat_rect.top - scroll_y + 8
    for msg in messages:
        lines   = wrap_text(msg.get_display_text(), FONT_CHAT, max_w)
        block_h = len(lines) * CHAT_LINE_H + BLOCK_PAD_V * 2
        if msg.role == 'user':
            rule_color = WHITE
            text_color = WHITE
            label      = "USER INPUT"
        elif msg.role == 'system':
            rule_color = YELLOW
            text_color = YELLOW
            label      = "SYSTEM"
        else:
            rule_color = RED
            text_color = IBM_BLUE
            label      = "BETA 5 OUTPUT"

        if y + block_h < chat_rect.top or y > chat_rect.bottom:
            y += block_h + 10; continue
        pygame.draw.rect(surf, BLACK,
                         pygame.Rect(x0, y,
                                     chat_rect.width - CHAT_MARGIN_L - CHAT_MARGIN_R,
                                     block_h))
        pygame.draw.line(surf, rule_color, (x0, y), (x0, y + block_h), 1)
        surf.blit(FONT_STATUS.render(label, True, rule_color), (x0 + 4, y + 2))
        for li, line in enumerate(lines):
            ty = y + BLOCK_PAD_V + li * CHAT_LINE_H + 2
            if ty < chat_rect.top or ty > chat_rect.bottom: continue
            col = WHITE if (not msg.done and li == len(lines)-1 and msg.flash_timer > 0) \
                  else text_color
            surf.blit(FONT_CHAT.render(line, True, col), (x0 + 1 + BLOCK_PAD_H, ty))
        y += block_h + 10
    return y

def total_content_height(messages, chat_rect):
    max_w = chat_rect.width - CHAT_MARGIN_L - CHAT_MARGIN_R - BLOCK_PAD_H * 2 - 4
    total = 8
    for msg in messages:
        lines   = wrap_text(msg.text, FONT_CHAT, max_w)
        total  += len(lines) * CHAT_LINE_H + BLOCK_PAD_V * 2 + 10
    return total

# ─── BUTTON ───────────────────────────────────────────────────────────────────
class Button:
    def __init__(self, rect, label, action=None, color=RED):
        self.rect    = pygame.Rect(rect)
        self.label   = label
        self.action  = action
        self.color   = color
        self.hovered = False
        self.pressed = False
        self.exec_timer  = 0
        self.blink_phase = 0

    def update(self):
        if self.exec_timer > 0:
            self.exec_timer  -= 1
            self.blink_phase  = (self.blink_phase + 1) % 30

    def draw(self, surf):
        if self.hovered or self.pressed:
            pygame.draw.rect(surf, WHITE, self.rect)
            pygame.draw.rect(surf, self.color, self.rect, 1)
            if self.exec_timer > 0:
                lbl = "EXECUTING..." if self.blink_phase < 15 else ""
                tc  = self.color
            else:
                lbl = self.label; tc = BLACK
        else:
            pygame.draw.rect(surf, BLACK, self.rect)
            pygame.draw.rect(surf, self.color, self.rect, 1)
            lbl = self.label; tc = WHITE
        if lbl:
            ts = FONT_BTN.render(lbl, True, tc)
            surf.blit(ts, (self.rect.centerx - ts.get_width()  // 2,
                           self.rect.centery - ts.get_height() // 2))

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self.hovered = self.rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self.pressed = True; self.exec_timer = 45
                if self.action: self.action()
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.pressed = False

# ─── PROCESSING INDICATOR ─────────────────────────────────────────────────────
class ProcessingIndicator:
    def __init__(self):
        self.active   = False
        self.frame    = 0
        self.progress = 0.0
        self.bar_w    = 400

    def update(self):
        if not self.active: return
        self.frame    += 1
        self.progress += 0.004
        if self.progress > 1.0: self.progress = 0.0

    def draw(self, surf, x, y):
        if not self.active: return
        pygame.draw.rect(surf, DIM_RED, pygame.Rect(x, y, self.bar_w, 6))
        pygame.draw.rect(surf, RED,     pygame.Rect(x, y, int(self.bar_w * self.progress), 6))
        cy = y + 10
        if (self.frame // 30) % 2 == 0:
            pygame.draw.rect(surf, RED, pygame.Rect(x, cy, self.bar_w, 18))
        txt = FONT_CURSOR.render("PROCESSING  *  PLEASE STAND BY", True, WHITE)
        surf.blit(txt, (x + self.bar_w + 12, cy + 2))

# ─── STATUS BAR ───────────────────────────────────────────────────────────────
class StatusBar:
    def __init__(self):
        self.cycle     = 0
        self.online    = False
        self.frame     = 0
        self.memory    = 4096
        self.model     = "UNKNOWN"
        self.recording = False

    def update(self):
        self.frame += 1
        if self.frame % 60 == 0:
            self.cycle = (self.cycle + 1) % 100000000

    def draw(self, surf, y, w):
        pygame.draw.rect(surf, BLACK, pygame.Rect(0, y, w, STATUS_H))
        pygame.draw.line(surf, RED, (0, y), (w, y), 1)
        link_col = GREEN if self.online else RED
        rec_flag = "  [REC]" if self.recording else ""
        text = (f"CORE: NOMINAL | UPLINK: {'VERIFIED' if self.online else 'OFFLINE'} | "
                f"MEM: {self.memory}K | MODEL: {self.model[:20]} | "
                f"CYCLE: {self.cycle:08d}{rec_flag}")
        parts = text.split("|")
        x = 8
        for i, part in enumerate(parts):
            col = link_col if i == 1 else (RED if self.recording and i == len(parts)-1 else WHITE)
            ts  = FONT_STATUS.render(part.strip(), True, col)
            surf.blit(ts, (x, y + (STATUS_H - ts.get_height()) // 2))
            x += ts.get_width() + 4
            if i < len(parts) - 1:
                sep = FONT_STATUS.render("|", True, RED)
                surf.blit(sep, (x, y + (STATUS_H - sep.get_height()) // 2))
                x += sep.get_width() + 4

# ─── DIVIDER / HEADER ─────────────────────────────────────────────────────────
def draw_divider(surf, y, w):
    pygame.draw.line(surf, RED, (0, y),     (w, y),     1)
    pygame.draw.line(surf, RED, (0, y + 4), (w, y + 4), 1)
    for tx in range(0, w, 80):
        pygame.draw.line(surf, WHITE, (tx, y - 2), (tx, y + 6), 1)
    cs = FONT_COORD.render("X:0440  *  SECTOR 7-G", True, WHITE)
    surf.blit(cs, (w - cs.get_width() - 6, y + 6))

def draw_header(surf, w, scan_left, scan_right):
    pygame.draw.rect(surf, BLACK, (0, 0, w, HEADER_H))
    title = "BETA 5 COMPUTER SYSTEM  --  AUTHORIZED ACCESS ONLY"
    ts = FONT_TITLE.render(title, True, WHITE)
    surf.blit(ts, (w // 2 - ts.get_width() // 2, 18))
    sub = "COMMISSIONED: STARDATE 4513.3  *  ECHELON CLEARANCE REQUIRED"
    ss  = FONT_SUB.render(sub, True, IBM_BLUE)
    surf.blit(ss, (w // 2 - ss.get_width() // 2, 44))
    scan_left.draw(surf)
    scan_right.draw(surf)

# ─── INPUT BOX ────────────────────────────────────────────────────────────────
class InputBox:
    def __init__(self, rect):
        self.rect    = pygame.Rect(rect)
        self.text    = ""
        self.active  = True
        self.cursor_visible = True
        self.cursor_timer   = 0

    def update(self):
        self.cursor_timer += 1
        if self.cursor_timer >= 30:
            self.cursor_visible = not self.cursor_visible
            self.cursor_timer   = 0

    def handle_event(self, event):
        if event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key not in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if len(self.text) < 500:
                    self.text += event.unicode
        elif event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)

    def draw(self, surf):
        pygame.draw.rect(surf, BLACK, self.rect)
        pygame.draw.rect(surf, WHITE, self.rect, 1)
        prompt = FONT_CHAT.render("> ", True, RED)
        surf.blit(prompt, (self.rect.x + 6,
                           self.rect.y + (self.rect.height - prompt.get_height()) // 2))
        ts = FONT_CHAT.render(self.text, True, WHITE)
        tx = self.rect.x + 6 + prompt.get_width()
        ty = self.rect.y + (self.rect.height - ts.get_height()) // 2
        surf.blit(ts, (tx, ty))
        if self.active and self.cursor_visible:
            pygame.draw.rect(surf, RED, (tx + ts.get_width(), ty, 8, ts.get_height()))

    def get_and_clear(self):
        t = self.text.strip(); self.text = ""; return t

    def set_text(self, text):
        self.text = text

# ═════════════════════════════════════════════════════════════════════════════
# MAIN APPLICATION
# ═════════════════════════════════════════════════════════════════════════════
def main():
    screen = pygame.display.set_mode((WIDTH, HEIGHT))
    pygame.display.set_caption("BETA 5 COMPUTER SYSTEM -- AUTHORIZED ACCESS ONLY")
    clock  = pygame.time.Clock()

    client = NovaClient(BASE_URL)
    audio  = AudioEngine()

    # State
    messages        = []
    scroll_y        = 0
    is_thinking     = False
    # Track history by index — avoids pre-increment race conditions
    shown_up_to     = 0          # index of last shown assistant message in hist
    server_hist_len = 0          # last known server history length
    online          = False
    tts_enabled     = [True]
    voice_recording = False
    voice_frames    = []
    voice_thread    = None
    pending_upload  = None

    # Components
    rain       = BinaryRain()
    scan_left  = ScanLine(y=62, x_start=0,               x_end=WIDTH // 2 - 320)
    scan_right = ScanLine(y=62, x_start=WIDTH // 2 + 320, x_end=WIDTH - 1)
    status_bar = StatusBar()
    processing = ProcessingIndicator()
    chat_rect  = pygame.Rect(0, CHAT_TOP, WIDTH, CHAT_BOT - CHAT_TOP)
    input_box  = InputBox((10, INPUT_Y, WIDTH - 20, INPUT_H))

    def add_system(text):
        m = Message(text, 'system')
        m.done = True
        messages.append(m)

    def add_user(text):
        m = Message(text.upper(), 'user')
        m.done = True
        messages.append(m)

    def add_assistant(text):
        import re
        clean = re.sub(r'\[IMAGE:[^\]]+\]',   '[IMAGE GENERATED]',   text)
        clean = re.sub(r'\[DIAGRAM:[^\]]+\]', '[DIAGRAM GENERATED]', clean)
        clean = re.sub(r'\[PLOT:[^\]]+\]',    '[PLOT GENERATED]',    clean)
        clean = re.sub(r'\[AUDIO:[^\]]+\]',   '[AUDIO GENERATED]',   clean)
        clean = re.sub(r'\[VIDEO:[^\]]+\]',   '[VIDEO GENERATED]',   clean)
        clean = re.sub(r'[*#`]', '', clean)
        messages.append(Message(clean.upper(), 'assistant'))

    add_system("BETA 5 COMPUTER SYSTEM ONLINE. CONNECTING TO NOVA INTELLIGENCE CORE. "
               "ECHELON CLEARANCE VERIFIED. ENTER QUERY OR USE VOICE INPUT.")

    # ── Voice helpers ─────────────────────────────────────────────────────────
    def frames_to_wav(frames):
        pcm   = np.concatenate(frames, axis=0).flatten()
        pcm16 = (pcm * 32767).clip(-32768, 32767).astype(np.int16)
        buf   = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1); wf.setsampwidth(2)
            wf.setframerate(16000); wf.writeframes(pcm16.tobytes())
        return buf.getvalue()

    def record_loop():
        nonlocal voice_frames
        try:
            with sd.InputStream(samplerate=16000, channels=1, dtype="float32",
                                blocksize=1024) as stream:
                while voice_recording:
                    data, _ = stream.read(1024)
                    voice_frames.append(data.copy())
        except Exception as e:
            print(f"Voice record error: {e}")

    def do_transcribe(wav_bytes):
        """Transcribe and put result in input box only — user decides when to send."""
        result = client.send_voice(wav_bytes)
        transcript = result.get("transcript", "").strip()
        if transcript:
            input_box.set_text(transcript)
            audio.beep()
            add_system(f"TRANSCRIPT READY: {transcript.upper()}")
        else:
            add_system("VOICE RECOGNITION FAILED. NO SIGNAL DETECTED.")

    # ── Send helper ───────────────────────────────────────────────────────────
    def do_send(text):
        nonlocal is_thinking, server_hist_len, shown_up_to, pending_upload
        if not text and not pending_upload: return
        payload = text
        if pending_upload:
            payload = pending_upload + ("User comment: " + text if text else "Please analyse.")
            pending_upload = None

        add_user(text or "(files attached)")
        is_thinking = True
        processing.active = True
        audio.beep()

        def _send():
            client.send_message(payload)
        threading.Thread(target=_send, daemon=True).start()

    def do_upload():
        nonlocal pending_upload
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw()
            files = filedialog.askopenfilenames(title="CARGO BAY — SELECT FILES")
            root.destroy()
            if not files: return
            audio.beep()
            add_system(f"UPLOADING {len(files)} FILE(S) TO NOVA...")

            def _up():
                nonlocal pending_upload
                result = client.upload_files(list(files))
                if result.get("status") == "success":
                    flist = result.get("files", [])
                    p = f"I've attached {len(flist)} file(s):\n\n"
                    for f in flist:
                        p += (f"**File: {f['original_name']}**\n"
                              f"Size: {f['size']/1024:.1f} KB\n"
                              f"Content:\n```\n{f.get('preview','[binary]')}\n```\n\n")
                    pending_upload = p
                    summary = ", ".join(f["original_name"] for f in flist)
                    add_system(f"FILES STAGED: {summary}. ADD COMMENT AND TRANSMIT.")
                    audio.response_beep()
                else:
                    add_system(f"UPLOAD FAILED: {result.get('error','?')}")
            threading.Thread(target=_up, daemon=True).start()
        except Exception as e:
            print(f"Upload error: {e}")

    # ── Buttons ───────────────────────────────────────────────────────────────
    BW = 118; BH = 44; GAP = 6
    btn_x = 10

    def send_action():
        text = input_box.get_and_clear()
        do_send(text)

    def voice_action():
        nonlocal voice_recording, voice_frames, voice_thread
        if not SD_OK:
            add_system("SOUNDDEVICE NOT INSTALLED. VOICE UNAVAILABLE.")
            return
        if voice_recording:
            voice_recording = False
            status_bar.recording = False
            if voice_thread: voice_thread.join(timeout=2)
            wav = frames_to_wav(voice_frames)
            voice_frames = []
            voice_btn.label = "VOICE INPUT"
            add_system("TRANSCRIBING VOICE INPUT...")
            audio.alert()
            threading.Thread(target=do_transcribe, args=(wav,), daemon=True).start()
        else:
            voice_recording = True
            voice_frames    = []
            status_bar.recording = True
            voice_btn.label = "STOP REC"
            audio.alert()
            voice_thread = threading.Thread(target=record_loop, daemon=True)
            voice_thread.start()

    def cargo_action():
        threading.Thread(target=do_upload, daemon=True).start()

    def tts_action():
        tts_enabled[0] = not tts_enabled[0]
        tts_btn.label = "TTS: ON " if tts_enabled[0] else "TTS: OFF"
        if not tts_enabled[0]:
            try: sd.stop()
            except: pass
            threading.Thread(target=client.stop_speaking, daemon=True).start()
        audio.beep()

    def clear_action():
        nonlocal shown_up_to, server_hist_len, is_thinking
        messages.clear()
        client.clear()
        shown_up_to = 0
        server_hist_len = 0
        is_thinking = False
        processing.active = False
        add_system("MEMORY CLEARED. NOVA LOGS RESET. READY.")

    voice_btn = Button((btn_x,              BTN_Y, BW, BH), "VOICE INPUT", voice_action, RED)
    cargo_btn = Button((btn_x + BW + GAP,   BTN_Y, BW, BH), "CARGO BAY",   cargo_action, YELLOW)
    tts_btn   = Button((btn_x+(BW+GAP)*2,   BTN_Y, BW, BH), "TTS: ON ",    tts_action,   GREEN)
    send_btn  = Button((WIDTH - BW - 10,    BTN_Y, BW, BH), "TRANSMIT",    send_action,  RED)
    clear_btn = Button((WIDTH - (BW+GAP)*2, BTN_Y, BW, BH), "CLEAR MEM",   clear_action, RED)

    all_buttons = [voice_btn, cargo_btn, tts_btn, send_btn, clear_btn]

    # ── History poll ──────────────────────────────────────────────────────────
    def fetch_history():
        nonlocal is_thinking, shown_up_to, server_hist_len, online
        while True:
            try:
                alive = client.ping()
                online = alive
                status_bar.online = alive

                if alive:
                    state = client.get_state()
                    if state.get("model"):
                        status_bar.model = state["model"].split("/")[-1].upper()[:20]

                hist = client.get_history()
                if hist is None:
                    time.sleep(POLL_MS / 1000); continue

                server_hist_len = len(hist)

                # Find any assistant messages we haven't shown yet
                for i in range(shown_up_to, len(hist)):
                    msg = hist[i]
                    if msg["role"] == "assistant":
                        content = msg["content"]
                        add_assistant(content)
                        is_thinking = False
                        processing.active = False
                        audio.response_beep()
                        if tts_enabled[0]:
                            def _tts(txt=content):
                                mp3 = client.speak(txt)
                                if mp3: audio.play_mp3_bytes(mp3)
                            threading.Thread(target=_tts, daemon=True).start()

                shown_up_to = len(hist)

            except Exception as e:
                print(f"Poll error: {e}")
            time.sleep(POLL_MS / 1000)

    poll_thread = threading.Thread(target=fetch_history, daemon=True)
    poll_thread.start()

    # ── Main loop ─────────────────────────────────────────────────────────────
    rain_surf = pygame.Surface((WIDTH, HEIGHT))

    running = True
    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    send_action()
                    send_btn.exec_timer = 45
                elif event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_PAGEUP:
                    scroll_y = max(0, scroll_y - 80)
                elif event.key == pygame.K_PAGEDOWN:
                    scroll_y += 80
                else:
                    input_box.handle_event(event)
            else:
                input_box.handle_event(event)
                for btn in all_buttons:
                    btn.handle_event(event)

        # Update
        rain.update()
        scan_left.update(); scan_right.update()
        status_bar.update()
        processing.update()
        input_box.update()
        for btn in all_buttons: btn.update()
        for msg in messages: msg.update()

        # Auto-scroll
        content_h = total_content_height(messages, chat_rect)
        max_scroll = max(0, content_h - chat_rect.height)
        if scroll_y >= max_scroll - 40:
            scroll_y = max_scroll

        # Draw
        screen.fill(BLACK)
        rain_surf.fill(BLACK)
        rain.draw(rain_surf)
        screen.blit(rain_surf, (0, 0))

        draw_header(screen, WIDTH, scan_left, scan_right)
        draw_divider(screen, DIVIDER_Y, WIDTH)

        overlay = pygame.Surface((chat_rect.width, chat_rect.height))
        overlay.set_alpha(210); overlay.fill(BLACK)
        screen.blit(overlay, (chat_rect.left, chat_rect.top))
        render_messages(screen, messages, scroll_y, chat_rect)

        if processing.active:
            processing.draw(screen, CHAT_MARGIN_L + 20, CHAT_BOT - 48)

        pygame.draw.line(screen, RED, (0, BTN_Y - 6), (WIDTH, BTN_Y - 6), 1)
        pygame.draw.line(screen, RED, (0, BTN_Y - 2), (WIDTH, BTN_Y - 2), 1)
        pygame.draw.line(screen, RED, (0, INPUT_Y - 4), (WIDTH, INPUT_Y - 4), 1)
        input_box.draw(screen)

        for btn in all_buttons: btn.draw(screen)

        dot_col = GREEN if online else RED
        pygame.draw.circle(screen, dot_col, (WIDTH - BW - 10 - 12, BTN_Y + BH//2), 5)

        status_bar.draw(screen, HEIGHT - STATUS_H, WIDTH)
        pygame.display.flip()

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    print("BETA 5 COMPUTER SYSTEM")
    print(f"Nova API: {BASE_URL}")
    main()
