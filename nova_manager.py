"""
nova_manager.py — Multi-agent manager for Nova Assistant.

Contains ManagerAgent: responsible for analysing, supervising,
and executing multi-agent task plans via the executor.

Usage:
    from nova_manager import ManagerAgent

    self.manager = ManagerAgent(self.ai, logger=self.log, nova=self)
"""

import warnings
from typing import Any
from collections import Counter


class ManagerAgent:
    def __init__(self, ai, logger=None, nova=None):
        """Initialize the ManagerAgent.

        Args:
            ai: AI model instance for generating responses
            logger: Optional logging function
            nova: Reference to the main NovaAssistant instance
        """
        self.ai = ai
        self.log = logger
        self.nova = nova

    SEQUENTIAL_PAIRS: list[tuple[str, str]] = [
        ("research", "code"),
        ("search_and_show_image", "code"),
        ("file_explorer", "text"),
        ("self_inspect", "text"),
    ]
    MAX_AGENTS = 3

    def analyse(self, plan, force_mode=None):
        """
        Validate and sanitise an agent execution plan.

        Args:
            plan:       dict with 'mode' and 'tasks', or a list of task dicts
            force_mode: optional override ('parallel' | 'sequential') applied
                        AFTER safety checks — use with care.
                        If 'parallel' is forced after sequential pairs are detected,
                        a UserWarning is raised.

        Returns:
            Sanitised plan dict. If tasks were truncated, a 'dropped' key
            is added containing the removed task dicts.

        Notes on SEQUENTIAL_PAIRS:
            Pairs are treated as UNORDERED — (A, B) == (B, A).
            Ordering of agents within a sequential plan is determined by the
            planner's task list, not enforced here. If directional enforcement
            is ever needed, it belongs in planner.py, not in analyse().
        """
        # FIX 6: enforce callability of self.log at entry
        assert self.log is None or callable(self.log), \
            f"self.log must be callable or None, got {type(self.log)}"

        # FIX 4 (round 4): MAX_AGENTS must be a positive integer
        assert isinstance(self.MAX_AGENTS, int) and self.MAX_AGENTS > 0, \
            f"MAX_AGENTS must be a positive int, got {self.MAX_AGENTS!r}"

        if isinstance(plan, dict):
            mode = plan.get("mode", "parallel")
            # FIX 4 (round 2): validate mode value from input dict
            if mode not in ("parallel", "sequential"):
                warnings.warn(
                    f"Unknown mode '{mode}' in plan. Defaulting to 'parallel'.",
                    UserWarning,
                    stacklevel=2
                )
                mode = "parallel"
            tasks = plan.get("tasks") or []

        elif isinstance(plan, list):
            # FIX 2 (round 4): explicit list branch — avoids string being iterated as chars
            mode = "parallel"
            tasks = list(plan)

        else:
            # FIX 2 (round 4): reject unknown types cleanly rather than silently becoming []
            raise TypeError(
                f"plan must be a dict or list of task dicts, got {type(plan).__name__}"
            )

        # warn on empty task list
        if not tasks:
            warnings.warn("Plan contains no tasks.", UserWarning, stacklevel=2)

        # ── Collect ALL validation errors before raising ──────────────────────
        errors = []

        for i, t in enumerate(tasks):
            if not isinstance(t, dict):
                errors.append(f"Task {i}: must be a dict, got {type(t).__name__}")
                continue
            if "agent" not in t:
                errors.append(f"Task {i}: missing 'agent' key")
            elif not isinstance(t["agent"], str):
                errors.append(f"Task {i}: 'agent' must be str, got {type(t['agent']).__name__}")
            if not isinstance(t.get("task"), str) or not t.get("task"):
                errors.append(f"Task {i}: 'task' must be a non-empty string")

        if errors:
            raise ValueError("Plan validation failed:\n" + "\n".join(errors))

        # FIX 1: use 'sanitised' to avoid shadowing the input parameter
        sanitised = {"mode": mode, "tasks": list(tasks)}

        # ── Check ALL sequential pairs ────────────────────────────────────────
        # FIX 3 (round 4): guard SEQUENTIAL_PAIRS against missing or None
        # TODO: SEQUENTIAL_PAIRS are currently unordered (A,B) == (B,A).
        # Ordering of agents within a sequential plan is determined by the
        # planner's task list, not enforced here. If directional enforcement
        # is ever needed, it belongs in planner.py, not in analyse().
        pairs = getattr(self, "SEQUENTIAL_PAIRS", None) or []
        triggered_pairs = []
        # all tasks guaranteed to have "agent" key by this point — validated above
        agent_types = {t["agent"] for t in sanitised["tasks"]}
        for a, b in pairs:
            if a in agent_types and b in agent_types:
                triggered_pairs.append((a, b))

        if triggered_pairs:
            sanitised["mode"] = "sequential"
            if self.log:
                self.log(f"[MANAGER] Sequential forced by pairs: {triggered_pairs}")

        # ── Apply force_mode AFTER safety checks ──────────────────────────────
        # FIX 2 (round 2): validate force_mode value and warn if invalid
        if force_mode is not None:
            if force_mode not in ("parallel", "sequential"):
                warnings.warn(
                    f"force_mode='{force_mode}' is not valid. "
                    f"Expected 'parallel' or 'sequential'. Ignoring.",
                    UserWarning,
                    stacklevel=2
                )
            else:
                if force_mode == "parallel" and triggered_pairs:
                    warnings.warn(
                        f"force_mode='parallel' overrides sequential safety enforcement "
                        f"for detected pairs: {triggered_pairs}. Ensure this is intentional.",
                        UserWarning,
                        stacklevel=2
                    )
                sanitised["mode"] = force_mode
                if self.log:
                    self.log(f"[MANAGER] Mode manually overridden to: {force_mode}")

        # ── Warn if duplicate agents would run in parallel ────────────────────
        if sanitised["mode"] == "parallel":
            agent_counts = Counter(t["agent"] for t in sanitised["tasks"])
            duplicates = [a for a, c in agent_counts.items() if c > 1]
            if duplicates:
                warnings.warn(
                    f"Agents running in parallel with duplicate instances: {duplicates}. "
                    f"Verify this is safe.",
                    UserWarning,
                    stacklevel=2
                )

        # ── Cap task count ────────────────────────────────────────────────────
        # FIX 1 (round 4): capture original count BEFORE truncation
        if len(sanitised["tasks"]) > self.MAX_AGENTS:
            original_count = len(sanitised["tasks"])
            dropped = sanitised["tasks"][self.MAX_AGENTS:]
            sanitised["tasks"] = sanitised["tasks"][:self.MAX_AGENTS]
            sanitised["dropped"] = dropped
            dropped_names = [t["agent"] for t in dropped]
            if self.log:
                self.log(
                    f"[MANAGER] ⚠️ Truncated to {self.MAX_AGENTS}. "
                    f"Dropped: {dropped_names}"
                )
            warnings.warn(
                f"Task list truncated from {original_count} to {self.MAX_AGENTS}. "
                f"Dropped agents: {dropped_names}",
                UserWarning,
                stacklevel=2
            )

        if self.log:
            self.log(f"[MANAGER] Mode: {sanitised['mode']} | Tasks: {len(sanitised['tasks'])}")

        return sanitised

    def execute(
        self,
        plan: dict,
        executor: Any,
        internet_ctx: str = "",
        history_str: str = "",
    ) -> list:
        """Dispatch tasks to the executor in the mode specified by the plan."""
        tasks = plan.get("tasks", [])
        mode  = plan.get("mode", "parallel")

        if not tasks:
            if self.log:
                self.log("[MANAGER] No tasks to execute — returning empty list")
            return []

        # FIX: guard executor calls — log and re-raise on failure
        try:
            if mode == "parallel":
                if self.log:
                    self.log(f"[MANAGER] Running {len(tasks)} tasks in parallel")
                return executor.run_tasks(tasks, internet_ctx, history_str)

            if self.log:
                self.log(f"[MANAGER] Running {len(tasks)} tasks sequentially")
            return executor.run_tasks_sequential(tasks, internet_ctx, history_str)

        except Exception as e:
            if self.log:
                self.log(f"[MANAGER] ❌ Executor failed ({mode}): {e}")
            raise

    def supervise(self, results, user_input):
        """Merge multiple agent results into one coherent answer."""
        clean_results = [
            r for r in results
            if r
               and not str(r).startswith("[RUNNING CODE")
               and not str(r).startswith("[AGENT ERROR]")
               and not str(r).strip().startswith("```python")
               and "import numpy" not in str(r)[:100]
               and "import plotly" not in str(r)[:100]
        ]

        if not clean_results:
            return None

        if len(clean_results) == 1:
            return clean_results[0]

        combined = "\n\n".join(
            f"[RESULT {i + 1}]\n{r}" for i, r in enumerate(clean_results)
        )

        # FIX: guard build_env_context call
        env_ctx = ""
        if self.nova:
            try:
                env_ctx = self.nova.build_env_context()
            except Exception as e:
                if self.log:
                    self.log(f"[MANAGER] ⚠️ build_env_context failed: {e}")

        prompt = f"""
{env_ctx}

You are a supervisor AI.

User question:
{user_input}

Agent results:
{combined}

Tasks:
- Remove contradictions
- Merge into one detailed and comprehensive answer
- Preserve important facts, numbers, and explanations
- DO NOT over-summarise
- ALWAYS include source links if present
- Preserve URLs exactly
- Add a "Sources:" section at the end with links
- If a sympy_exec result is present, use THAT as the verification —
  do NOT invent or substitute your own verification
- NEVER use illustrative code snippets from math explanations as verification
- Verification means the actual computed result from sympy_exec only
- NEVER invent or fabricate source links
- If a result came from sympy_exec, say "Verified locally using SymPy" — no link needed
- Only include URLs that actually appeared in the agent results
- CRITICAL: If any result contains [IMAGE:filename], [AUDIO:path], [VIDEO:path] or [PLOT:filename] tags, preserve them EXACTLY as written — do NOT convert to markdown image syntax or change the path
- NEVER invent image filenames — only use [IMAGE:...] tags that appear verbatim in the agent results
- Do NOT extract image URLs from sources and turn them into [IMAGE:...] tags
- Place any [IMAGE:...] tag at the very start of your response, before any other text
- NEVER invent [PLOT:] tags — only include [PLOT:filename] if that exact tag appears verbatim in the agent results
Final answer:
"""
        # FIX: guard AI call
        try:
            return self.ai.generate(prompt, use_planning=False)
        except Exception as e:
            if self.log:
                self.log(f"[MANAGER] ❌ supervise AI call failed: {e}")
            return clean_results[0]  # fallback to first result

    def supervise_plan(self, plan, user_input):
        """Validate and improve the plan BEFORE execution.

        Note: Sequential pair enforcement here mirrors analyse() intentionally —
        supervise_plan runs pre-execution as an early guard, analyse() runs
        at validation time. If both run, sequential mode is enforced twice
        which is harmless. Task cap here uses MAX_AGENTS for consistency.
        """
        if self.log:
            self.log("[SUPERVISOR] Reviewing plan before execution")

        tasks  = plan.get("tasks", [])
        agents = [t.get("agent") for t in tasks]

        # Respect planner's media decisions — never override
        if len(tasks) == 1 and agents[0] in [
            "play_local_music", "play_local_video", "play_youtube_video"
        ]:
            if self.log:
                self.log(f"[SUPERVISOR] Respecting planner → {agents[0]}")
            return plan

        # Ensure research runs before code
        if "research" in agents and "code" in agents:
            plan["mode"] = "sequential"
            priority = {
                "research": 0,
                "file_explorer": 1,
                "search_and_show_image": 2,
                "code": 3,
                "text": 4
            }
            tasks = sorted(tasks, key=lambda t: priority.get(t["agent"], 99))
            plan["tasks"] = tasks
            if self.log:
                self.log("[SUPERVISOR] Enforced order: research → code")

        # FIX: cap uses MAX_AGENTS for consistency with analyse()
        # previously used hardcoded MAX_TASKS=4 which conflicted
        if len(tasks) > self.MAX_AGENTS:
            plan["tasks"] = tasks[:self.MAX_AGENTS]
            if self.log:
                self.log(f"[SUPERVISOR] Trimmed tasks → {self.MAX_AGENTS}")

        # FIX: guard self.nova.tools access — check both nova and tools exist
        available_tools = []
        if self.nova and hasattr(self.nova, "tools") and self.nova.tools:
            try:
                available_tools = self.nova.tools.list_tools()
            except Exception as e:
                if self.log:
                    self.log(f"[SUPERVISOR] ⚠️ Could not list tools: {e}")

        for i, t in enumerate(tasks):
            agent = t.get("agent")
            job = t.get("task", "").lower()

            # Don't redirect code tasks that are about audio programming
            is_audio_programming = any(w in job for w in [
                "sounddevice", "pygame.mixer", "frequency", "sine wave",
                "waveform", "generate audio", "synthesize", "oscillator",
                "matplotlib", "plotly", "scipy"
            ])

            if agent in ["code", "file_explorer"] and not is_audio_programming:
                if any(w in job for w in ["play", "open", "launch", "start"]):
                    if any(w in job for w in ["video", "film", "movie", "mp4", "mkv"]):
                        if "play_local_video" in available_tools:
                            tasks[i] = {"agent": "play_local_video", "task": job}
                            if self.log:
                                self.log("[SUPERVISOR] Redirected code → play_local_video")
                    elif any(w in job for w in ["music", "song", "mp3", "track"]):
                        if "play_local_music" in available_tools:
                            tasks[i] = {"agent": "play_local_music", "task": job}
                            if self.log:
                                self.log("[SUPERVISOR] Redirected code → play_local_music")

        plan["tasks"] = tasks
        return plan