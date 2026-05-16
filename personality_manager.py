"""
personality_manager.py  –  Nova Personality System
====================================================
Drop this file next to nova_web.py.

Folder layout expected:
    <nova_root>/
        personalities/
            einstein.json
            shakespeare.json
            ...
        personality_manager.py

Each JSON must have at minimum:  name, system_prompt
Optional fields:  description, temperature, voice { engine, edge_voice, speech_rate }
"""

import json
import os
import glob
import logging
import threading  # FIX 5: thread safety

logger = logging.getLogger(__name__)

# ── Default / fallback voice so Nova keeps working if a personality has no voice block ──
DEFAULT_VOICE = {
    "engine": "edge",
    "edge_voice": "en-GB-RyanNeural",
    "sapi_voice": "Microsoft David Desktop",
    "speech_rate": 0,
}

DEFAULT_TEMPERATURE = 0.7


class PersonalityManager:
    """Loads personality JSON files and tracks the active personality."""

    def __init__(self, personalities_dir: str | None = None):
        if personalities_dir is None:
            base = os.path.dirname(os.path.abspath(__file__))
            personalities_dir = os.path.join(base, "personalities")

        self.personalities_dir = personalities_dir
        self._personalities: dict[str, dict] = {}
        self._active_name: str | None = None
        self._lock = threading.Lock()  # FIX 5: thread safety lock

        self._load_all()

    # ──────────────────────────────────────────────
    # Loading
    # ──────────────────────────────────────────────

    def _load_all(self):
        """Scan personalities/ and load every .json file found."""
        new_personalities: dict[str, dict] = {}

        if not os.path.isdir(self.personalities_dir):
            logger.warning(f"[Personalities] Folder not found: {self.personalities_dir}")
            with self._lock:
                self._personalities.clear()
            return

        pattern = os.path.join(self.personalities_dir, "*.json")
        files = sorted(glob.glob(pattern))

        for path in files:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                name = data.get("name", "").strip()
                if not name:
                    logger.warning(f"[Personalities] Skipping {path}: no 'name' field")
                    continue
                if "system_prompt" not in data:
                    logger.warning(f"[Personalities] Skipping {name}: no 'system_prompt'")
                    continue

                # FIX 2: dedup guard — warn if name already seen in this load pass
                if name in new_personalities:
                    logger.warning(
                        f"[Personalities] Duplicate name '{name}' in {path} — skipping, "
                        f"keeping first loaded."
                    )
                    continue

                # Normalise optional fields so callers never have to check
                data.setdefault("description", "")
                data.setdefault("temperature", DEFAULT_TEMPERATURE)
                data.setdefault("voice", DEFAULT_VOICE.copy())
                data["voice"] = {**DEFAULT_VOICE, **data["voice"]}

                new_personalities[name] = data
                logger.info(f"[Personalities] Loaded: {name}")

            except Exception as e:
                logger.error(f"[Personalities] Failed to load {path}: {e}")

        # FIX 5: atomic swap under lock
        with self._lock:
            self._personalities = new_personalities
            # FIX 2 (continued): if active personality was removed, deactivate cleanly
            if self._active_name and self._active_name not in self._personalities:
                logger.warning(
                    f"[Personalities] Active personality '{self._active_name}' no longer "
                    f"exists after reload — deactivating."
                )
                self._active_name = None

        logger.info(f"[Personalities] Total loaded: {len(self._personalities)}")

    def reload(self):
        """Hot-reload all personality files (useful during development)."""
        self._load_all()

    # ──────────────────────────────────────────────
    # Queries
    # ──────────────────────────────────────────────

    @property
    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._personalities.keys())

    @property
    def all(self) -> list[dict]:
        with self._lock:
            return [self._personalities[n] for n in sorted(self._personalities.keys())]

    def get(self, name: str) -> dict | None:
        with self._lock:
            return self._personalities.get(name)

    @property
    def active(self) -> dict | None:
        with self._lock:
            if self._active_name:
                return self._personalities.get(self._active_name)
            return None

    @property
    def active_name(self) -> str | None:
        with self._lock:
            return self._active_name

    # ──────────────────────────────────────────────
    # Activation
    # ──────────────────────────────────────────────

    def activate(self, name: str) -> dict:
        """
        Set the active personality by name.
        Returns the personality dict.
        Raises KeyError if name not found.
        """
        with self._lock:
            if name not in self._personalities:
                raise KeyError(f"Personality '{name}' not found. Available: {sorted(self._personalities.keys())}")
            self._active_name = name
            result = self._personalities[name]
        logger.info(f"[Personalities] Active → {name}")
        return result

    def deactivate(self):
        """Return Nova to her default (no personality override)."""
        with self._lock:
            self._active_name = None
        logger.info("[Personalities] Deactivated — Nova restored to default")

    # ──────────────────────────────────────────────
    # Helpers for callers
    # ──────────────────────────────────────────────

    def build_system_prompt(self, nova_base_prompt: str) -> str:
        p = self.active  # thread-safe via property
        if p is None:
            return nova_base_prompt or ""

        nova_base_prompt = nova_base_prompt or ""  # FIX 4: guard against None

        # FIX 1: correct else branch — extract tools section OR fall back to full prompt
        split_marker = "TOOLS AVAILABLE:"
        if split_marker in nova_base_prompt:
            tools_section = nova_base_prompt[nova_base_prompt.find(split_marker):]
        else:
            tools_section = ""  # FIX 1: was incorrectly assigning full prompt here

        # FIX 3: removed hardcoded "Never refer to yourself as Nova or as an AI assistant"
        # — that instruction breaks Nova's identity when she's just adjusting tone, not
        #   fully roleplaying. Callers can add it explicitly in the JSON system_prompt
        #   if a full character persona is intended.
        identity_note = (
            "\n\nIMPORTANT: Stay in character at ALL times. Never break character.\n\n"
        )

        if tools_section:
            return (
                p["system_prompt"]
                + identity_note
                + "You have access to the following tools:\n\n"
                + tools_section
            )
        else:
            # No tools section found — just prepend personality to base prompt
            return p["system_prompt"] + identity_note + nova_base_prompt

    def active_temperature(self, fallback: float = DEFAULT_TEMPERATURE) -> float:
        p = self.active
        return p["temperature"] if p else fallback

    def active_voice(self) -> dict:
        p = self.active
        return p["voice"] if p else DEFAULT_VOICE.copy()


# ── Module-level singleton ─────────────────────────────────────────────────────
personality_manager = PersonalityManager()
