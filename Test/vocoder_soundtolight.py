# BETA 5 COMPUTER SYSTEM — VOCODER ARRAY
# Sound-to-light avatar — Windows system audio via pyaudiowpatch WASAPI loopback
# pip install pyaudiowpatch pygame numpy

import pygame
import numpy as np
import math
import time
import sys
import threading

try:
    import pyaudiowpatch as pyaudio
except ImportError:
    print("pip install pyaudiowpatch")
    sys.exit(1)

# ─────────────────────────────────────────────
# Audio config
# ─────────────────────────────────────────────
BLOCK_SIZE   = 2048           # frames per callback
GAIN         = 14.0           # boost FFT energy to fill the grid
ATTACK       = 0.85           # column rise speed  (0–1)
DECAY        = 0.08           # column fall speed  (lower = slower)
PEAK_HOLD_S  = 0.55           # seconds to hold peak dot before dropping
SPILL        = 0.38           # energy bleed into adjacent columns (artistic smear)
IDLE_AMP     = 0.06           # dim pulse when silent

# ─────────────────────────────────────────────
# Matrix / display config
# ─────────────────────────────────────────────
COLS         = 32
ROWS         = 8
NODE_DIA     = 10
GUTTER       = 4
NODE_STEP    = NODE_DIA + GUTTER

PANEL_PAD    = 8
LABEL_H      = 18
PANEL_W      = COLS * NODE_STEP - GUTTER + PANEL_PAD * 2
PANEL_H      = ROWS * NODE_STEP - GUTTER + PANEL_PAD * 2 + LABEL_H

WIN_W        = PANEL_W + 80
WIN_H        = PANEL_H + 100
FPS          = 60

# Colours
C_DEAD       = (18,  4,   4)
C_FULL_RED   = (255, 30,  0)
C_HOT_WHITE  = (255, 240, 220)
C_ORANGE     = (255, 90,  0)
C_AMBER      = (180, 50,  0)
C_LABEL      = (255, 60,  60)
C_BORDER     = (180, 30,  30)
C_AMBER_DIM  = (120, 60,  0)
C_PEAK       = (255, 255, 180)
C_BG         = (0,   0,   0)

# ─────────────────────────────────────────────
# Shared audio state
# ─────────────────────────────────────────────
_lock      = threading.Lock()
_fft_bands = np.zeros(COLS, dtype=np.float32)


def _log_edges(block_size, n_cols, sr, lo_hz=60, hi_hz=16000):
    freqs     = np.fft.rfftfreq(block_size, 1.0 / sr)
    log_edges = np.logspace(math.log10(lo_hz), math.log10(hi_hz), n_cols + 1)
    edges = []
    for f in log_edges:
        idx = int(np.searchsorted(freqs, f))
        edges.append(max(1, min(idx, len(freqs) - 1)))
    return edges


def _make_callback(edges):
    def callback(in_data, frame_count, time_info, status):
        global _fft_bands
        pcm = np.frombuffer(in_data, dtype=np.float32)
        # stereo → mono
        if len(pcm) == frame_count * 2:
            pcm = pcm.reshape(-1, 2).mean(axis=1)
        elif len(pcm) > frame_count:
            pcm = pcm[:frame_count]

        windowed = pcm * np.hanning(len(pcm))

        # Gate raw signal — if RMS is below threshold, treat as silence
        rms = float(np.sqrt(np.mean(pcm ** 2)))
        if rms < 0.002:
            with _lock:
                _fft_bands[:] = 0.0
            return (None, pyaudio.paContinue)

        spectrum = np.abs(np.fft.rfft(windowed))

        bands = np.zeros(COLS, dtype=np.float32)
        for c in range(COLS):
            lo, hi = edges[c], edges[c + 1]
            bands[c] = float(np.mean(spectrum[lo:hi])) if hi > lo else float(spectrum[lo])

        peak = spectrum.max()
        if peak > 1e-6:
            bands /= peak
        bands = np.clip(bands * GAIN, 0.0, 1.0)
        bands[bands < 0.15] = 0.0  # ← noise gate

        with _lock:
            _fft_bands[:] = bands

        return (None, pyaudio.paContinue)
    return callback


def _start_loopback():
    """Open pyaudiowpatch WASAPI loopback on the default output device.
    Returns (stream, pa_instance) or (None, pa_instance) on failure."""
    pa = pyaudio.PyAudio()
    try:
        wasapi_info = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_out = pa.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        print(f"Default output device : {default_out['name']}")

        # Find matching loopback device
        loopback = None
        for i in range(pa.get_device_count()):
            dev = pa.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice") and default_out["name"] in dev["name"]:
                loopback = dev
                break

        # Fallback: any loopback device
        if loopback is None:
            print("Exact match not found — trying any loopback device...")
            for i in range(pa.get_device_count()):
                dev = pa.get_device_info_by_index(i)
                if dev.get("isLoopbackDevice"):
                    loopback = dev
                    break

        if loopback is None:
            print("No loopback device found.")
            return None, pa

        sr  = int(loopback["defaultSampleRate"])
        ch  = loopback["maxInputChannels"]
        print(f"Loopback device       : {loopback['name']}")
        print(f"Sample rate / channels: {sr} Hz / {ch}")

        edges  = _log_edges(BLOCK_SIZE, COLS, sr)
        stream = pa.open(
            format=pyaudio.paFloat32,
            channels=ch,
            rate=sr,
            input=True,
            input_device_index=loopback["index"],
            frames_per_buffer=BLOCK_SIZE,
            stream_callback=_make_callback(edges),
        )
        stream.start_stream()
        return stream, pa

    except Exception as e:
        print(f"Loopback error: {e}")
        return None, pa


# ─────────────────────────────────────────────
# Colour helpers
# ─────────────────────────────────────────────
def _lerp(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return (int(c1[0] + (c2[0] - c1[0]) * t),
            int(c1[1] + (c2[1] - c1[1]) * t),
            int(c1[2] + (c2[2] - c1[2]) * t))


def amp_to_color(a):
    if a < 0.0001: return C_DEAD
    if a < 0.40:   return _lerp(C_DEAD,     C_AMBER,    a / 0.40)
    if a < 0.70:   return _lerp(C_AMBER,    C_FULL_RED, (a - 0.40) / 0.30)
    if a < 0.90:   return _lerp(C_FULL_RED, C_ORANGE,   (a - 0.70) / 0.20)
    return             _lerp(C_ORANGE,   C_HOT_WHITE,(a - 0.90) / 0.10)


def row_amp(col_amp, row):
    """Gravity-fill: bottom rows light first. Row 0 = top, ROWS-1 = bottom."""
    row_from_bottom = ROWS - 1 - row
    threshold = row_from_bottom / (ROWS - 1)
    if col_amp <= threshold:
        return 0.0
    excess = col_amp - threshold
    return min(1.0, excess / (1.0 / ROWS))


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main():
    pygame.init()
    screen = pygame.display.set_mode((WIN_W, WIN_H))
    pygame.display.set_caption("BETA 5 — VOCODER ARRAY — SOUND TO LIGHT")
    clock  = pygame.time.Clock()

    try:
        font_label = pygame.font.SysFont("Courier New", 9, bold=False)
        font_small = pygame.font.SysFont("Courier New", 9, bold=False)
    except Exception:
        font_label = pygame.font.SysFont("monospace", 9)
        font_small = pygame.font.SysFont("monospace", 9)

    PANEL_X = (WIN_W - PANEL_W) // 2
    PANEL_Y = (WIN_H - PANEL_H) // 2

    # Display-side amplitude state
    col_amps  = np.zeros(COLS, dtype=np.float64)
    peaks     = np.zeros(COLS, dtype=np.float64)
    peak_hold = np.zeros(COLS, dtype=np.float64)

    # Bloom surfaces
    bloom      = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
    prev_bloom = pygame.Surface((WIN_W, WIN_H), pygame.SRCALPHA)
    prev_bloom.fill((0, 0, 0, 0))

    idle_phases = np.linspace(0, 2 * math.pi, COLS)

    # Start loopback
    print("Opening WASAPI loopback...")
    stream, pa  = _start_loopback()
    loopback_ok = stream is not None

    if loopback_ok:
        print("Loopback stream active — reacting to system audio.")
    else:
        print("Falling back to simulation mode.")

    start_time = time.time()
    db_display = "PWR: --- dB"
    db_color   = C_LABEL
    db_timer   = 0.0

    running = True
    while running:
        dt = clock.tick(FPS) / 1000.0
        t  = time.time() - start_time

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False

        # ── Pull latest FFT bands ────────────────────────────────────────
        if loopback_ok:
            with _lock:
                raw = _fft_bands.astype(np.float64)
        else:
            raw = np.array([
                0.08 + 0.07 * math.sin(t * 1.1 + idle_phases[c])
                for c in range(COLS)
            ], dtype=np.float64)

        # ── Artistic smear ───────────────────────────────────────────────
        smeared = raw.copy()
        smeared[1:-1] += SPILL * (raw[:-2] + raw[2:]) * 0.5
        smeared = np.clip(smeared, 0.0, 1.0)

        # ── Asymmetric smoothing ─────────────────────────────────────────
        rising         = smeared > col_amps
        col_amps[rising]  += ATTACK * (smeared[rising]  - col_amps[rising])
        col_amps[~rising] += DECAY  * (smeared[~rising] - col_amps[~rising])

        # ── Idle floor ───────────────────────────────────────────────────
        if col_amps.sum() < COLS * 0.02:
            idle     = IDLE_AMP * (0.5 + 0.5 * np.sin(t * 1.3 + idle_phases))
            col_amps = np.maximum(col_amps, idle)

        # ── Peak hold ────────────────────────────────────────────────────
        new_peak             = col_amps >= peaks
        peaks[new_peak]      = col_amps[new_peak]
        peak_hold[new_peak]  = PEAK_HOLD_S
        peak_hold[~new_peak] -= dt
        drop                 = (~new_peak) & (peak_hold <= 0)
        peaks[drop]          = np.maximum(peaks[drop] - dt * 0.6, col_amps[drop])

        # ── dB readout ───────────────────────────────────────────────────
        db_timer += dt
        if db_timer >= 0.1:
            db_timer = 0.0
            mx       = float(col_amps.max())
            db       = 20.0 * math.log10(mx) if mx > 1e-5 else -60.0
            db_display = f"PWR: {db:+.1f} dB"
            db_color = (C_HOT_WHITE if db > -6 else
                        C_ORANGE    if db > -18 else C_LABEL)

        # ── Draw ─────────────────────────────────────────────────────────
        screen.fill(C_BG)
        bloom.fill((0, 0, 0, 0))

        prev_bloom.set_alpha(89)
        screen.blit(prev_bloom, (0, 0))

        pygame.draw.rect(screen, C_BORDER,
                         pygame.Rect(PANEL_X, PANEL_Y, PANEL_W, PANEL_H), 1)

        lsurf = font_label.render("VOCODER ARRAY -- CHANNEL STATUS", True, C_LABEL)
        screen.blit(lsurf, (PANEL_X + 3, PANEL_Y + 3))

        dbsurf = font_small.render(db_display, True, db_color)
        screen.blit(dbsurf,
                    (PANEL_X + PANEL_W - dbsurf.get_width() - 4, PANEL_Y + 3))

        node_top = PANEL_Y + LABEL_H + PANEL_PAD // 2

        for col in range(COLS):
            cx = PANEL_X + PANEL_PAD + col * NODE_STEP + NODE_DIA // 2
            ca = float(col_amps[col])
            pk = float(peaks[col])

            for row in range(ROWS):
                cy = node_top + row * NODE_STEP + NODE_DIA // 2
                na = row_amp(ca, row)

                if na > 0.001:
                    color   = amp_to_color(na)
                    b_alpha = int(120 * na)
                    b_color = (min(255, color[0]),
                               min(255, int(color[1] * 0.5)),
                               min(255, int(color[2] * 0.3)),
                               b_alpha)
                    pygame.draw.circle(bloom, b_color, (cx, cy), NODE_DIA // 2 + 6)
                else:
                    color = C_DEAD

                pygame.draw.circle(screen, color, (cx, cy), NODE_DIA // 2)

            # Peak dot
            if pk > 0.05:
                pk_row = int((1.0 - pk) * (ROWS - 1) + 0.5)
                pk_row = max(0, min(ROWS - 1, pk_row))
                pk_cy  = node_top + pk_row * NODE_STEP + NODE_DIA // 2
                pygame.draw.circle(screen, C_PEAK, (cx, pk_cy), 2)

        bloom.set_alpha(110)
        screen.blit(bloom, (0, 0))
        prev_bloom.fill((0, 0, 0, 0))
        prev_bloom.blit(bloom, (0, 0))

        src   = "LOOPBACK" if loopback_ok else "SIMULATION"
        scol  = C_LABEL    if loopback_ok else C_AMBER_DIM
        ssurf = font_small.render(
            f"SRC: {src}  |  T: {t:.1f}s  |  {db_display}", True, scol)
        screen.blit(ssurf, (PANEL_X, PANEL_Y + PANEL_H + 6))

        pygame.display.flip()

    if stream:
        stream.stop_stream()
        stream.close()
    pa.terminate()
    pygame.quit()
    print("Closed.")


if __name__ == "__main__":
    main()
