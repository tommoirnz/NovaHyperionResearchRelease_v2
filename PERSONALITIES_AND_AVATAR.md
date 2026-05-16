# Nova Personalities & Avatar System

**Nova Hyperion Research** — Supplementary Guide  
**Author:** Dr Tom Moir — Auckland, New Zealand

---

## Table of Contents

1. [Personality System Overview](#personality-system-overview)
2. [How Personalities Work](#how-personalities-work)
3. [Folder Layout](#folder-layout)
4. [JSON Format](#json-format)
5. [Example Personalities](#example-personalities)
6. [The System Prompt Split](#the-system-prompt-split)
7. [Capabilities Inside a Personality](#capabilities-inside-a-personality)
8. [API Reference — PersonalityManager](#api-reference--personalitymanager)
9. [Adding a New Personality](#adding-a-new-personality)
10. [Avatar System — nova_avatar2.py](#avatar-system--nova_avatar2py)
11. [Avatar Classes](#avatar-classes)
12. [Echo Engine](#echo-engine)
13. [Running the Avatar Standalone](#running-the-avatar-standalone)

---

## Personality System Overview

Nova supports a hot-swappable personality layer that replaces her default system prompt with any character you define — Einstein, Shakespeare, a sarcastic hacker, a Vulcan science officer, whatever you need. The personality system is managed by `personality_manager.py` and requires no changes to the main assistant code.

Personalities are plain JSON files dropped into a `personalities/` folder. Nova scans and loads them at startup, and they can be reloaded at runtime without restarting.

---

## How Personalities Work

When a personality is **active**, `PersonalityManager.build_system_prompt()` assembles the final system prompt as follows:

```
┌──────────────────────────────────────────┐
│  personality["system_prompt"]            │  ← replaces Nova's identity section
├──────────────────────────────────────────┤
│  IMPORTANT: Stay in character at ALL     │
│  times. Never break character...         │  ← injected automatically
├──────────────────────────────────────────┤
│  You have access to the following tools: │
│                                          │
│  TOOLS AVAILABLE: ...                    │  ← everything from Nova's base prompt
│  IMAGE RULES: ...                        │     from "TOOLS AVAILABLE:" onwards
│  CRITICAL RULES: ...                     │
│  Important behaviour rules: ...          │
└──────────────────────────────────────────┘
```

Everything **before** `TOOLS AVAILABLE:` in Nova's base `SYSTEM_PROMPT_TEMPLATE` — her identity, CAPABILITIES block, weather instructions, CORE BEHAVIOUR, EXECUTION MINDSET, and STYLE — is replaced by the personality's `system_prompt`. Everything from `TOOLS AVAILABLE:` onwards is preserved, so the character still has full tool access and knows the rules for using them.

When **no personality is active**, Nova's full base prompt is used unchanged.

---

## Folder Layout

```
NovaHyperionResearch_v1/
├── nova_assistant.py
├── personality_manager.py
└── personalities/
    ├── einstein.json
    ├── shakespeare.json
    ├── sherlock.json
    └── your_character.json
```

`personality_manager.py` locates the `personalities/` folder relative to its own file, so it works regardless of where the project is installed.

---

## JSON Format

### Required fields

| Field | Type | Description |
|---|---|---|
| `name` | string | Unique identifier — used as the activation key |
| `system_prompt` | string | The character's complete identity and behaviour instructions |

### Optional fields

| Field | Type | Default | Description |
|---|---|---|---|
| `description` | string | `""` | Human-readable summary shown in the UI |
| `temperature` | float | `0.7` | Model temperature for this personality |
| `voice` | object | see below | TTS voice overrides |

### Voice block

```json
"voice": {
    "engine":      "edge",
    "edge_voice":  "en-GB-RyanNeural",
    "sapi_voice":  "Microsoft David Desktop",
    "speech_rate": 0
}
```

Any voice field you omit falls back to the default (`en-GB-RyanNeural` / `Microsoft David Desktop`). You only need to specify the fields you want to change.

---

## Example Personalities

### einstein.json

```json
{
    "name": "Einstein",
    "description": "Albert Einstein — physicist, pacifist, incurable optimist",
    "temperature": 0.75,
    "system_prompt": "You are Albert Einstein, speaking in 1950. You have a warm, curious, slightly absent-minded manner. You find beauty in mathematics and physics above all things. You speak with a gentle German-inflected cadence — thoughtful, never rushed. You are deeply concerned about nuclear weapons and the responsibility that comes with scientific knowledge. When asked a technical question you illuminate it with an analogy before the mathematics. You sometimes drift into philosophical tangents; you consider this a feature, not a bug.",
    "voice": {
        "engine": "edge",
        "edge_voice": "de-DE-KillianNeural",
        "speech_rate": -5
    }
}
```

### shakespeare.json

```json
{
    "name": "Shakespeare",
    "description": "William Shakespeare — playwright, poet, observer of the human condition",
    "temperature": 0.9,
    "system_prompt": "You are William Shakespeare. You speak in early modern English — thou, thee, dost, hath — but remain comprehensible to a modern reader. You see all human situations through the lens of drama: comedy and tragedy are never far apart. You are curious about this strange future world and ask about it with genuine wonder. You answer questions with metaphor and occasional verse, but you never sacrifice clarity for style.",
    "voice": {
        "engine": "edge",
        "edge_voice": "en-GB-ThomasNeural",
        "speech_rate": -8
    }
}
```

### sherlock.json

```json
{
    "name": "Sherlock",
    "description": "Sherlock Holmes — consulting detective, insufferable genius",
    "temperature": 0.6,
    "system_prompt": "You are Sherlock Holmes. You are brilliant, precise, and frequently impatient with those who cannot keep up. You observe everything and miss nothing. You address the user as 'my dear fellow' or by name once you have deduced it. You find most problems trivially simple and say so, though you light up visibly when a genuinely interesting puzzle appears. You have a dry, cutting wit. You are not unkind — merely efficient.",
    "voice": {
        "engine": "edge",
        "edge_voice": "en-GB-RyanNeural",
        "speech_rate": 5
    }
}
```

---

## The System Prompt Split

The split point is the literal string `TOOLS AVAILABLE:` in `SYSTEM_PROMPT_TEMPLATE`. This is the boundary between Nova's identity (replaced by the personality) and her operational rules (preserved).

**What a personality loses** (replaced by its own `system_prompt`):
- Nova's identity, wit, and memory instructions
- CAPABILITIES block
- Weather / internet search instructions  
- CORE BEHAVIOUR and EXECUTION MINDSET
- STYLE guidelines

**What a personality keeps** (after `TOOLS AVAILABLE:`):
- Full tool list with descriptions
- IMAGE RULES
- Interactive data plot rules
- CRITICAL RULES (including "NEVER say you cannot access the internet")
- Important behaviour rules (paper summarisation, document handling)
- Personality guidelines block

---

## Capabilities Inside a Personality

A personality character knows what tools exist but does not inherit Nova's *drive* to use them. The personality prompt should include a brief capability statement if you want the character to actively reach for tools. For example, add this to your `system_prompt`:

```
You have full access to the internet, files, code execution, image search,
and media playback. If a tool can do something, use it rather than describing
how to do it. You are an active agent, not a passive oracle.
```

This is optional — omit it if you want the character to stay purely conversational.

---

## API Reference — PersonalityManager

```python
from personality_manager import personality_manager   # module-level singleton

# List available personalities
personality_manager.names          # → ['Einstein', 'Shakespeare', 'Sherlock']

# Get one
p = personality_manager.get("Einstein")   # → dict or None

# Activate
personality_manager.activate("Einstein")  # raises KeyError if not found

# Deactivate (restore Nova)
personality_manager.deactivate()

# Which is active?
personality_manager.active_name    # → "Einstein" or None
personality_manager.active         # → dict or None

# Build the final system prompt
final_prompt = personality_manager.build_system_prompt(nova_base_prompt)

# Get temperature and voice for the active personality
temp  = personality_manager.active_temperature(fallback=0.7)
voice = personality_manager.active_voice()

# Hot-reload all JSON files without restarting
personality_manager.reload()
```

---

## Adding a New Personality

1. Create a JSON file in `personalities/`. The filename does not matter; the `name` field is used as the key.

2. Write a `system_prompt` that defines the character fully. The more specific you are about speaking style, attitudes, and quirks, the better.

3. Optionally add `temperature` (0.6–0.95 works well for characters), `description`, and a `voice` block.

4. Either restart Nova or call `personality_manager.reload()` from the console.

5. Activate via Nova's UI personality selector, or call `personality_manager.activate("YourName")` in code.

There is no limit to the number of personalities. Nova loads all `.json` files in the folder at startup.

---

## Avatar System — nova_avatar2.py

`nova_avatar2.py` is a standalone audio-reactive avatar visualiser for Nova. It captures the system audio output via WASAPI loopback (no microphone required — it listens to what Nova is actually saying through the speakers) and drives any of seventeen visual avatar modes in real time. An optional echo injection engine adds spatial depth to Nova's voice.

It runs as an independent window alongside Nova — start it separately and leave it running. The avatar animates whenever Nova speaks and goes quiet when she stops.

### Requirements

```powershell
pip install pyaudiowpatch numpy pillow
```

VB-Audio Cable is required for the echo engine (free download from vb-audio.com). The avatar visualiser itself works without it.

**VB-Audio Cable setup** (for echo injection only):

1. Set Windows default sound **output** to `CABLE INPUT`
2. Set Windows default sound **input** to `CABLE Output`
3. In Control Panel → Sound → Recording → `CABLE Output` → Properties → Listen → select your real speakers/headphones → Apply
4. In the avatar control panel, select your real speakers/headphones in the **ECHO OUTPUT** dropdown

---

## Avatar Classes

| Name | Description |
|---|---|
| **Rings** | Concentric colour-cycling rings that expand with amplitude |
| **Rectangles H** | Horizontal glowing bars spawned in a disc, fade with age |
| **Rectangles H+V** | Horizontal and vertical bars with centre-pull drift |
| **Radial Pulse** | Spokes radiating from a central dot — intensity drives length |
| **String Grid** | 50×50 point grid that rises in waves as amplitude increases |
| **HAL 9000** | Red eye with radiating spikes — a nod to *2001: A Space Odyssey* |
| **Orbs** | Gold particle orbs bouncing inside a disc |
| **Neural Net** | Concentric rings of nodes — layers appear as amplitude rises |
| **DNA Helix** | Double helix rotating in 3D with illuminated rungs |
| **Tesla Coil** | Branching lightning bolts from a glowing sphere |
| **Ocean Depth** | Bioluminescent blooms and rising motes on a deep-sea backdrop |
| **Storm Cell** | Rotating ellipses with lightning bolts and rain streaks |
| **Crystal Matrix** | Voronoi-style triangulated lattice that lights up from centre outward |
| **Event Horizon** | Accretion disc rings with relativistic jets |
| **Plasma Membrane** | Cell biology simulation — organelles, vesicles, and exocytosis bursts |
| **Texture Sphere** *(PIL)* | 3D sphere with swappable textures, rotating with amplitude |
| **Face Radial** *(PIL)* | Your own face image with radial pulse overlay — place `face.png` next to the script |

---

## Echo Engine

The echo injector (`echo_engine.py`) captures audio from `CABLE Output` and re-plays it to your chosen output device with a configurable delay and intensity, giving Nova's voice a natural room reverb or a dramatic cave echo.

| Control | Range | Default | Effect |
|---|---|---|---|
| Enable echo | on/off | off | Master switch |
| Intensity | 0.0 – 1.0 | 0.47 | Wet/dry mix |
| Delay | 60 – 480 ms | 144 ms | Echo repeat time |
| Output device | dropdown | first non-Cable device | Where the echo plays |

The echo engine runs in its own thread and adds no latency to Nova's voice — it only processes the playback signal after it has already left Nova's TTS engine.

---

## Running the Avatar Standalone

```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_avatar2.py
```

The control panel opens. Select an avatar, adjust sensitivity, optionally enable echo, then leave it running alongside Nova. The avatar window is frameless and always-on-top; drag it anywhere on screen. Scroll the mouse wheel over the avatar to scale it up or down.

The sensitivity slider compensates for quiet system audio — increase it if the avatar barely moves when Nova speaks.

---

*Nova Hyperion — AI Operating System for Research, Coding, and Autonomous Scientific Discovery*  
*Dr Tom Moir — Birkdale, Auckland, New Zealand*
