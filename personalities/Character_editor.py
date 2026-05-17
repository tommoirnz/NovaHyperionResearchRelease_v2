#!/usr/bin/env python3
"""
character_editor.py  –  Nova Avatar / Character JSON Editor
============================================================
Create or edit character JSON files for use in Nova AI Theatre / NOVADream.

Dependencies (install as needed):
    pip install edge-tts pygame
    pip install pywin32          # for SAPI5 enumeration (Windows only)

Usage:
    python character_editor.py
    python character_editor.py  path/to/character.json   # open directly
"""

import asyncio
import json
import os
import sys
import tempfile
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

# ── Optional back-ends ────────────────────────────────────────────────────────
try:
    import win32com.client as _win32com
    _WIN32 = True
except ImportError:
    _WIN32 = False

try:
    import edge_tts as _edge_tts
    _EDGE = True
except ImportError:
    _EDGE = False

try:
    import pygame as _pygame
    _pygame.mixer.init()
    _PYGAME = True
except Exception:
    _PYGAME = False

# ── Edge voice catalogue ──────────────────────────────────────────────────────
EDGE_VOICES = [
    # English
    "en-US-AriaNeural",     "en-US-GuyNeural",      "en-US-JennyNeural",
    "en-US-DavisNeural",    "en-US-AmberNeural",    "en-US-AnaNeural",
    "en-US-AshleyNeural",   "en-US-BrandonNeural",  "en-US-ChristopherNeural",
    "en-US-CoraNeural",     "en-US-ElizabethNeural","en-US-EricNeural",
    "en-US-JacobNeural",    "en-US-MichelleNeural", "en-US-MonicaNeural",
    "en-US-NancyNeural",    "en-US-RogerNeural",    "en-US-SaraNeural",
    "en-US-SteffanNeural",  "en-US-TonyNeural",
    "en-GB-LibbyNeural",    "en-GB-MaisieNeural",   "en-GB-RyanNeural",
    "en-GB-SoniaNeural",    "en-GB-ThomasNeural",
    "en-AU-NatashaNeural",  "en-AU-WilliamNeural",
    "en-CA-ClaraNeural",    "en-CA-LiamNeural",
    "en-IN-NeerjaNeural",   "en-IN-PrabhatNeural",
    "en-IE-ConnorNeural",   "en-IE-EmilyNeural",
    "en-NZ-MitchellNeural", "en-NZ-MollyNeural",
    "en-PH-JamesNeural",    "en-PH-RosaNeural",
    # Chinese
    "zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural",  "zh-CN-YunjianNeural",
    "zh-CN-YunxiNeural",    "zh-CN-YunxiaNeural",  "zh-CN-YunyangNeural",
    "zh-CN-liaoning-XiaobeiNeural", "zh-CN-shaanxi-XiaoniNeural",
    "zh-TW-HsiaoChenNeural","zh-TW-HsiaoYuNeural", "zh-TW-YunJheNeural",
    "zh-HK-HiuGaaiNeural",  "zh-HK-HiuMaanNeural","zh-HK-WanLungNeural",
    # Japanese / Korean
    "ja-JP-NanamiNeural",   "ja-JP-KeitaNeural",
    "ko-KR-InJoonNeural",   "ko-KR-SunHiNeural",
    # Spanish
    "es-ES-AlvaroNeural",   "es-ES-ElviraNeural",
    "es-MX-DaliaNeural",    "es-MX-JorgeNeural",
    "es-US-AlonsoNeural",   "es-US-PalomaNeural",
    # French
    "fr-FR-DeniseNeural",   "fr-FR-HenriNeural",
    "fr-CA-AntoineNeural",  "fr-CA-JeanNeural",    "fr-CA-SylvieNeural",
    # German
    "de-DE-AmalaNeural",    "de-DE-ConradNeural",
    "de-DE-KatjaNeural",    "de-DE-KillianNeural",
    # Italian
    "it-IT-DiegoNeural",    "it-IT-ElsaNeural",    "it-IT-IsabellaNeural",
    # Portuguese
    "pt-BR-AntonioNeural",  "pt-BR-FranciscaNeural",
    "pt-PT-DuarteNeural",   "pt-PT-RaquelNeural",
    # Russian / Arabic / Hindi
    "ru-RU-DariyaNeural",   "ru-RU-SvetlanaNeural",
    "ar-AE-FatimaNeural",   "ar-AE-HamdanNeural",
    "ar-SA-HamedNeural",    "ar-SA-ZariyahNeural",
    "hi-IN-MadhurNeural",   "hi-IN-SwaraNeural",
    # European
    "nl-NL-ColetteNeural",  "nl-NL-FennaNeural",   "nl-NL-MaartenNeural",
    "pl-PL-AgnieszkaNeural","pl-PL-MarekNeural",   "pl-PL-ZofiaNeural",
    "tr-TR-AhmetNeural",    "tr-TR-EmelNeural",
    "sv-SE-MattiasNeural",  "sv-SE-SofieNeural",
    "da-DK-ChristelNeural", "da-DK-JeppeNeural",
    "nb-NO-FinnNeural",     "nb-NO-PernilleNeural",
    "fi-FI-HarriNeural",    "fi-FI-NooraNeural",
    "el-GR-AthinaNeural",   "el-GR-NestorasNeural",
    "he-IL-AvriNeural",     "he-IL-HilaNeural",
    "cs-CZ-AntoninNeural",  "cs-CZ-VlastaNeural",
    "hu-HU-NoemiNeural",    "hu-HU-TamasNeural",
    "ro-RO-AlinaNeural",    "ro-RO-EmilNeural",
    "uk-UA-OstapNeural",    "uk-UA-PolinaNeural",
    # Asian
    "vi-VN-HoaiMyNeural",   "vi-VN-NamMinhNeural",
    "th-TH-AcharaNeural",   "th-TH-NiwatNeural",   "th-TH-PremwadeeNeural",
    "id-ID-ArdiNeural",     "id-ID-GadisNeural",
    "ms-MY-OsmanNeural",    "ms-MY-YasminNeural",
    # Celtic / regional
    "ca-ES-JoanaNeural",    "ca-ES-EnricNeural",
    "eu-ES-AinhoaNeural",   "eu-ES-AnderNeural",
    "gl-ES-SabelaNeural",   "gl-ES-RoiNeural",
    "cy-GB-AledNeural",     "cy-GB-NiaNeural",
    "ga-IE-ColmNeural",     "ga-IE-OrlaNeural",
]

TEST_PHRASE = "Hello! This is a voice preview. How do I sound to you?"

# ── SAPI helpers ──────────────────────────────────────────────────────────────

def get_sapi_voices():
    """Return list of installed SAPI5 voice description strings."""
    if not _WIN32:
        return []
    try:
        sapi = _win32com.Dispatch("SAPI.SpVoice")
        col = sapi.GetVoices()
        return [col.Item(i).GetDescription() for i in range(col.Count)]
    except Exception as exc:
        print(f"[SAPI] enum error: {exc}")
        return []


def _sapi_speak_worker(text, voice_name, rate_float, volume_float):
    """Blocking SAPI speak – run in a daemon thread.

    COM requires CoInitialize on every thread that touches it; the main thread
    gets this automatically but spawned threads do not, hence the explicit
    CoInitialize / CoUninitialize bracketing here.
    """
    if not _WIN32:
        return
    import pythoncom
    pythoncom.CoInitialize()
    try:
        sapi = _win32com.Dispatch("SAPI.SpVoice")
        col  = sapi.GetVoices()
        for i in range(col.Count):
            if col.Item(i).GetDescription() == voice_name:
                sapi.Voice = col.Item(i)
                break
        # SAPI rate: -10..10  (0 = normal).  1.0 → 0, 0.5 → -5, 2.0 → +5
        sapi.Rate   = max(-10, min(10, int((rate_float - 1.0) * 5)))
        sapi.Volume = max(0,   min(100, int(volume_float * 100)))
        sapi.Speak(text)
    except Exception as exc:
        print(f"[SAPI] speak error: {exc}")
    finally:
        pythoncom.CoUninitialize()


def sapi_speak(text, voice_name, rate=1.0, volume=1.0):
    t = threading.Thread(target=_sapi_speak_worker,
                         args=(text, voice_name, rate, volume), daemon=True)
    t.start()


# ── Edge TTS helpers ──────────────────────────────────────────────────────────

def _rate_to_edge_pct(rate_float):
    """Convert float speech rate (1.0=normal) to edge-tts percent string.
    1.0 -> '+0%',  1.5 -> '+50%',  0.7 -> '-30%'"""
    pct = int(round((rate_float - 1.0) * 100))
    return f"+{pct}%" if pct >= 0 else f"{pct}%"

async def _edge_generate(text, voice, rate_pct, path):
    communicate = _edge_tts.Communicate(text, voice, rate=rate_pct)
    await communicate.save(path)


def _edge_speak_worker(text, voice, rate_pct, volume_float, status_cb):
    if not _EDGE:
        status_cb("edge-tts not installed (pip install edge-tts)")
        return
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp.close()
    try:
        asyncio.run(_edge_generate(text, voice, rate_pct, tmp.name))
        status_cb("Playing edge audio …")
        if _PYGAME:
            _pygame.mixer.music.load(tmp.name)
            _pygame.mixer.music.set_volume(min(1.0, volume_float))
            _pygame.mixer.music.play()
            # wait for playback to finish before deleting
            import time
            while _pygame.mixer.music.get_busy():
                time.sleep(0.05)
        else:
            # fallback – hand off to OS default player
            os.startfile(tmp.name)
            import time; time.sleep(3)
        status_cb("Ready")
    except Exception as exc:
        status_cb(f"Edge error: {exc}")
    finally:
        try:
            os.unlink(tmp.name)
        except Exception:
            pass


def edge_speak(text, voice, rate=1.0, volume=1.0, status_cb=None):
    if status_cb is None:
        status_cb = lambda s: None
    rate_pct = _rate_to_edge_pct(rate)
    t = threading.Thread(target=_edge_speak_worker,
                         args=(text, voice, rate_pct, volume, status_cb), daemon=True)
    t.start()


# ── Colour palette ────────────────────────────────────────────────────────────
BG       = "#1e1e2e"
PANEL    = "#2a2a3e"
ACCENT   = "#7c6af7"
ACCENT2  = "#4ea8de"
FG       = "#cdd6f4"
FG_DIM   = "#6c7086"
ENTRY_BG = "#313244"
BTN_BG   = "#45475a"
BTN_ACT  = "#585b70"
RED      = "#f38ba8"
GREEN    = "#a6e3a1"
YELLOW   = "#f9e2af"


# ═══════════════════════════════════════════════════════════════════════════════
class CharacterEditor(tk.Tk):
# ═══════════════════════════════════════════════════════════════════════════════

    def __init__(self, initial_file=None):
        super().__init__()
        self.title("Nova · Character Editor")
        self.configure(bg=BG)
        self.minsize(820, 720)

        self._current_file = None
        self._sapi_voices  = get_sapi_voices()
        self._dirty        = False          # unsaved changes flag

        self._build_menu()
        self._build_ui()
        self._apply_theme()

        if initial_file and os.path.isfile(initial_file):
            self._load_file(initial_file)
        else:
            self._new_character()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = tk.Menu(self, bg=PANEL, fg=FG, activebackground=ACCENT,
                     activeforeground=FG, tearoff=False)

        fm = tk.Menu(mb, bg=PANEL, fg=FG, activebackground=ACCENT,
                     activeforeground=FG, tearoff=False)
        fm.add_command(label="New",        accelerator="Ctrl+N", command=self._new_character)
        fm.add_command(label="Open…",      accelerator="Ctrl+O", command=self._open_file)
        fm.add_separator()
        fm.add_command(label="Save",       accelerator="Ctrl+S", command=self._save)
        fm.add_command(label="Save As…",   accelerator="Ctrl+Shift+S", command=self._save_as)
        fm.add_separator()
        fm.add_command(label="Exit",       command=self._on_close)
        mb.add_cascade(label="File", menu=fm)

        em = tk.Menu(mb, bg=PANEL, fg=FG, activebackground=ACCENT,
                     activeforeground=FG, tearoff=False)
        em.add_command(label="Clear System Prompt", command=self._clear_prompt)
        em.add_command(label="Reload SAPI voices",  command=self._reload_sapi)
        mb.add_cascade(label="Edit", menu=em)

        self.config(menu=mb)

        self.bind_all("<Control-n>", lambda _: self._new_character())
        self.bind_all("<Control-o>", lambda _: self._open_file())
        self.bind_all("<Control-s>", lambda _: self._save())
        self.bind_all("<Control-S>", lambda _: self._save_as())

    # ── UI scaffold ───────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── top: title bar / file path ────────────────────────────────────
        top = tk.Frame(self, bg=PANEL, pady=6)
        top.pack(fill="x")
        tk.Label(top, text="Nova Character Editor", font=("Segoe UI", 13, "bold"),
                 bg=PANEL, fg=ACCENT).pack(side="left", padx=12)
        self._lbl_file = tk.Label(top, text="[new]", font=("Segoe UI", 9),
                                   bg=PANEL, fg=FG_DIM)
        self._lbl_file.pack(side="left", padx=6)
        tk.Button(top, text="Open…", command=self._open_file,
                  **self._btn_kw()).pack(side="right", padx=6)
        tk.Button(top, text="New",   command=self._new_character,
                  **self._btn_kw()).pack(side="right", padx=(0, 4))

        # ── main paned area ───────────────────────────────────────────────
        pane = tk.PanedWindow(self, orient="vertical", bg=BG,
                              sashrelief="flat", sashwidth=6)
        pane.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        top_frame = tk.Frame(pane, bg=BG)
        pane.add(top_frame, stretch="always")

        bot_frame = tk.Frame(pane, bg=BG)
        pane.add(bot_frame, stretch="always")
        pane.paneconfigure(top_frame, minsize=340)
        pane.paneconfigure(bot_frame, minsize=160)

        # ── top section ───────────────────────────────────────────────────
        self._build_identity(top_frame)
        self._build_voice(top_frame)
        self._build_meta(top_frame)

        # ── bottom: system prompt ─────────────────────────────────────────
        self._build_prompt(bot_frame)

        # ── status bar ────────────────────────────────────────────────────
        bar = tk.Frame(self, bg=PANEL, pady=3)
        bar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="Ready")
        tk.Label(bar, textvariable=self._status_var,
                 font=("Segoe UI", 8), bg=PANEL, fg=FG_DIM,
                 anchor="w").pack(side="left", padx=10)
        tk.Button(bar, text="Save", command=self._save,
                  bg=ACCENT, fg="white", relief="flat", padx=12, pady=1,
                  font=("Segoe UI", 9, "bold"),
                  activebackground=ACCENT2, cursor="hand2").pack(side="right", padx=8)

    # ── Identity panel ────────────────────────────────────────────────────────

    def _build_identity(self, parent):
        f = self._section(parent, "Identity")

        self._e(f, "Character name",  row=0)
        self.var_name = self._entry(f, 0)

        self._e(f, "Description",     row=1)
        self.var_desc = self._entry(f, 1)

    # ── Voice panel ───────────────────────────────────────────────────────────

    def _build_voice(self, parent):
        f = self._section(parent, "Voice")

        # Engine radio
        tk.Label(f, text="Primary engine:", bg=PANEL, fg=FG,
                 font=("Segoe UI", 9)).grid(row=0, column=0, sticky="w",
                                             padx=8, pady=(4, 2))
        self.var_engine = tk.StringVar(value="edge")
        ef = tk.Frame(f, bg=PANEL)
        ef.grid(row=0, column=1, columnspan=3, sticky="w")
        for val, lbl in (("edge", "Edge TTS"), ("sapi5", "SAPI5")):
            tk.Radiobutton(ef, text=lbl, variable=self.var_engine, value=val,
                           bg=PANEL, fg=FG, selectcolor=ENTRY_BG,
                           activebackground=PANEL, activeforeground=FG,
                           font=("Segoe UI", 9),
                           command=self._on_engine_change).pack(side="left", padx=6)

        # ── Edge row ──────────────────────────────────────────────────────
        self._e(f, "Edge voice:", row=1)
        self.var_edge_voice = tk.StringVar(value="en-GB-RyanNeural")
        cb_edge = ttk.Combobox(f, textvariable=self.var_edge_voice,
                               values=EDGE_VOICES, state="readonly", width=34)
        cb_edge.grid(row=1, column=1, columnspan=2, sticky="ew", padx=4, pady=3)
        self._style_combo(cb_edge)
        tk.Button(f, text="▶ Test Edge", command=self._test_edge,
                  **self._btn_kw(bg=ACCENT2)).grid(row=1, column=3,
                                                    padx=(4, 8), pady=3)

        # Edge search box
        tk.Label(f, text="Filter:", bg=PANEL, fg=FG_DIM,
                 font=("Segoe UI", 8)).grid(row=2, column=0, sticky="e", padx=8)
        self.var_edge_filter = tk.StringVar()
        self.var_edge_filter.trace_add("write", self._filter_edge)
        filter_e = tk.Entry(f, textvariable=self.var_edge_filter, width=20,
                            bg=ENTRY_BG, fg=FG, insertbackground=FG,
                            relief="flat", font=("Segoe UI", 9))
        filter_e.grid(row=2, column=1, sticky="w", padx=4, pady=2)
        self._cb_edge = cb_edge   # keep ref for filter updates

        # ── SAPI row ──────────────────────────────────────────────────────
        self._e(f, "SAPI5 voice:", row=3)
        sapi_choices = self._sapi_voices if self._sapi_voices else ["(none installed)"]
        self.var_sapi_voice = tk.StringVar(
            value=sapi_choices[0] if sapi_choices else "")
        cb_sapi = ttk.Combobox(f, textvariable=self.var_sapi_voice,
                               values=sapi_choices, state="readonly", width=34)
        cb_sapi.grid(row=3, column=1, columnspan=2, sticky="ew", padx=4, pady=3)
        self._cb_sapi = cb_sapi          # keep ref for programmatic .set()
        self._style_combo(cb_sapi)
        tk.Button(f, text="▶ Test SAPI", command=self._test_sapi,
                  **self._btn_kw(bg=ACCENT2)).grid(row=3, column=3,
                                                    padx=(4, 8), pady=3)

        # ── Rate + Volume ─────────────────────────────────────────────────
        self.var_rate   = tk.DoubleVar(value=1.0)
        self.var_volume = tk.DoubleVar(value=1.0)
        self._slider(f, "Speech rate",  self.var_rate,   0.5, 3.0, row=4)
        self._slider(f, "Volume",       self.var_volume, 0.0, 1.0, row=5)

        # ── Test phrase ───────────────────────────────────────────────────
        self._e(f, "Test phrase:", row=6)
        self.var_test_phrase = tk.StringVar(value=TEST_PHRASE)
        tk.Entry(f, textvariable=self.var_test_phrase, bg=ENTRY_BG, fg=FG,
                 insertbackground=FG, relief="flat",
                 font=("Segoe UI", 9), width=46
                 ).grid(row=6, column=1, columnspan=3, sticky="ew", padx=4, pady=3)

        f.columnconfigure(1, weight=1)

    # ── Meta panel (temperature, personality) ─────────────────────────────────

    def _build_meta(self, parent):
        f = self._section(parent, "Behaviour")

        self.var_temp = tk.DoubleVar(value=0.99)
        self._slider(f, "Temperature", self.var_temp, 0.0, 1.0, row=0)

        self.var_personality = tk.BooleanVar(value=True)
        tk.Checkbutton(f, text="is_personality  (mark as personality character)",
                       variable=self.var_personality,
                       bg=PANEL, fg=FG, selectcolor=ENTRY_BG,
                       activebackground=PANEL, activeforeground=FG,
                       font=("Segoe UI", 9)
                       ).grid(row=1, column=0, columnspan=4, sticky="w",
                              padx=10, pady=(0, 4))

        f.columnconfigure(1, weight=1)

    # ── System prompt ─────────────────────────────────────────────────────────

    def _build_prompt(self, parent):
        hdr = tk.Frame(parent, bg=PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text="System Prompt", font=("Segoe UI", 9, "bold"),
                 bg=PANEL, fg=ACCENT).pack(side="left", padx=10, pady=4)
        tk.Button(hdr, text="Clear", command=self._clear_prompt,
                  **self._btn_kw(fg=RED)).pack(side="right", padx=8, pady=3)

        self.txt_prompt = scrolledtext.ScrolledText(
            parent, wrap="word", bg=ENTRY_BG, fg=FG, insertbackground=FG,
            selectbackground=ACCENT, font=("Consolas", 9), relief="flat",
            undo=True, padx=8, pady=6)
        self.txt_prompt.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.txt_prompt.bind("<Key>", lambda _: self._mark_dirty())

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _section(self, parent, title):
        outer = tk.Frame(parent, bg=BG)
        outer.pack(fill="x", padx=4, pady=4)
        hdr = tk.Frame(outer, bg=PANEL)
        hdr.pack(fill="x")
        tk.Label(hdr, text=title, font=("Segoe UI", 9, "bold"),
                 bg=PANEL, fg=ACCENT).pack(side="left", padx=10, pady=3)
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="x")
        return inner

    def _e(self, parent, text, row):
        tk.Label(parent, text=text, bg=PANEL, fg=FG,
                 font=("Segoe UI", 9), anchor="e", width=14
                 ).grid(row=row, column=0, sticky="e", padx=8, pady=3)

    def _entry(self, parent, row):
        var = tk.StringVar()
        var.trace_add("write", lambda *_: self._mark_dirty())
        e = tk.Entry(parent, textvariable=var, bg=ENTRY_BG, fg=FG,
                     insertbackground=FG, relief="flat",
                     font=("Segoe UI", 9))
        e.grid(row=row, column=1, columnspan=3, sticky="ew", padx=(4, 10), pady=3)
        parent.columnconfigure(1, weight=1)
        return var

    def _slider(self, parent, label, var, lo, hi, row):
        tk.Label(parent, text=f"{label}:", bg=PANEL, fg=FG,
                 font=("Segoe UI", 9), anchor="e", width=14
                 ).grid(row=row, column=0, sticky="e", padx=8, pady=2)
        lbl_val = tk.Label(parent, text=f"{var.get():.2f}", bg=PANEL, fg=ACCENT2,
                           font=("Segoe UI", 9), width=5)
        lbl_val.grid(row=row, column=3, padx=(0, 8))

        # Use trace_add so the label refreshes on BOTH user drags AND
        # programmatic var.set() calls (e.g. when loading a JSON).
        # Scale's command= only fires on mouse interaction.
        def _refresh(*_):
            # ttk.Scale transiently sets the var to relative strings like
            # "+10%" during widget init; ignore those, wait for a real float.
            try:
                lbl_val.config(text=f"{var.get():.2f}")
                self._mark_dirty()
            except (tk.TclError, ValueError):
                pass

        var.trace_add("write", _refresh)

        s = ttk.Scale(parent, from_=lo, to=hi, variable=var,
                      orient="horizontal")
        s.grid(row=row, column=1, columnspan=2, sticky="ew", padx=4, pady=2)

    def _fget(self, var, default=0.0):
        """Safe DoubleVar getter -- ttk.Scale can leave relative strings like
        '+0%' in the variable if the slider was never dragged by the user.
        Fall back to *default* rather than raising TclError."""
        try:
            return float(var.get())
        except (tk.TclError, ValueError):
            return default

    def _btn_kw(self, bg=BTN_BG, fg=FG):
        return dict(bg=bg, fg=fg, relief="flat", padx=8, pady=3,
                    font=("Segoe UI", 9), activebackground=BTN_ACT,
                    activeforeground=FG, cursor="hand2")

    def _style_combo(self, cb):
        """Apply dark styling to a ttk.Combobox.

        IMPORTANT: a readonly Combobox in the 'clam' theme draws its text using
        the *readonly* state's foreground/background, which fall back to system
        defaults unless explicitly mapped. With a dark palette those defaults
        leave the text the same colour as the field background, so the
        selection appears blank. style.map(... 'readonly' ...) is the only
        fix — style.configure() alone is not enough.
        """
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TCombobox",
                        fieldbackground=ENTRY_BG, background=BTN_BG,
                        foreground=FG, selectbackground=ACCENT,
                        arrowcolor=FG)
        style.map("TCombobox",
                  fieldbackground=[("readonly", ENTRY_BG),
                                   ("disabled", ENTRY_BG)],
                  foreground    =[("readonly", FG),
                                  ("disabled", FG_DIM)],
                  selectbackground=[("readonly", ENTRY_BG)],
                  selectforeground=[("readonly", FG)],
                  background    =[("readonly", ENTRY_BG)])

    def _apply_theme(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TScale", background=PANEL, troughcolor=ENTRY_BG,
                        sliderthickness=14, sliderrelief="flat")

    def _filter_edge(self, *_):
        term = self.var_edge_filter.get().lower()
        filtered = [v for v in EDGE_VOICES if term in v.lower()] or EDGE_VOICES
        self._cb_edge["values"] = filtered
        if self.var_edge_voice.get() not in filtered:
            self.var_edge_voice.set(filtered[0])

    def _mark_dirty(self):
        if not self._dirty:
            self._dirty = True
            self._update_title()

    def _update_title(self):
        name = os.path.basename(self._current_file) if self._current_file else "new"
        dirty = " ●" if self._dirty else ""
        self.title(f"Nova · Character Editor  –  {name}{dirty}")
        self._lbl_file.config(
            text=self._current_file if self._current_file else "[unsaved]")

    def _set_status(self, msg):
        self._status_var.set(msg)
        self.after(4000, lambda: self._status_var.set("Ready"))

    # ── Engine radio callback ─────────────────────────────────────────────────

    def _on_engine_change(self):
        self._mark_dirty()

    # ── Voice test ────────────────────────────────────────────────────────────

    def _test_edge(self):
        voice = self.var_edge_voice.get()
        if not voice:
            messagebox.showwarning("No voice", "Select an Edge voice first.")
            return
        if not _EDGE:
            messagebox.showerror("Missing package",
                                 "edge-tts is not installed.\n\n"
                                 "Run:  pip install edge-tts")
            return
        self._set_status(f"Generating Edge audio with {voice} …")
        edge_speak(self.var_test_phrase.get(), voice,
                   rate=self._fget(self.var_rate, 1.0),
                   volume=self._fget(self.var_volume, 1.0),
                   status_cb=lambda s: self.after(0, self._set_status, s))

    def _test_sapi(self):
        voice = self.var_sapi_voice.get()
        if not voice or voice.startswith("("):
            messagebox.showwarning("No voice", "No SAPI5 voice selected.")
            return
        self._set_status(f"Speaking with SAPI5: {voice} …")
        sapi_speak(self.var_test_phrase.get(), voice,
                   rate=self._fget(self.var_rate, 1.0),
                   volume=self._fget(self.var_volume, 1.0))

    # ── Reload SAPI list ──────────────────────────────────────────────────────

    def _reload_sapi(self):
        self._sapi_voices = get_sapi_voices()
        self._set_status(f"Found {len(self._sapi_voices)} SAPI voices.")

    # ── JSON serialise / deserialise ──────────────────────────────────────────

    def _to_dict(self):
        return {
            "name":        self.var_name.get().strip(),
            "description": self.var_desc.get().strip(),
            "voice": {
                "engine":      self.var_engine.get(),
                "edge_voice":  self.var_edge_voice.get(),
                "sapi_voice":  self.var_sapi_voice.get(),
                "speech_rate": round(self._fget(self.var_rate, 1.0), 2),
                "volume":      round(self._fget(self.var_volume, 1.0), 2),
            },
            "temperature":    round(self._fget(self.var_temp, 0.99), 4),
            "system_prompt":  self.txt_prompt.get("1.0", "end-1c"),
            "is_personality": self.var_personality.get(),
        }

    def _from_dict(self, d):
        self.var_name.set(d.get("name", ""))
        self.var_desc.set(d.get("description", ""))

        v = d.get("voice", {})

        # Engine radio — set before voices so the button reflects correctly
        self.var_engine.set(v.get("engine", "edge"))

        # Clear any active filter first so the full EDGE_VOICES list is in the
        # combobox; otherwise a loaded voice that's outside the filtered subset
        # silently fails to display.
        self.var_edge_filter.set("")
        self._cb_edge["values"] = EDGE_VOICES

        edge_v = v.get("edge_voice", "en-GB-RyanNeural")
        if edge_v not in EDGE_VOICES:
            edge_v = EDGE_VOICES[0]
        self.var_edge_voice.set(edge_v)
        # .current(index) is the only reliable way to force a readonly
        # Combobox to repaint; .set() updates the var but not the display.
        try:
            self._cb_edge.current(EDGE_VOICES.index(edge_v))
        except ValueError:
            self._cb_edge.current(0)

        sapi_v = v.get("sapi_voice", "")
        if sapi_v not in self._sapi_voices and self._sapi_voices:
            sapi_v = self._sapi_voices[0]
        if sapi_v:
            self.var_sapi_voice.set(sapi_v)
            # same .current(index) approach for the SAPI combobox
            try:
                self._cb_sapi.current(self._sapi_voices.index(sapi_v))
            except ValueError:
                self._cb_sapi.current(0)

        self.var_rate.set(v.get("speech_rate", 1.0))
        self.var_volume.set(v.get("volume", 1.0))
        self.var_temp.set(d.get("temperature", 0.99))
        self.var_personality.set(d.get("is_personality", True))

        self.txt_prompt.delete("1.0", "end")
        self.txt_prompt.insert("1.0", d.get("system_prompt", ""))

    # ── File operations ───────────────────────────────────────────────────────

    def _new_character(self):
        if self._dirty and not self._confirm_discard():
            return
        self._current_file = None
        self._dirty = False
        self._from_dict({
            "name": "", "description": "",
            "voice": {"engine": "edge",
                      "edge_voice": "en-GB-RyanNeural",
                      "sapi_voice": self._sapi_voices[0] if self._sapi_voices else "",
                      "speech_rate": 1.0, "volume": 1.0},
            "temperature": 0.99, "system_prompt": "", "is_personality": True
        })
        self._update_title()
        self._set_status("New character created.")

    def _open_file(self):
        if self._dirty and not self._confirm_discard():
            return
        path = filedialog.askopenfilename(
            title="Open character JSON",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self._load_file(path)

    def _load_file(self, path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            self._from_dict(data)
            self._current_file = path
            self._dirty = False
            self._update_title()
            self._set_status(f"Loaded: {os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror("Load error", f"Could not load JSON:\n{exc}")

    def _save(self):
        if self._current_file:
            self._write(self._current_file)
        else:
            self._save_as()

    def _save_as(self):
        name = self.var_name.get().strip() or "character"
        safe = "".join(c if c.isalnum() or c in " _-" else "_" for c in name)
        path = filedialog.asksaveasfilename(
            title="Save character JSON",
            defaultextension=".json",
            initialfile=f"{safe.replace(' ', '_')}.json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")])
        if path:
            self._write(path)

    def _write(self, path):
        try:
            data = self._to_dict()
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
            self._current_file = path
            self._dirty = False
            self._update_title()
            self._set_status(f"Saved → {os.path.basename(path)}")
        except Exception as exc:
            messagebox.showerror("Save error", f"Could not save:\n{exc}")

    # ── Misc ──────────────────────────────────────────────────────────────────

    def _clear_prompt(self):
        self.txt_prompt.delete("1.0", "end")
        self._mark_dirty()

    def _confirm_discard(self):
        return messagebox.askyesno(
            "Unsaved changes",
            "You have unsaved changes. Discard them?")

    def _on_close(self):
        if self._dirty and not self._confirm_discard():
            return
        self.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    initial = sys.argv[1] if len(sys.argv) > 1 else None
    app = CharacterEditor(initial_file=initial)
    app.mainloop()