"""
nova_ai.py — AI engine for Nova Assistant.

Contains WorkingAI: the core model interface supporting both local
Ollama models and cloud models via OpenRouter, plus the ReAct agent
loop, PDF extraction, and error/mistake caching.

Usage:
    from nova_ai import WorkingAI

    self.ai = WorkingAI(model=None, logger=self.log)
"""

import json
import os
import re
import time

import requests

from datetime import datetime
from mistake_memory import MistakeMemory
from Internet_Tools import InternetTools


# ──────────────────────────────────────────────────────────────────────────────
# PDF HELPERS  (used only by WorkingAI.react_agent)
# ──────────────────────────────────────────────────────────────────────────────

def resolve_pdf_url(url):
    """Convert an arXiv abstract URL or DOI link to a direct PDF URL."""
    import re as _re
    m = _re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", url, _re.I)
    if m:
        # NOTE: Springer DOI redirect — may 404 for non-Springer DOIs
        # A more robust solution would use https://doi.org/{doi} for resolution
        return f"https://link.springer.com/content/pdf/{m.group(0)}.pdf"
    if "arxiv.org/abs/" in url:
        return url.replace("/abs/", "/pdf/") + ".pdf"
    if "arxiv.org/pdf/" in url:
        return url
    if url.endswith(".pdf"):
        return url
    return url


def download_pdf(url, filename="downloaded_paper.pdf"):
    """Download a PDF from *url* into the downloads/ folder and return the local path."""
    import requests as _requests
    os.makedirs("downloads", exist_ok=True)
    filename = os.path.join("downloads", os.path.basename(filename))
    r = _requests.get(url, timeout=30)
    r.raise_for_status()
    with open(filename, "wb") as f:
        f.write(r.content)
    return filename


class WorkingAI:
    """Core AI engine supporting local Ollama and cloud OpenRouter models."""

    DEFAULT_SYSTEM_PROMPT = (
        "You are Nova, a persistent AI assistant with memory across sessions. "
        "Conversation history is provided to you and is real — treat it as genuine recalled memory. "
        "NEVER say you have no memory of previous conversations. "
        "NEVER say each conversation starts fresh. "
        "When asked what was discussed before, reference the history you have been given."
    )

    def __init__(self, model=None, logger=None):
        self.token_limit_callback = None
        self.token_callback = None
        self.log = logger
        self.affect = None
        self.cloud_config = None
        self.cloud_model_ids = set()
        try:
            with open("config.json", "r") as f:
                cfg = json.load(f)
            self.cache_dir = cfg["cache_directory"]
            self.cache_file = os.path.join(self.cache_dir, cfg["error_cache_file"])
            self._error_disk_cache = {}
            self.cache_max_age_days = cfg.get("cache_max_age_days", 300)
            self.cache_max_entries = cfg.get("cache_max_entries", 1000)
            self.cloud_config = cfg.get("cloud_models", None)
            if self.cloud_config:
                env_key = os.getenv("OPENROUTER_KEY", "").strip()
                if env_key:
                    self.cloud_config["api_key"] = env_key
                    for m in self.cloud_config.get("models", []):
                        self.cloud_model_ids.add(m["id"])
                    if self.log:
                        self.log(f"[AI] Cloud models: {len(self.cloud_model_ids)} "
                                 f"via {self.cloud_config.get('provider', '?')}")
                else:
                    if self.log:
                        self.log("[AI] ⚠️  OPENROUTER_KEY missing or empty — cloud models disabled.")
                    self.cloud_config = None
            self.model = model or cfg.get("default_model", "ministral-3:latest")
            self.max_tokens = cfg.get("max_tokens", 16000)
            self.system_prompt = cfg.get("system_prompt", self.DEFAULT_SYSTEM_PROMPT)
            os.makedirs(self.cache_dir, exist_ok=True)
        except Exception as e:
            if self.log:
                self.log(f"[AI] Config error: {e}")
            self.model = model or "ministral-3:latest"
            self.cache_dir = None
            self.cache_file = None
            self._error_disk_cache = {}
            self.max_tokens = 16000
            self.system_prompt = self.DEFAULT_SYSTEM_PROMPT
        self.current_temperature = 0.3  # FIX: was always falling back to default via getattr
        self._load_disk_cache()
        self.mistake_memory = MistakeMemory(cache_dir=self.cache_dir, logger=self.log)
        # NOTE: these must be injected externally after construction
        # e.g. self.ai.token_callback = self._on_token_count
        self.internet = InternetTools(log_callback=self.log)
        if self.log:
            self.log("[AI] Internet tools ready")
    def set_affect(self, affect_instance):
        """Inject emotional state engine."""
        self.affect = affect_instance
        if self.log:
            self.log("[AI] Affect engine connected")

    def _encode_image(self, image_path):
        """Encode an image file to base64 string."""
        import base64
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _build_affect_context(self) -> str:
        """Add emotional state to system prompt."""
        if not self.affect:
            return ""
        try:
            state = self.affect.get_state()
            # Get top 2 strongest emotions
            top = sorted(state.items(), key=lambda x: x[1], reverse=True)[:2]
            active = [f"{k} ({v:.2f})" for k, v in top if v > 0.1]
            if not active:
                return ""
            return f"\n\nCURRENT EMOTIONAL STATE: {', '.join(active)}. Let this subtly colour your tone."
        except Exception as e:
            if self.log:
                self.log(f"[AI] Affect error: {e}")
            return ""
    #--------------------------------------------------------------------------
    # MODEL ROUTING
    # ──────────────────────────────────────────────────────────────────────────

    def _is_cloud_model(self, name):
        """Return True if *name* refers to a cloud/OpenRouter model."""
        return name in self.cloud_model_ids or name.startswith("☁") or name.startswith("cloud:")

    # ──────────────────────────────────────────────────────────────────────────
    # GENERATION
    # ──────────────────────────────────────────────────────────────────────────

    def generate(self, prompt, use_planning=True, image_path=None, temperature=None):
        temp = temperature if temperature is not None else self.current_temperature
        if self.log:
            self.log(f"[GENERATE] temp={temp} model={self.model}")
        """Generate a response, optionally prefixed with a reasoning plan."""
        skip_keywords = [
            "Return ONLY Python code",
            "Fix this Python error",
            "Category:",
            "Does answering this question require",
            "Generate COMPLETE updated code"
        ]
        skip_planning = any(k in prompt for k in skip_keywords) or "PLAN:" in prompt

        if not use_planning or skip_planning or len(prompt) < 120:
            if self._is_cloud_model(self.model):
                return self._generate_cloud(prompt, temperature=0.5, image_path=image_path)
            return self._generate_ollama(prompt, temperature=0.5, image_path=image_path)

        plan_prompt = f"""
    You are an expert reasoning assistant.

    User request:
    {prompt}

    Briefly plan the best way to answer this request.

    Rules:
    - Return ONLY a numbered list
    - Maximum 5 steps
    - One short sentence per step
    - No headings
    - No explanations
    - Do NOT give the final answer
    """
        if self._is_cloud_model(self.model):
            plan = self._generate_cloud(plan_prompt, temperature=0.5)
        else:
            plan = self._generate_ollama(plan_prompt, temperature=0.5)

        answer_prompt = f"""
    Follow this reasoning plan to answer the user's request.

    PLAN:
    {plan}

    USER REQUEST:
    {prompt}

    Write a detailed and complete answer.

    Guidelines:
    - Preserve important details
    - Include key facts and explanations
    - Do NOT over-summarise
    """
        if self._is_cloud_model(self.model):
            return self._generate_cloud(prompt, temperature=temp, image_path=image_path)
        return self._generate_ollama(answer_prompt, temperature=0.5, image_path=image_path)

    def _generate_ollama(self, prompt, temperature=None, image_path=None):
        """Send a prompt to the local Ollama server and return the response text."""
        temp = temperature if temperature is not None else self.current_temperature
        if self.log:
            self.log(f"\n📤 [Ollama] → {self.model} (temp={temp})")
        try:
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temp, "num_predict": 4000}
            }
            if image_path and os.path.exists(image_path):
                b64 = self._encode_image(image_path)
                payload["images"] = [b64]
                if self.log:
                    self.log(f"[AI] Ollama vision — image attached: {os.path.basename(image_path)}")

            r = requests.post(
                "http://localhost:11434/api/generate",
                json=payload,
                timeout=400
            )
            if r.status_code != 200:
                return ""
            try:
                return r.json().get("response", "")
            except Exception:
                return ""
        except Exception as e:
            if self.log:
                self.log(f"❌ Ollama: {e}")
            return ""

    def _generate_cloud(self, prompt, temperature=None, system_prompt=None, image_path=None):
        """Send a prompt to the configured cloud provider and return the response text."""
        if not self.cloud_config:
            if self.log:
                self.log("❌ No cloud config")
            return ""

        api_key = self.cloud_config.get("api_key", "")
        base_url = self.cloud_config.get("base_url", "https://openrouter.ai/api/v1")
        provider = self.cloud_config.get("provider", "openrouter")

        if not api_key:
            if self.log:
                self.log(f"❌ No API key for {provider}")
            return ""

        model_id = self.model.lstrip("☁ ").strip()
        if self.log:
            self.log(f"\n☁ [{provider}] → {model_id}")

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        if provider == "openrouter":
            headers["HTTP-Referer"] = "https://novaassistant.local"
            headers["X-Title"] = "NovaAssistant"

        temp = temperature if temperature is not None else getattr(self, "current_temperature", 0.3)

        # Build messages with system prompt
        messages = []

        sys_text = system_prompt or getattr(self, "system_prompt", "")
        if sys_text:
            affect_ctx = self._build_affect_context()
            full_system = sys_text + affect_ctx
            messages.append({"role": "system", "content": full_system})

        if image_path and os.path.exists(image_path):
            ext = os.path.splitext(image_path)[1].lower()
            mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".gif": "image/gif",
                    ".webp": "image/webp"}.get(ext, "image/jpeg")
            b64 = self._encode_image(image_path)
            user_message = {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt}
                ]
            }
            if self.log:
                self.log(f"[AI] Vision — image attached: {os.path.basename(image_path)}")
        else:
            user_message = {"role": "user", "content": prompt}

        messages.append(user_message)

        payload = {
            "model": model_id,
            "messages": messages,
            "temperature": temp,
            "max_tokens": self.max_tokens
        }

        # ──────────────────────────────────────────────────────────────────────────
        # RETRY LOGIC with exponential backoff
        # ──────────────────────────────────────────────────────────────────────────
        last_exception = None

        for attempt in range(3):
            try:
                r = requests.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=300
                )

                # Handle rate limiting (429)
                if r.status_code == 429:
                    wait = 2 ** attempt
                    if self.log:
                        self.log(f"[AI] Rate limited (429), waiting {wait}s... (attempt {attempt + 1}/3)")
                    time.sleep(wait)
                    continue

                # Handle moderation block (403)
                if r.status_code == 403:
                    if self.log:
                        self.log(f"[AI] Moderation block (403): {r.text[:200]}")
                    return ""

                if r.status_code != 200:
                    if self.log:
                        self.log(f"❌ Cloud {r.status_code}: {r.text[:200]}")
                    return ""

                data = r.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content") or ""

                # Debug logging
                if self.log:
                    self.log(
                        f"[DEBUG] content type: {type(content)}, repr: {repr(content[:200] if content else content)}")

                # Safety check for non-string or empty content
                if not isinstance(content, str) or not content.strip():
                    original_type = type(content)
                    content = str(content) if content is not None else ""
                    if self.log:
                        self.log(f"[WARNING] Non-string content converted from: {original_type}")
                    if not content.strip():
                        if self.log:
                            self.log(f"[WARNING] Empty response — possible moderation block")
                        return ""

                if self.log:
                    u = data.get("usage", {})
                    self.log(f"☁ {u.get('prompt_tokens', '?')} in / {u.get('completion_tokens', '?')} out tokens")
                    if self.token_callback:
                        self.token_callback(
                            u.get("prompt_tokens", 0),
                            u.get("completion_tokens", 0),
                            model_id
                        )
                    tout = u.get("completion_tokens", "?")
                    if isinstance(tout, int) and tout >= self.max_tokens:
                        self.log("⚠️ MAX TOKENS HIT")
                        if self.token_limit_callback:
                            self.token_limit_callback()

                # Strip internal reasoning and agent scaffolding tags
                content = re.sub(r"<think(?:ing)?>.*?</think(?:ing)?>", "", content, flags=re.DOTALL)
                content = re.sub(r"<tool_call>.*?</tool_call>", "", content, flags=re.DOTALL)
                content = re.sub(r"<tool_response>.*?</tool_response>", "", content, flags=re.DOTALL)
                content = content.strip()

                # ── Update affect from response ──
                if self.affect:
                    try:
                        self.affect.update(content)
                    except Exception as e:
                        if self.log:
                            self.log(f"[AI] Affect update error: {e}")

                return content

            except requests.exceptions.Timeout as e:
                if self.log:
                    self.log(f"❌ Cloud timeout (attempt {attempt + 1}/3)")
                last_exception = e
                time.sleep(1)

            except requests.exceptions.ConnectionError as e:
                if self.log:
                    self.log(f"❌ Connection error (attempt {attempt + 1}/3): {e}")
                last_exception = e
                time.sleep(1)

            except requests.exceptions.RequestException as e:
                if self.log:
                    self.log(f"❌ Request error (attempt {attempt + 1}/3): {e}")
                last_exception = e
                time.sleep(1)

            except Exception as e:
                if self.log:
                    self.log(f"❌ Cloud error: {e}")
                raise  # Non-retriable, bail immediately

        # If we get here, all 3 attempts failed
        if last_exception:
            if self.log:
                self.log(f"❌ All 3 attempts failed. Last error: {last_exception}")
            raise last_exception

        return ""
    # ──────────────────────────────────────────────────────────────────────────
    # CODE GENERATION
    # ──────────────────────────────────────────────────────────────────────────

    def generate_code(self, task, error_context=None, error_type=None):
        """Generate Python code for *task*, optionally guided by a prior error."""
        has_prev = "PREVIOUS CONTEXT:" in task
        if has_prev:
            prompt = f"""You are a Python coding expert with memory.
Today's date is {datetime.now().strftime("%A %d %B %Y")}.
{task}
Generate COMPLETE updated code. Never use emoji in matplotlib text.
Return ONLY Python code in ```python ... ``` block:"""

        elif error_context and error_type:
            prompt = f"""Fix this Python error.
ERROR: {error_type}
DETAILS: {error_context[:300]}
TASK: {task}
Return ONLY Python code in ```python ... ``` block:"""

        else:
            has_maths = bool(re.search(
                r"MATPLOTLIB MATHTEXT|\\frac|\\int|\\sqrt|\\arctan", task))
            mathtext_rule = """
- ALL matplotlib text (titles, labels, legends, ax.text) MUST use mathtext r'$...$' notation
- NEVER use plain text for maths: use r'$x^2$' not 'x^2'
- Use r'$\\frac{a}{b}$' for fractions, r'$\\sqrt{x}$' for roots""" if has_maths else ""

            prompt = f"""You are a Python coding assistant.

Today's date is {datetime.now().strftime("%A %d %B %Y")}.
TASK: {task}
- Never use emoji in matplotlib text
- If INTERNET DATA is included, use those variables directly{mathtext_rule}
IMPORTANT RULES:
1. If LOCAL IMAGE FILES are provided in the context, you MUST display them.
2. Do NOT generate synthetic graphics if real images exist.
3. Prefer local files over downloading new ones.

MATPLOTLIB LAYOUT RULES (CRITICAL):
1. ALWAYS call plt.tight_layout()
2. If using a main title, use: plt.suptitle("Title", y=0.98)
3. NEVER set suptitle y > 1.0
4. DO NOT use plt.subplots_adjust() or plt.tight_layout(rect=...)
5. Use ONLY plt.tight_layout()
6. Ensure all titles, labels, and legends are fully visible

Return ONLY Python code in ```python ... ``` block:"""

        return self.generate(prompt, use_planning=True)

    # ──────────────────────────────────────────────────────────────────────────
    # REACT AGENT
    # ──────────────────────────────────────────────────────────────────────────

    def react_agent(self, user_prompt, tools, history="", internet_ctx="", max_steps=6):
        """Run the ReAct agent loop, calling tools as needed to answer *user_prompt*."""
        if hasattr(self, "internet_indicator_callback"):
            self.internet_indicator_callback(True)

        recent_actions      = []
        last_pdf_observation = ""

        try:
            for step in range(max_steps):
                if self.log:
                    self.log(f"[AGENT STEP {step + 1}/{max_steps}] Thinking...")

                pdf_block = f"""
════════════════════════════════════
RETRIEVED PAPER — USE THIS EXACTLY
════════════════════════════════════
{last_pdf_observation}

YOU MUST:
- Use the Title EXACTLY as it appears above
- Use the Authors EXACTLY as they appear above
- Summarise ONLY the text above
- DO NOT substitute any other paper
════════════════════════════════════
""" if last_pdf_observation else ""

                prompt = f"""
{pdf_block}
You are an AI agent that can solve problems using external tools.

────────────────────────────────────
INTERNET CONTEXT (PRIMARY SOURCE)
────────────────────────────────────
{internet_ctx}

CRITICAL INTERNET RULE:
- The Internet context above ALREADY contains retrieved real-world data
- You MUST use it as your PRIMARY source
- DO NOT ignore it
- If the Internet context is NOT EMPTY, extract the answer directly from it
- DO NOT call search if relevant data exists in the context

EVIDENCE RULE:
- When stating specific facts, ensure they are explicitly present in the context
- If not clearly supported, soften the claim: "reports indicate", "sources suggest"
- ALWAYS include URLs when they are present in the context

────────────────────────────────────
SYSTEM DATE (ABSOLUTE)
────────────────────────────────────
- The provided date is REAL and MUST be trusted
- NEVER override it with training knowledge

────────────────────────────────────
PAPER SUMMARISATION RULE (MANDATORY)
────────────────────────────────────
- When read_pdf returns an observation, Title and Authors are GROUND TRUTH
- Copy them EXACTLY — NEVER substitute a different paper
- Summarise ONLY that text

────────────────────────────────────
TASK EXECUTION RULES
────────────────────────────────────
- You are executing ONE task from a planner
- DO NOT break into sub-tasks or create a new plan
- Choose ONE best action each step

────────────────────────────────────
TOOLS
────────────────────────────────────
search(query)
read_url(url)
read_pdf(url)
fetch_js(url)
────────────────────────────────────
PAPER DOWNLOAD RULE (MANDATORY)
────────────────────────────────────
- For ANY arXiv URL use read_pdf
- For ANY URL ending in .pdf use read_pdf
- For ANY DOI link use read_pdf
- NEVER use read_url for PDFs

────────────────────────────────────
FORMAT
────────────────────────────────────
Thought: reasoning
Action: tool_name(argument)

OR

Final: answer

────────────────────────────────────
RECENT CONVERSATION
────────────────────────────────────
{history}

────────────────────────────────────
TASK
────────────────────────────────────
{user_prompt}

If Internet context contains relevant data → go directly to Final answer.
"""
                response = self.generate(prompt, use_planning=False)
                if not response:
                    return "No response from model."

                # Truncate runaway responses
                if len(response) > 8000:
                    if "Final:" in response:
                        response = "Final:" + response.split("Final:")[-1]
                    elif "Action:" in response:
                        action_part = response.split("Action:")[-1].strip()
                        if action_part and "(" in action_part:
                            response = response.split("Action:")[0] + "Action:" + action_part.split("\n")[0]
                        else:
                            response = response.split("Action:")[0].strip()
                    if self.log:
                        self.log("[AGENT] ⚠️ Truncated runaway response")

                has_final  = "Final:"  in response
                has_action = "Action:" in response

                if has_final and not has_action:
                    return response.split("Final:")[-1].strip()

                if has_final and has_action:
                    response = response.split("Final:")[0].strip()

                if "Action:" not in response:
                    return response.strip()

                # Parse action
                try:
                    action_line = response.split("Action:")[1].strip().split("\n")[0]
                    tool = action_line.split("(")[0].strip().lower()
                    arg  = action_line.split("(", 1)[1].rsplit(")", 1)[0].strip().strip('"').strip("'")
                    if arg.lower().startswith("url:"):   arg = arg[4:].strip()
                    if arg.lower().startswith("query:"): arg = arg[6:].strip()
                except Exception:
                    return response

                # Loop detection
                action_key = f"{tool}:{arg[:80]}"
                if action_key in recent_actions:
                    if self.log:
                        self.log(f"[AGENT] ⚠️ Loop detected: {action_key}")
                    return "I was unable to find the information after multiple attempts."
                recent_actions.append(action_key)
                if len(recent_actions) > 6:
                    recent_actions.pop(0)

                if self.log:
                    self.log(f"[TOOL] {tool} -> {arg[:80]}")

                # Tool execution
                observation = ""
                if tool in ["search", "read_url", "read_pdf","fetch_js"]:
                    if self.log:
                        self.log(f"[INTERNET] 🌐 Agent using tool: {tool}")
                    try:
                        if tool == "search":
                            observation = tools._brave_search(arg, count=3)
                        elif tool == "read_url":
                            observation = tools.fetch_url(arg)
                        elif tool == "fetch_js":
                            observation = tools.fetch_js_url(arg)
                        elif tool == "read_pdf":
                            pdf_url = resolve_pdf_url(arg)
                            path    = download_pdf(pdf_url)
                            observation = self.extract_pdf_text(path, max_chars=8000)
                    except Exception as e:
                        observation = f"{tool.upper()}_ERROR: {e}"
                else:
                    observation = f"Unknown tool: {tool}"

                print(f"\n=== TOOL USED: {tool} ===\n{observation[:500]}\n=== END OBSERVATION ===\n")

                observation = observation[:6000]
                history += f"\n{response}\n\nObservation:\n{observation}\n"

                if tool == "read_pdf":
                    extracted_title   = ""
                    extracted_authors = ""
                    for line in observation.splitlines():
                        l = line.strip()
                        if l.lower().startswith("title:")   and not extracted_title:
                            extracted_title   = l.split(":", 1)[1].strip()
                        elif l.lower().startswith("authors:") and not extracted_authors:
                            extracted_authors = l.split(":", 1)[1].strip()

                    summary_prompt = f"""Write a 3-4 sentence summary of this research paper.

PAPER TEXT:
{observation[:6000]}

Write only the summary paragraph.
Do NOT include a title line or authors line — just the summary.
"""
                    summary = self.generate(summary_prompt, use_planning=False)
                    return (
                        f"**Title:** {extracted_title}\n"
                        f"**Authors:** {extracted_authors}\n\n"
                        f"{summary or observation}"
                    )

            return "Agent could not complete the task."

        finally:
            if hasattr(self, "internet_indicator_callback"):
                self.internet_indicator_callback(False)

    # ──────────────────────────────────────────────────────────────────────────
    # PDF EXTRACTION
    # ──────────────────────────────────────────────────────────────────────────

    def extract_pdf_text(self, path, max_chars=100000):
        """Extract plain text from a PDF file, up to *max_chars* characters."""
        import fitz
        try:
            doc = fitz.open(path)
            text_parts = [page.get_text() for page in doc]
            return "\n".join(text_parts).strip()[:max_chars]
        except Exception as e:
            return f"PDF_READ_ERROR: {e}"
    # ──────────────────────────────────────────────────────────────────────────
    # ERROR CACHE
    # ──────────────────────────────────────────────────────────────────────────

    def _load_disk_cache(self):
        """Load the persistent error-search cache from disk, evicting stale entries."""
        if not self.cache_file or not os.path.exists(self.cache_file):
            return
        try:
            with open(self.cache_file, "r", encoding="utf-8") as f:
                raw = json.load(f)

            # FIX: evict by age
            max_age = getattr(self, "cache_max_age_days", 300) * 86400
            now = time.time()
            raw = {k: v for k, v in raw.items()
                   if now - v.get("timestamp", 0) < max_age}

            # FIX: evict by count — keep newest entries
            max_entries = getattr(self, "cache_max_entries", 1000)
            if len(raw) > max_entries:
                sorted_entries = sorted(raw.items(),
                                        key=lambda x: x[1].get("timestamp", 0),
                                        reverse=True)
                raw = dict(sorted_entries[:max_entries])

            self._error_disk_cache = raw
            if self.log:
                self.log(f"[AI] Cache loaded: {len(self._error_disk_cache)} entries")
        except Exception:
            self._error_disk_cache = {}

    def _save_disk_cache(self):
        """Persist the error-search cache to disk."""
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(self._error_disk_cache, f, indent=2)
        except Exception:
            pass

    def _get_error_cache_key(self, error_type, query):
        """Build a cache key from error type and package name."""
        pkg = self._extract_package_name(query)
        return f"{error_type.lower()}::{pkg.lower()}" if pkg else error_type.lower()

    def _get_cached_error_search(self, error_type, query):
        """Return cached search results for this error type, or None."""
        key = self._get_error_cache_key(error_type, query)
        if key in self._error_disk_cache:
            return self._error_disk_cache[key].get("results")
        for pattern in [error_type.lower(), error_type.lower().replace("error", "")]:
            for k in self._error_disk_cache:
                if pattern in k:
                    return self._error_disk_cache[k].get("results")
        return None

    def _cache_error_search(self, error_type, query, results):
        """Store search results in the error cache and flush to disk."""
        key = self._get_error_cache_key(error_type, query)
        self._error_disk_cache[key] = {"results": results, "timestamp": time.time()}
        self._save_disk_cache()

    def _extract_package_name(self, query):
        """Extract a known Python package name from *query*, or return None."""
        if not query:
            return None
        packages = [
            "matplotlib", "numpy", "scipy", "pandas", "sympy",
            "tensorflow", "torch", "sklearn", "keras", "flask",
            "django", "requests", "beautifulsoup4", "seaborn",
            "plotly", "tkinter", "pygame", "pyqt5", "cv2", "pillow",
            "pydub", "librosa", "soundfile", "pyaudio", "pyopengl", "ffmpeg"
        ]
        ql = str(query).lower()
        for p in packages:
            if re.search(r"\b" + re.escape(p) + r"\b", ql):
                return p
        for p in packages:
            if p in ql:
                return p
        return None
