import copy
from concurrent.futures import ThreadPoolExecutor
import re
import os
from typing import List, Any, Dict
import shutil

class AgentExecutor:

    def __init__(self, nova):
        self.nova = nova
        self._correction_attempted = False

    # ─────────────────────────────────────────
    # PARALLEL EXECUTION
    # ─────────────────────────────────────────
    def run_tasks(self, tasks, internet_ctx="", history_str=""):
        """
        Dispatch tasks in parallel or sequential mode.
        Sequential mode passes context between steps.
        """
        if not tasks:
            self.nova.log("[EXECUTOR] No tasks to run")
            return []

        mode = "parallel"
        if isinstance(tasks, dict):
            mode = tasks.get("mode", "parallel")
            tasks = tasks.get("tasks", [])

        self.nova.log(f"[EXECUTOR] mode={mode}, tasks={len(tasks)}, history_str_len={len(history_str)}")

        if mode == "sequential":
            return self.run_tasks_sequential(tasks, internet_ctx=internet_ctx, history_str=history_str)

        # ── Parallel execution ───────────────────────────────────────────────
        results = []
        for task in tasks:
            result = self._run_agent(task, internet_ctx=internet_ctx, history_str=history_str)
            results.append(result)
        return results

    def run_tasks_sequential(self, tasks: List[Dict[str, Any]], internet_ctx: str = "", history_str: str = "") -> List[
        Any]:
        results = []
        accumulated_context = history_str

        for i, task in enumerate(tasks):
            self.nova.log(
                f"[EXECUTOR] Sequential step {i + 1}/{len(tasks)}: {task.get('agent')} — {task.get('task', '')[:80]}")

            result = self._run_agent(task, internet_ctx=internet_ctx, history_str=accumulated_context)
            results.append(result)

            # Inject this step's result into context for the next step
            if result and isinstance(result, str):
                # Use higher limit for text/research results that may be written to file
                max_len = 8000 if task.get('agent') in ['text', 'research'] else 1200
                step_summary = f"\n\n[Step {i + 1} result — agent: {task.get('agent')}, task: {task.get('task', '')}]\n{result[:max_len]}"
                accumulated_context = accumulated_context + step_summary
                self.nova.log(f"[EXECUTOR] Context updated after step {i + 1}: +{len(step_summary)} chars")
            else:
                self.nova.log(f"[EXECUTOR] Step {i + 1} returned no result — context unchanged")

        return results

    def _run_agent(self, task, internet_ctx="", history_str=""):
        """
        Execute a single agent task

        Args:
            task: Dictionary with 'agent' and 'task' keys
            internet_ctx: Internet context string
            history_str: Conversation history to provide context
        """
        agent = task.get("agent", "text")
        job = task.get("task", "")

        self.nova.log(f"[DEBUG] RUN AGENT → {agent}")

        formatted_history = ""
        if history_str and agent in ["text", "math", "research"]:
            formatted_history = self._format_history_for_agent(history_str)
            self.nova.log(f"[AGENT] {agent} received {len(formatted_history)} chars of history")

        try:
            tool_map = {
                "play_local_music": "play_local_music",
                "play_local_video": "play_local_video",
                "youtube_tools": "play_youtube_video",
                "file_explorer": "file_explorer",
                "open_webpage": "open_webpage",
                "self_inspect": "self_inspect",
                "search_and_show_image": "search_and_show_image"
            }

            if agent == "file_explorer":
                job = self._translate_file_command(job)

            # ── TOOL EXECUTION ─────────────────
            if agent in tool_map:
                tool_name = tool_map[agent]
                self.nova.log(f"[TOOL EXEC] {agent} → {tool_name}")

                if tool_name == "search_and_show_image":
                    clean_job = job.lower()

                    count_map = {"two": 2, "three": 3, "four": 4, "five": 5,
                                 "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
                    requested_count = 6
                    for word, num in count_map.items():
                        if word in clean_job:
                            requested_count = num
                            break
                    digit_match = re.search(r'\b(\d+)\b', clean_job)
                    if digit_match:
                        requested_count = int(digit_match.group(1))

                    strip_phrases = [
                        "find", "search for", "get", "download", "fetch",
                        "images of", "pictures of", "photos of", "image of",
                        "four", "three", "two", "five", "six",
                        "and put them on a poster", "for a poster", "poster",
                        "collage", "display", "layout", "arrange",
                        "and display", "and show", "and arrange"
                    ]
                    for phrase in strip_phrases:
                        clean_job = clean_job.replace(phrase, "")

                    and_pos = clean_job.find(" and ")
                    if and_pos != -1:
                        after_and = clean_job[and_pos + 5:]
                        instruction_words = ["put", "place", "make", "create", "build", "arrange",
                                             "display", "show", "use", "combine", "design"]
                        if any(after_and.startswith(w) for w in instruction_words):
                            clean_job = clean_job[:and_pos]

                    clean_job = re.sub(r'\s+', ' ', clean_job).strip()
                    clean_job = f"{requested_count} {clean_job}"
                    self.nova.log(f"[IMAGE SEARCH] Cleaned query: '{clean_job}' count={requested_count}")

                    return self.nova.tools.run(
                        tool_name,
                        clean_job,
                        self.nova.ai.internet,
                        self.nova.image_dir,
                    )

                elif tool_name == "open_webpage":
                    return self.nova.tools.run(
                        tool_name,
                        job,
                        internet_tools=self.nova.ai.internet
                    )

                else:
                    return self.nova.tools.run(tool_name, job)

            # ── DIAGRAM ────────────────────────
            if agent == "diagram":
                self.nova.log(f"[AGENT] diagram → {job}")
                result = self.nova.tools.run("diagram", job, self.nova.ai)
                if isinstance(result, str) and result.startswith("DIAGRAM:"):
                    path = result.split(":", 1)[1].strip()
                    self.nova.root.after(0, lambda p=path: self.nova.show_graphviz_diagram(p))
                    return "[DIAGRAM GENERATED]"
                return result or "[DIAGRAM FAILED]"

            # ── WRITE FILE ─────────────────────
            if agent == "write_file":
                path_match = re.search(
                    r'\bto\s+([A-Za-z]:[/\\][^\n\s]+\.[\w]+)\s*$',
                    job,
                    re.IGNORECASE
                )
                if not path_match:
                    self.nova.log("[WRITE_FILE] No file path found in task")
                    return "❌ Write failed: No file path found in task"

                file_path = path_match.group(1).strip().rstrip('.,;)\'"')

                if "TASK:" in job:
                    task_body = job.split("TASK:", 1)[1].strip()
                else:
                    task_body = job

                if "TASK:" in job and len(task_body.split("\n")[0]) < 200:
                    context_block = job.split("TASK:")[0]
                    context_block = re.sub(
                        r'^CONTEXT FROM PREVIOUS INSPECTION:\s*',
                        '',
                        context_block,
                        flags=re.IGNORECASE
                    ).strip()
                    content = context_block
                else:
                    content = re.sub(
                        r'^.*?[A-Za-z]:[/\\][^\n]+\.[\w]+\s*:?\s*',
                        '',
                        task_body,
                        flags=re.IGNORECASE | re.DOTALL
                    ).strip()

                content = re.sub(r"^```[\w]*\n?", "", content)
                content = re.sub(r"\n?```$", "", content).strip()

                if len(content) < 50 and history_str:
                    candidates = []

                    step_matches = re.findall(
                        r'\[Step \d+ result — agent: \w+, task: [^\]]+\]\n(.*?)(?=\[Step \d+|\Z)',
                        history_str,
                        re.DOTALL
                    )
                    candidates.extend([m.strip() for m in step_matches])

                    history_match = re.search(
                        r'Assistant:\s*(.*?)(?=User:|$)',
                        history_str,
                        re.DOTALL
                    )
                    if history_match:
                        candidates.append(history_match.group(1).strip())

                    if candidates:
                        best = max(candidates, key=len)
                        if len(best) > len(content):
                            content = best
                            self.nova.log(f"[WRITE_FILE] Using best candidate ({len(content)} chars)")

                if '\\n' in content and '\n' not in content:
                    content = content.encode('utf-8').decode('unicode_escape')

                self.nova.log(f"[WRITE_FILE] → {file_path} ({len(content)} chars)")
                return self.nova.tools.run("write_file", file_path, content)

            # ── RESEARCH ───────────────────────
            if agent == "research":
                job = re.sub(r'\b\w+:\S+\s*', '', job).strip()

                research_prompt = job
                if formatted_history:
                    research_prompt = f"""CONTEXT FROM RECENT CONVERSATION:
{formatted_history}

CURRENT RESEARCH QUERY:
{job}

Use the context to understand what information is being sought.
"""

                return self.nova.ai.react_agent(
                    research_prompt,
                    self.nova.ai.internet,
                    history=self.nova.build_recent_history(),
                    internet_ctx=internet_ctx,
                    max_steps=6
                )


            # ── CODE ───────────────────────────
            if agent == "code":
                self.nova.log("[CODE] Generating + executing")

                # Check if research results are in the accumulated context
                has_research = any(x in history_str for x in [
                    "Step 1 result", "http://", "https://", "wikimedia", "URL"
                ])

                if has_research:
                    code_prompt = f"""VERIFIED RESOURCES FROM PREVIOUS RESEARCH STEP:
        {history_str[-4000:]}

        CODE REQUEST:
        {job}

        CRITICAL: Use ONLY the URLs provided in the research results above.
        Do NOT construct, guess, or modify any URLs. Copy them exactly as shown.
        """
                elif formatted_history:
                    code_prompt = f"""CONTEXT FROM RECENT CONVERSATION:
        {formatted_history}

        CODE REQUEST:
        {job}

        Generate Python code that addresses the request in the context of the conversation.
        """
                else:
                    code_prompt = job

                # ── Web display rules — always appended ──
                code_prompt += """

        IMPORTANT OUTPUT RULES FOR THIS SYSTEM:
        - NEVER use plt.show() — it blocks execution
        - For matplotlib: save using plt.savefig() to web_images/ folder
        - Use: import os, time; os.makedirs('web_images', exist_ok=True)
        - Filename: f'web_images/plot_{int(time.time()*1000)}.png'
        - Save with: plt.savefig(filename, dpi=100, bbox_inches='tight'); plt.close()
        - For Plotly: save to plots/ as HTML using fig.write_html(), never call fig.show()
        - For GUI apps (tkinter, pygame): run normally — no file save needed
        - WIKIMEDIA DOWNLOADS: NEVER use urllib.request — always use requests with headers:
          headers = {"User-Agent": "Mozilla/5.0 (compatible; NovaBot/1.0)"}
          response = requests.get(url, headers=headers, timeout=10)
        - After download, ALWAYS verify: os.path.exists(path) and os.path.getsize(path) > 1000
        - Add time.sleep(1) between image downloads to avoid HTTP 429
        - NEVER emit [IMAGE:filename] tags for files that failed to download
        - Use Wikimedia API for verified URLs, never construct thumbnail URLs manually
        """

                code = self.nova.ai.generate_code(code_prompt)
                self.nova.code_window.set_code(code)

                def _update_preview(c=code):
                    try:
                        clean = re.sub(r"```(?:python)?\s*", "", c)
                        clean = re.sub(r"```", "", clean).strip()
                        self.nova.code_display.config(state="normal")
                        self.nova.code_display.delete("1.0", "end")
                        self.nova.code_display.insert("1.0", clean)
                        self.nova.code_display.see("1.0")
                        self.nova.code_display.config(state="disabled")
                    except Exception as e:
                        self.nova.log(f"[CODE PREVIEW] {e}")

                self.nova.root.after(0, _update_preview)

                import threading

                def run_code():
                    success, output, attempts, meta = self.nova.smart_loop.run(code)

                    if success:
                        import glob, time
                        from datetime import datetime

                        # Check for fresh Plotly HTML
                        html_files = glob.glob("plots/*.html")
                        if html_files:
                            latest = max(html_files, key=os.path.getctime)
                            if time.time() - os.path.getmtime(latest) < 60:
                                filename = os.path.basename(latest)
                                self.nova.conversation_history.append({
                                    "role": "assistant",
                                    "content": f"[PLOT:{filename}]",
                                    "timestamp": datetime.now().strftime('%H:%M')
                                })
                                self.nova.log(f"[CODE AGENT] Plotly HTML injected: {filename}")
                                return

                        # Check for fresh matplotlib PNG
                        png_files = (glob.glob("plots/*.png") + glob.glob("web_images/*.png") +
                                     glob.glob("plots/*.gif") + glob.glob("web_images/*.gif") +
                                     glob.glob("web_images/*.jpg") + glob.glob("web_images/*.jpeg"))
                        if png_files:
                            latest = max(png_files, key=os.path.getctime)
                            if time.time() - os.path.getmtime(latest) < 60:

                                filename = os.path.basename(latest)
                                web_path = os.path.join("web_images", filename)
                                if not latest.startswith("web_images"):
                                    shutil.copy2(latest, web_path)
                                self.nova.conversation_history.append({
                                    "role": "assistant",
                                    "content": f"[IMAGE:{filename}]",
                                    "timestamp": datetime.now().strftime('%H:%M')
                                })
                                self.nova.log(f"[CODE AGENT] Matplotlib PNG injected: {filename}")
                                return

                    result = output if success else f"[CODE FAILED] {output}"
                    self.nova.root.after(
                        0,
                        lambda: self.nova._deliver_tool_result(result)
                    )

                threading.Thread(target=run_code, daemon=True).start()
                return "[RUNNING CODE...]"

            # ── SYMPY ──────────────────────────
            if agent == "sympy_exec":
                self.nova.log("[SYMPY] Generating SymPy code...")
                code = self.nova.ai.generate(
                    f"Write executable Python SymPy code only.\n"
                    f"Task: {job}\n"
                    f"Requirements:\n"
                    f"- ONLY Python code, no English text anywhere\n"
                    f"- No comments, no explanations, no prose\n"
                    f"- Define all variables with symbols()\n"
                    f"- End with print(latex(result))\n"
                    f"- If you write anything other than Python code the program will crash",
                    use_planning=False
                )
                code = re.sub(r"```(?:python)?\s*", "", code)
                code = re.sub(r"```", "", code).strip()

                header = "from sympy import *\nfrom sympy import latex\n"
                if "from sympy" not in code:
                    code = header + code
                else:
                    code = "from sympy import latex\n" + code

                result = self.nova.tools.run("sympy_exec", code)
                if result:
                    clean = result.replace("**SymPy Verification Result:**", "").strip()
                    clean = clean.replace("$$", "").strip()
                    return f"**SymPy Verification Result:**\n\n$$\n{clean}\n$$"
                return "SymPy returned no result"

            # ── MATH ───────────────────────────
            if agent == "math":
                math_prompt = job
                if formatted_history:
                    math_prompt = f"""CONTEXT FROM RECENT CONVERSATION:
{formatted_history}

MATH QUERY:
{job}

IMPORTANT: Do NOT include Python or SymPy code examples. Use LaTeX notation only.
Verification is handled separately.
"""
                math_prompt += """Before finalising your answer, check your working by substituting
back into the original equation or problem. If anything looks wrong,
correct it before responding. Show your checking step explicitly.
"""
                return self.nova.ai.generate(math_prompt, use_planning=False)
            # ── GEOMETRY ───────────────────────────────────────────────
            if agent == "plot_geometry":
                self.nova.log("[GEOMETRY] Rendering figure...")
                result = self.nova.tools.run("plot_geometry", job)
                return result

            # ── READ LOG ────────────────────────────────────────────────
            if agent == "read_log":
                self.nova.log("[READ_LOG] Nova reading own log...")
                result = self.nova.tools.run("read_log", job)
                return result

            # ── TEXT / FALLBACK ─────────────────
            if agent == "text":
                text_prompt = job
                if formatted_history:
                    text_prompt = f"""RECENT CONVERSATION HISTORY:
{formatted_history}

CURRENT TASK:
{job}

Complete the task using the context from the conversation history. If this is a follow-up question, reference what was discussed.
IMPORTANT: Respond in plain prose only. Do NOT write Python code, shell commands, or any executable code.
"""
                self.nova.log(f"[TEXT AGENT] Prompt length: {len(text_prompt)} chars")
                return self.nova.ai.generate(text_prompt, use_planning=False)

            return self.nova.ai.generate(job, use_planning=False)

        except Exception as e:
            return f"[AGENT ERROR] {agent}: {e}"


    # ─────────────────────────────────────────
    # HISTORY FORMATTING
    # ─────────────────────────────────────────
    def _format_history_for_agent(self, history_str, max_exchanges=50):
        """
        Format conversation history for agent consumption

        Args:
            history_str: Raw history string or JSON
            max_exchanges: Maximum number of exchanges to include

        Returns:
            Formatted history string
        """
        if not history_str:
            return ""

        try:
            import json
            if isinstance(history_str, str) and (
                    history_str.strip().startswith('{') or history_str.strip().startswith('[')):
                data = json.loads(history_str)
                if isinstance(data, dict) and 'history' in data:
                    exchanges = []
                    for entry in data['history'][-max_exchanges:]:
                        task = entry.get('task', '')
                        result = entry.get('result', '')
                        if len(result) > 500:
                            result = result[:500] + "..."
                        exchanges.append(f"User: {task}\nAssistant: {result}")
                    return "\n\n".join(exchanges)

        except (json.JSONDecodeError, ValueError, KeyError):
            pass
        if isinstance(history_str, str):
            if len(history_str) > 10000:
                return history_str[:10000] + "\n...[truncated]"
            return history_str

        return str(history_str)

    # ─────────────────────────────────────────
    # FILE COMMAND NORMALIZATION
    # ─────────────────────────────────────────
    def _translate_file_command(self, text):
        text = (text or "").lower().strip()

        noise_phrases = [
            "contents of", "directory of", "folder of", "files in",
            "files and folders in", "list files in",
            "list files and folders in", "show files in",
            "show contents of", "display contents of",
            "display files in", "and folders", "files and",
        ]

        for phrase in noise_phrases:
            text = text.replace(phrase, "")

        text = text.strip()

        if re.match(r"^[a-z]:/", text):
            return f"list {text}"

        if text.startswith("list"):
            parts = text.split()
            for p in parts:
                if re.match(r"^[a-z]:/", p):
                    return f"list {p}"

        if "text file" in text or ".txt" in text:
            return "find *.txt in C:/Users/OEM/Desktop"

        if "desktop" in text and "list" in text:
            return "list C:/Users/OEM/Desktop"

        return text