"""
nova_math_researcher.py
=======================
Persistent background math research loop for Nova.
Dashboard  → http://localhost:8082
Notifies Nova → POST https://localhost:8080/api/research_alert  (Option 2)
Sends email  → via Nova research hooks                           (Option 3)
"""

import asyncio
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Optional

import httpx
import sympy as sp
from dotenv import load_dotenv
load_dotenv()

# Ignore this if you are just using the main NOVA Hyperion  AI as it won't run unless you make it!
# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_BASE           = "http://localhost:11434"
OLLAMA_MODEL          = "qwen2.5:14b" #Change if you so wish
OPENROUTER_KEY        = os.getenv("OPENROUTER_KEY", "")
OPENROUTER_MODEL      = "anthropic/claude-sonnet-4-5"

JOURNAL_PATH          = Path("research_journal.json")
DIGEST_PATH           = Path("research_digest.txt")
LOG_PATH              = Path("nova_math_researcher.log")
DASHBOARD_PORT        = 8082

# Nova web server — researcher will POST alerts here
NOVA_ALERT_URL        = "https://localhost:8080/api/research_alert"
NOVA_ALERT_SECRET     = os.getenv("NOVA_ALERT_SECRET", "nova-research-secret")

LOOP_INTERVAL_S       = 10
NUMERICAL_TRIALS      = 2000
ESCALATION_THRESHOLD  = 200

RESEARCH_DOMAINS = [
    "number theory (primes, divisibility, modular arithmetic)",
    "combinatorial identities and binomial coefficients",
    "integer sequences and recurrence relations",
    "connections between signal processing and number theory",
    "inequalities involving floor and ceiling functions",
    "properties of Fibonacci-like sequences",
    "Diophantine equations with small solutions",
    "connections between continued fractions and irrational numbers",
    "connections between control theory and discrete mathematics",
    "properties of polynomial roots and coefficients",
]

# ---------------------------------------------------------------------------
# Live status dict
# ---------------------------------------------------------------------------

STATUS = {
    "state":       "Starting up...",
    "phase":       "idle",
    "domain":      "",
    "conjecture":  "",
    "progress":    0,
    "cycle_count": 0,
    "found_count": 0,
    "started":     datetime.now().isoformat(),
    "last_cycle":  "",
    "next_cycle":  "",
    "log_tail":    [],
}


def update_status(**kwargs):
    STATUS.update(kwargs)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

class TailHandler(logging.Handler):
    def emit(self, record):
        line = self.format(record)
        STATUS["log_tail"].append(line)
        if len(STATUS["log_tail"]) > 14:
            STATUS["log_tail"].pop(0)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
        TailHandler(),
    ],
)
log = logging.getLogger("NovaMathResearcher")

# ---------------------------------------------------------------------------
# Research Journal
# ---------------------------------------------------------------------------

class ResearchJournal:
    def __init__(self, path: Path = JOURNAL_PATH):
        self.path = path
        if not self.path.exists():
            self.path.write_text("[]", encoding="utf-8")

    def _load(self) -> list:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def append(self, entry: dict):
        entries = self._load()
        entry["timestamp"] = datetime.now().isoformat()
        entries.append(entry)
        self.path.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def today_entries(self) -> list:
        today = date.today().isoformat()
        return [e for e in self._load() if e.get("timestamp", "").startswith(today)]

    def recent_survivors(self, n: int = 6) -> list:
        all_e     = self._load()
        survivors = [e for e in all_e if e.get("status") in ("verified", "escalated", "proved")]
        return survivors[-n:]

# ---------------------------------------------------------------------------
# Notify Nova (Option 2 — POST to Nova's alert endpoint)
# ---------------------------------------------------------------------------

ALERT_FILE = Path("research_alert.json")   # Nova polls for this file

async def notify_nova(finding: dict):
    """
    Write research_alert.json so Nova's ResearchWatcher picks it up.
    Nova is a Tkinter app — it polls this file every 30s via root.after().
    Non-fatal if write fails.
    """
    log.info(f"Verification dict: {finding.get('verification')}")
    payload = {
        "status":     finding.get("status", "verified"),
        "conjecture": finding.get("conjecture", {}).get("conjecture", ""),
        "domain":     finding.get("conjecture", {}).get("domain", ""),
        "cases":      finding.get("verification", {}).get("passed", 0),
        "arxiv":      finding.get("arxiv", ""),
        "proof":      finding.get("proof_attempt", "") or "",
        "timestamp":  finding.get("timestamp", datetime.now().isoformat()),
    }
    try:
        ALERT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info(f"Alert file written → {ALERT_FILE}")
    except Exception as e:
        log.warning(f"Could not write alert file: {e}")

# ---------------------------------------------------------------------------
# Dashboard HTTP server
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>Nova Math Researcher</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#000;color:#fff;font-family:'Courier New',monospace;padding:20px;font-size:14px}}
h1{{color:#ff9900;font-size:1.3em;letter-spacing:4px;text-transform:uppercase;border-bottom:2px solid #ff9900;padding-bottom:8px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.panel{{background:#0d0d1a;border:1px solid #223;border-radius:6px;padding:14px}}
.panel-title{{color:#9999ff;font-size:.72em;letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;border-bottom:1px solid #223;padding-bottom:5px}}
.row{{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #181828;font-size:.83em}}
.lbl{{color:#778}}.val{{color:#ff9900;font-weight:bold}}
.val.g{{color:#66cc66}}.val.b{{color:#9999ff}}.val.r{{color:#cc6666}}
.pbar{{height:12px;background:#181828;border-radius:6px;margin:8px 0;overflow:hidden}}
.pfill{{height:100%;background:#ff9900;border-radius:6px}}
.cbox{{background:#08080f;border-left:3px solid #ff9900;padding:8px 12px;font-size:.8em;line-height:1.55;color:#ccc;margin-top:8px;min-height:55px;word-break:break-word}}
.logbox{{font-size:.7em;line-height:1.65;color:#667788}}
.logbox .w{{color:#cc6666}}.logbox .i{{color:#556677}}
.finding{{background:#081008;border-left:3px solid #66cc66;padding:7px 11px;margin-bottom:7px;font-size:.79em;line-height:1.5}}
.badge{{display:inline-block;padding:1px 8px;border-radius:3px;font-size:.68em;font-weight:bold;margin-bottom:3px;letter-spacing:2px;text-transform:uppercase}}
.bv{{background:#1a3a1a;color:#66cc66}}.be{{background:#1a2a3a;color:#9999ff}}.bp{{background:#3a2200;color:#ff9900}}
.phase-idle{{color:#556}}.phase-generating{{color:#9999ff}}.phase-verifying{{color:#ff9900}}
.phase-arxiv{{color:#bb88ff}}.phase-escalating{{color:#cc6666}}.phase-notifying{{color:#66cc66}}
.footer{{font-size:.72em;color:#334;margin-top:14px;text-align:right}}
</style>
</head>
<body>
<h1>&#9733; Nova Math Researcher</h1>
<div class="grid">

<div class="panel">
  <div class="panel-title">System Status</div>
  <div class="row"><span class="lbl">Phase</span><span class="val phase-{phase}">{phase_upper}</span></div>
  <div class="row"><span class="lbl">Cycles run</span><span class="val">{cycle_count}</span></div>
  <div class="row"><span class="lbl">Survivors</span><span class="val g">{found_count}</span></div>
  <div class="row"><span class="lbl">Last cycle</span><span class="val b">{last_cycle}</span></div>
  <div class="row"><span class="lbl">Next cycle</span><span class="val b">{next_cycle}</span></div>
  <div class="row"><span class="lbl">Local model</span><span class="val">{model}</span></div>
  <div class="row"><span class="lbl">Nova alert</span><span class="val g">ENABLED</span></div>
</div>

<div class="panel">
  <div class="panel-title">Current Activity</div>
  <div class="row"><span class="lbl">Domain</span><span class="val" style="font-size:.8em;max-width:60%;text-align:right">{domain}</span></div>
  <div class="row"><span class="lbl">State</span><span class="val">{state}</span></div>
  <div style="margin-top:8px;font-size:.72em;color:#778">Verification progress</div>
  <div class="pbar"><div class="pfill" style="width:{progress}%"></div></div>
  <div style="font-size:.72em;color:#667;margin-bottom:6px">{progress}% of {trials} cases</div>
  <div class="panel-title" style="margin-top:8px">Active Conjecture</div>
  <div class="cbox">{conjecture}</div>
</div>

<div class="panel">
  <div class="panel-title">Live Log</div>
  <div class="logbox">{log_lines}</div>
</div>

<div class="panel">
  <div class="panel-title">Recent Survivors</div>
  {findings_html}
</div>

</div>
<div class="footer">Started: {started} &nbsp;|&nbsp; Refreshes every 5s &nbsp;|&nbsp; Nova alerts active</div>
</body>
</html>"""


def build_dashboard(journal: ResearchJournal) -> str:
    phase     = STATUS["phase"]
    survivors = journal.recent_survivors(5)

    if survivors:
        parts = []
        for s in reversed(survivors):
            st = s.get("status", "verified")
            bc = {"verified": "bv", "escalated": "be", "proved": "bp"}.get(st, "bv")
            text = s.get("conjecture", {}).get("conjecture", "")[:200]
            v    = s.get("verification", {})
            ts   = s.get("timestamp", "")[:16]
            parts.append(
                f'<div class="finding">'
                f'<span class="badge {bc}">{st.upper()}</span><br>'
                f'{text}<br>'
                f'<span style="color:#445;font-size:.85em">Cases: {v.get("passed","?")} &nbsp;|&nbsp; {ts}</span>'
                f'</div>'
            )
        findings_html = "".join(parts)
    else:
        findings_html = '<div style="color:#334;font-size:.85em;padding:8px">No survivors yet.</div>'

    log_lines = ""
    for line in STATUS["log_tail"]:
        css  = "w" if "[WARNING]" in line or "[ERROR]" in line else "i"
        safe = line.replace("&", "&amp;").replace("<", "&lt;")
        log_lines += f'<div class="{css}">{safe}</div>'
    if not log_lines:
        log_lines = '<div class="i">No log entries yet.</div>'

    next_cycle = STATUS.get("next_cycle", "")
    if next_cycle:
        try:
            secs = int((datetime.fromisoformat(next_cycle) - datetime.now()).total_seconds())
            next_cycle = f"in {max(0, secs)}s"
        except Exception:
            pass

    last_cycle = STATUS.get("last_cycle", "")
    if last_cycle:
        last_cycle = last_cycle[11:19]

    return DASHBOARD_HTML.format(
        phase=phase, phase_upper=phase.upper(),
        cycle_count=STATUS["cycle_count"], found_count=STATUS["found_count"],
        last_cycle=last_cycle or "—", next_cycle=next_cycle or "—",
        model=OLLAMA_MODEL, domain=STATUS["domain"][:45] or "—",
        state=STATUS["state"], progress=STATUS["progress"],
        trials=NUMERICAL_TRIALS, conjecture=STATUS["conjecture"][:280] or "Waiting...",
        log_lines=log_lines, findings_html=findings_html,
        started=STATUS["started"][:16],
    )


def make_handler(journal: ResearchJournal):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/status.json":
                body = json.dumps(STATUS, default=str).encode()
                ct   = "application/json"
            else:
                body = build_dashboard(journal).encode("utf-8")
                ct   = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    return Handler


def start_dashboard_server(journal: ResearchJournal):
    server = HTTPServer(("0.0.0.0", DASHBOARD_PORT), make_handler(journal))
    Thread(target=server.serve_forever, daemon=True).start()
    log.info(f"Dashboard → http://localhost:{DASHBOARD_PORT}")

# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

async def ollama_generate(prompt: str, system: str = "", timeout: int = 120) -> str:
    payload = {
        "model":   OLLAMA_MODEL,
        "prompt":  prompt,
        "system":  system,
        "stream":  False,
        "options": {"temperature": 0.8, "num_predict": 1024},
    }
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(f"{OLLAMA_BASE}/api/generate", json=payload)
        r.raise_for_status()
        return r.json().get("response", "").strip()

# ---------------------------------------------------------------------------
# Claude / OpenRouter client
# ---------------------------------------------------------------------------

async def claude_generate(prompt: str, system: str = "", timeout: int = 180) -> str:
    if not OPENROUTER_KEY:
        return "[OpenRouter key not configured]"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":      OPENROUTER_MODEL,
        "max_tokens": 2048,
        "messages":   [{"role": "user", "content": prompt}],
    }
    if system:
        payload["system"] = system
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers, json=payload,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()

# ---------------------------------------------------------------------------
# arXiv novelty check
# ---------------------------------------------------------------------------

async def arxiv_check(summary: str) -> str:
    query = summary[:80].replace(" ", "+")
    url   = f"https://export.arxiv.org/find/math/1/ti:+AND+{query}/0/1/0/all/0/1"
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r      = await client.get(url)
            titles = re.findall(r'<span class="descriptor">Title:</span>\s*(.*?)</div>', r.text, re.DOTALL)
            titles = [re.sub(r'<[^>]+>', '', t).strip() for t in titles[:3]]
            return "; ".join(titles) if titles else "No closely matching papers found"
    except Exception as e:
        return f"arXiv unavailable: {e}"

# ---------------------------------------------------------------------------
# Conjecture generation
# ---------------------------------------------------------------------------

CONJECTURE_SYSTEM = """\
You are a creative mathematics research assistant.
Propose one original, testable mathematical conjecture.
Rules:
1. Be precise and unambiguous.
2. Express it as a Python function `def test(n):` returning True/False.
3. Use only stdlib + sympy imports inside the function.
4. Be non-trivial but plausible.

Respond ONLY with valid JSON (no markdown, no preamble):
{
  "conjecture": "English statement",
  "domain": "Mathematical domain",
  "python_test": "def test(n):\\n    import sympy as sp\\n    ...",
  "motivation": "Why this might be true"
}"""


async def generate_conjecture(domain: str) -> Optional[dict]:
    raw   = await ollama_generate(f"Conjecture domain: {domain}", system=CONJECTURE_SYSTEM)
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        log.warning("No JSON in conjecture output")
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        # Ollama sometimes puts raw \n \t inside JSON strings — fix them
        try:
            fixed = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', match.group())
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            log.warning(f"JSON error: {e}")
            return None
# ---------------------------------------------------------------------------
# Numerical verification
# ---------------------------------------------------------------------------

def safe_exec_test(code: str, n: int) -> Optional[bool]:
    ns = {"sp": sp, "sympy": sp}
    try:
        exec(code, ns)
        fn = ns.get("test")
        return bool(fn(n)) if fn else None
    except Exception:
        return None


async def verify_conjecture(conjecture: dict, trials: int = NUMERICAL_TRIALS) -> dict:
    code      = conjecture.get("python_test", "")
    passed    = 0
    failed_at = []
    none_count = 0

    for n in range(1, trials + 1):
        res = safe_exec_test(code, n)
        if res is None:
            none_count += 1
            if none_count >= 10:
                # Test function is broken — treat as refuted
                failed_at.append(n)
                break
            continue
        if res:
            passed += 1
        else:
            failed_at.append(n)
            if len(failed_at) >= 3:
                break
        if n % 20 == 0:
            update_status(progress=int(n / trials * 100), state=f"Testing case {n}/{trials}")
            await asyncio.sleep(0)

    return {
        "passed":          passed,
        "total_tested":    min(n, trials),
        "counterexamples": failed_at,
        "survived":        len(failed_at) == 0 and passed > 0,
    }


# ---------------------------------------------------------------------------
# Proof escalation
# ---------------------------------------------------------------------------

PROOF_SYSTEM = """\
You are an expert mathematician.
A conjecture has survived extensive numerical testing.
1. Attempt a rigorous proof, or
2. Find a theoretical counterexample, or
3. Suggest a proof strategy and explain why it is likely true/false.
Be concise but rigorous. Use LaTeX where helpful."""


async def attempt_proof(conjecture: dict, verification: dict) -> str:
    prompt = (
        f"Conjecture: {conjecture['conjecture']}\n"
        f"Domain: {conjecture['domain']}\n"
        f"Motivation: {conjecture.get('motivation', '')}\n"
        f"Evidence: held for {verification['passed']} consecutive cases.\n\n"
        "Please attempt a proof or provide deep theoretical analysis."
    )
    return await claude_generate(prompt, system=PROOF_SYSTEM)

# ---------------------------------------------------------------------------
# Digest
# ---------------------------------------------------------------------------

def generate_digest(journal: ResearchJournal) -> str:
    survivors = [e for e in journal.today_entries() if e.get("status") in ("verified", "escalated", "proved")]
    lines = [
        f"=== Nova Math Research Digest — {date.today()} ===",
        f"Cycles: {STATUS['cycle_count']}  |  Survivors: {len(survivors)}",
        "",
    ]
    for s in survivors:
        lines.append(f"[{s['status'].upper()}] {s.get('conjecture',{}).get('conjecture','')}")
        v = s.get("verification", {})
        lines.append(f"  Cases: {v.get('passed','?')}")
        if s.get("proof_attempt"):
            lines.append(f"  Analysis: {s['proof_attempt'][:300]}...")
        lines.append("")
    if not survivors:
        lines.append("No conjectures survived today.")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Main research loop
# ---------------------------------------------------------------------------

class MathResearcher:

    def __init__(self):
        self.journal      = ResearchJournal()
        self.domain_index = 0
        self.running      = False

    def next_domain(self) -> str:
        d = RESEARCH_DOMAINS[self.domain_index % len(RESEARCH_DOMAINS)]
        self.domain_index += 1
        return d

    async def run_cycle(self):
        domain = self.next_domain()
        STATUS["cycle_count"] += 1
        STATUS["last_cycle"]   = datetime.now().isoformat()

        update_status(phase="generating", domain=domain,
                      state="Asking Ollama for conjecture...", progress=0, conjecture="")
        log.info(f"--- Cycle {STATUS['cycle_count']} | {domain} ---")

        # 1. Generate
        conjecture = await generate_conjecture(domain)
        if not conjecture:
            update_status(phase="idle", state="Generation failed — will retry next cycle")
            return

        text = conjecture.get("conjecture", "")
        update_status(conjecture=text, state="Conjecture received, verifying...")
        log.info(f"Conjecture: {text[:100]}")

        # 2. Verify
        update_status(phase="verifying")
        verification = await verify_conjecture(conjecture)

        if not verification["survived"]:
            ce = verification["counterexamples"]
            log.info(f"Refuted at: {ce}")
            update_status(phase="idle",
                          state=f"Refuted at n={ce[0] if ce else '?'}", progress=100)
            self.journal.append({
                "type": "conjecture", "conjecture": conjecture,
                "verification": verification, "status": "refuted",
            })
            return

        STATUS["found_count"] += 1
        log.info(f"Survived {verification['passed']} cases!")
        update_status(state=f"Survived {verification['passed']} cases — checking arXiv...", progress=100)

        # 3. arXiv
        update_status(phase="arxiv", state="Searching arXiv...")
        arxiv_result = await arxiv_check(text)
        log.info(f"arXiv: {arxiv_result}")

        # 4. Escalate to Claude if strong evidence
        proof_attempt = None
        status        = "verified"
        if verification["passed"] >= ESCALATION_THRESHOLD:
            update_status(phase="escalating", state="Escalating to Claude for proof attempt...")
            status = "escalated"
            proof_attempt = await attempt_proof(conjecture, verification)
            log.info(f"Proof attempt ({len(proof_attempt)} chars)")
            if any(w in proof_attempt.lower() for w in ["proved", "proof:", "q.e.d", "∎", "we have shown"]):
                status = "proved"

        # 5. Persist
        finding = {
            "type": "conjecture", "conjecture": conjecture,
            "verification": verification, "arxiv": arxiv_result,
            "proof_attempt": proof_attempt, "status": status,
        }
        self.journal.append(finding)
        DIGEST_PATH.write_text(generate_digest(self.journal), encoding="utf-8")

        update_status(phase="notifying", state=f"Notifying Nova — [{status}] found...")
        log.info(f"Result [{status}] — notifying Nova")

        # 6. Notify Nova (Option 2) — triggers TTS + email on Nova's side
        await notify_nova(finding)

        update_status(phase="idle", state=f"[{status.upper()}] stored: {text[:55]}...")

    async def run(self):
        self.running = True
        start_dashboard_server(self.journal)
        log.info(f"Math Researcher started. Dashboard → http://localhost:{DASHBOARD_PORT}")

        while self.running:
            try:
                await self.run_cycle()
            except Exception as e:
                log.error(f"Cycle error: {e}\n{traceback.format_exc()}")
                update_status(phase="idle", state=f"Error: {str(e)[:60]}")

            next_t = datetime.now() + timedelta(seconds=LOOP_INTERVAL_S)
            STATUS["next_cycle"] = next_t.isoformat()
            update_status(phase="idle", state="Sleeping until next cycle...")
            log.info(f"Next cycle in {LOOP_INTERVAL_S}s")
            await asyncio.sleep(LOOP_INTERVAL_S)

    def stop(self):
        self.running = False

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def main():
    researcher = MathResearcher()
    try:
        await researcher.run()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        researcher.stop()


if __name__ == "__main__":
    asyncio.run(main())
