"""
nova_research_hooks.py
======================
Tkinter-compatible integration between Nova and the math researcher.

HOW IT WORKS
------------
The researcher writes research_alert.json when a survivor is found.
Nova polls for this file every 30 seconds using root.after().
When found: Nova speaks an alert, saves a full HTML report with MathJax,
and sends an email with a clickable link to open the report in a browser.

HOW TO WIRE IN (just 3 lines in NovaAssistant.__init__, after self.root exists)
-------------------------------------------------------------------------------
    from nova_research_hooks import ResearchWatcher
    self.research_watcher = ResearchWatcher(self)
    self.research_watcher.start()

ENV VARIABLES (add to your .env):
    NOTIFY_EMAIL_FROM=your@gmail.com
    NOTIFY_EMAIL_TO=your@gmail.com
    NOTIFY_EMAIL_PASS=xxxx xxxx xxxx xxxx   # Gmail app password
"""

import json
import logging
import os
import re
import smtplib
import ssl
import threading
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

log = logging.getLogger("NovaResearchHooks")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALERT_FILE      = Path("research_alert.json")
CHEM_ALERT_FILE = Path(r"C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1\chemistry_alert.json")
POLL_INTERVAL = 30_000
REPORTS_DIR   = Path("nova_outputs") / "research"

EMAIL_FROM = os.getenv("NOTIFY_EMAIL_FROM", "")
EMAIL_TO   = os.getenv("NOTIFY_EMAIL_TO",   "")
EMAIL_PASS = os.getenv("NOTIFY_EMAIL_PASS",  "")
EMAIL_HOST = os.getenv("NOTIFY_EMAIL_HOST",  "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("NOTIFY_EMAIL_PORT", "587"))

# ---------------------------------------------------------------------------
# HTML Report Generator — full MathJax rendering
# ---------------------------------------------------------------------------

def save_finding_as_html(finding: dict) -> Path:
    """Save a research finding as a standalone HTML file with MathJax."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    status     = finding.get("status", "verified").upper()
    conjecture = finding.get("conjecture", "")
    domain     = finding.get("domain", "")
    cases      = finding.get("cases", 0)
    arxiv      = finding.get("arxiv", "")
    proof      = finding.get("proof", "") or ""
    timestamp  = finding.get("timestamp", datetime.now().isoformat())[:16]

    colour = {"VERIFIED": "#66cc66", "ESCALATED": "#9999ff", "PROVED": "#ff9900"}.get(status, "#66cc66")

    def md_to_html(text):
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'\*(.*?)\*', r'<em>\1</em>', text)
        text = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.*?)$', r'<h2>\1</h2>', text, flags=re.MULTILINE)
        text = text.replace('\n\n', '</p><p style="margin-bottom:1em">').replace('\n', '<br>')
        return text

    proof_section = ""
    if proof:
        proof_section = f"""
        <div class="section">
            <div class="section-title">Claude's Analysis</div>
            <div class="proof-content">
                <p style="margin-bottom:1em">{md_to_html(proof)}</p>
            </div>
        </div>"""

    arxiv_section = ""
    if arxiv and arxiv != "No closely matching papers found":
        arxiv_section = f"""
        <div class="section">
            <div class="section-title">Related Literature</div>
            <p style="color:#778;font-size:0.9em">{arxiv}</p>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nova Research — {status}</title>
<script>
MathJax = {{
  tex: {{
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
    processEscapes: true
  }},
  options: {{ skipHtmlTags: ['script','noscript','style','textarea','pre'] }}
}};
</script>
<script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js"></script>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{
    background:#04080F; color:#D0E8FF;
    font-family:'Segoe UI',Georgia,serif;
    max-width:900px; margin:0 auto; padding:40px 20px; line-height:1.8;
}}
.header {{ border-bottom:2px solid #ff9900; padding-bottom:12px; margin-bottom:8px; }}
.header-title {{ color:#ff9900; font-size:1.3em; letter-spacing:3px; text-transform:uppercase; }}
.meta {{ color:#446; font-size:0.8em; margin-bottom:24px; margin-top:4px; }}
.badge {{
    display:inline-block; padding:3px 16px; border-radius:4px;
    font-size:0.8em; font-weight:bold; letter-spacing:3px;
    border:1px solid {colour}; color:{colour}; background:#0a0a1a; margin-bottom:20px;
}}
.section {{
    background:#0a0f1a; border:1px solid #223; border-radius:8px;
    padding:20px 24px; margin-bottom:18px;
}}
.section-title {{
    color:#9999ff; font-size:0.75em; letter-spacing:3px;
    text-transform:uppercase; margin-bottom:12px;
    border-bottom:1px solid #223; padding-bottom:6px;
}}
.conjecture-text {{
    font-size:1.05em; line-height:1.9; color:#eee;
    border-left:3px solid #ff9900; padding-left:16px;
}}
.proof-content {{ color:#ccc; line-height:1.9; font-size:0.95em; }}
.proof-content strong {{ color:#fff; }}
.proof-content h2 {{ color:#9999ff; margin:16px 0 8px; font-size:1em; }}
.proof-content h3 {{ color:#9999ff; margin:12px 0 6px; font-size:0.95em; }}
.stats {{ display:flex; gap:32px; flex-wrap:wrap; }}
.stat {{ display:flex; flex-direction:column; }}
.stat-label {{ color:#446; font-size:0.72em; letter-spacing:1px; text-transform:uppercase; }}
.stat-value {{ color:{colour}; font-weight:bold; font-size:1.1em; }}
.footer {{ text-align:center; margin-top:36px; color:#334; font-size:0.75em; border-top:1px solid #223; padding-top:14px; }}
</style>
</head>
<body>

<div class="header">
    <div class="header-title">⭐ Nova Research Finding</div>
</div>
<div class="meta">Generated: {timestamp} &nbsp;|&nbsp; Nova Autonomous Math Researcher</div>

<span class="badge">{status}</span>

<div class="section">
    <div class="section-title">Conjecture</div>
    <div class="conjecture-text">{conjecture}</div>
</div>

<div class="section">
    <div class="section-title">Evidence</div>
    <div class="stats">
        <div class="stat">
            <span class="stat-label">Domain</span>
            <span class="stat-value" style="color:#9999ff;font-size:0.9em">{domain}</span>
        </div>
        <div class="stat">
            <span class="stat-label">Test Cases Passed</span>
            <span class="stat-value">{cases:,}</span>
        </div>
        <div class="stat">
            <span class="stat-label">Status</span>
            <span class="stat-value">{status}</span>
        </div>
    </div>
</div>

{proof_section}
{arxiv_section}

<div class="footer">
    Nova Autonomous Research System &nbsp;|&nbsp; {timestamp}
</div>
</body>
</html>"""

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[^\w]', '_', conjecture[:35])
    filename  = f"research_{ts}_{safe_name}.html"
    path      = REPORTS_DIR / filename
    path.write_text(html, encoding="utf-8")
    log.info(f"Report saved → {path}")
    return path

# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------
def _build_email_html(finding: dict, report_path: Path = None) -> str:
    status        = finding.get("status", "verified").upper()
    conjecture    = finding.get("conjecture", "")
    domain        = finding.get("domain", "")
    cases         = finding.get("cases", 0)
    arxiv         = finding.get("arxiv", "")
    proof         = finding.get("proof", "") or ""
    timestamp     = finding.get("timestamp", "")[:16]
    finding_type  = finding.get("type", "math")
    dock_best     = finding.get("dock_best", "")

    is_chemistry  = finding_type == "chemistry"
    header_colour = "#00ff88" if is_chemistry else "#ff9900"
    header_title  = "&#129516; NOVA CANCER RESEARCHER" if is_chemistry else "&#9733; NOVA MATH RESEARCHER"
    colour        = {"VERIFIED": "#66cc66", "ESCALATED": "#9999ff",
                     "PROVED": "#ff9900", "PROMISING": "#00ff88"}.get(status, "#66cc66")

    # Evidence row — chemistry shows docking score, math shows case count
    if is_chemistry and dock_best and dock_best != "N/A":
        evidence_row = f"""
    <tr><td style="padding:10px 0;border-bottom:1px solid #223;font-size:13px;">
      <strong style="color:#9999ff;">Best docking score</strong> &nbsp;
      <strong style="color:#66cc66;">{dock_best}</strong>
    </td></tr>"""
    else:
        evidence_row = f"""
    <tr><td style="padding:10px 0;border-bottom:1px solid #223;font-size:13px;">
      <strong style="color:#9999ff;">Evidence</strong> &nbsp;
      Held for <strong style="color:#66cc66;">{cases:,}</strong> consecutive cases
    </td></tr>"""

    # Strip heavy LaTeX for email preview
    preview = re.sub(r'\$\$.*?\$\$', '[see full report for equations]', proof[:500], flags=re.DOTALL)
    preview = re.sub(r'\$[^$\n]+\$', '[eq]', preview)

    proof_preview = ""
    if proof:
        proof_preview = f"""
        <tr><td style="padding:12px 0;border-top:1px solid #223;">
          <strong style="color:#9999ff;">Analysis Preview</strong><br>
          <div style="margin-top:8px;font-size:12px;line-height:1.6;color:#888;font-style:italic;">
            {preview}{'...' if len(proof) > 500 else ''}
          </div>
        </td></tr>"""

    report_link = ""
    if report_path and report_path.exists():
        file_url    = "file:///" + str(report_path.resolve()).replace("\\", "/")
        button_text = "🧬 VIEW CANCER RESEARCH REPORT" if is_chemistry else "📄 VIEW FULL REPORT WITH EQUATIONS"
        report_link = f"""
        <tr><td style="padding:20px 0;text-align:center;border-top:1px solid #223;">
          <a href="{file_url}"
             style="display:inline-block;background:{header_colour};color:#000;
                    padding:12px 28px;border-radius:4px;font-weight:bold;
                    font-size:0.9em;letter-spacing:2px;text-decoration:none;">
            {button_text}
          </a>
          <div style="color:#445;font-size:0.72em;margin-top:8px;">
            Opens in your browser
          </div>
        </td></tr>"""

    label = "Compound" if is_chemistry else "Conjecture"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="background:#0a0a12;color:#ddd;font-family:'Courier New',monospace;padding:24px;margin:0;">
<div style="max-width:640px;margin:0 auto;">
  <div style="border-bottom:2px solid {header_colour};padding-bottom:10px;margin-bottom:20px;">
    <h1 style="color:{header_colour};font-size:1.2em;letter-spacing:3px;margin:0;">{header_title}</h1>
    <div style="color:#556;font-size:0.75em;margin-top:4px;">Research Alert — {timestamp}</div>
  </div>
  <table style="width:100%;border-collapse:collapse;">
    <tr><td style="padding:10px 0;border-bottom:1px solid #223;">
      <span style="display:inline-block;background:#1a1a2a;border:1px solid {colour};
                   color:{colour};padding:2px 12px;border-radius:4px;
                   font-size:0.75em;letter-spacing:3px;font-weight:bold;">{status}</span>
    </td></tr>
    <tr><td style="padding:12px 0;border-bottom:1px solid #223;">
      <strong style="color:#9999ff;">{label}</strong><br>
      <div style="margin-top:8px;font-size:14px;line-height:1.6;
                  background:#08080f;border-left:3px solid {header_colour};
                  padding:10px 14px;color:#eee;">
        {conjecture}
      </div>
    </td></tr>
    <tr><td style="padding:10px 0;border-bottom:1px solid #223;font-size:13px;">
      <strong style="color:#9999ff;">Domain</strong> &nbsp; {domain}
    </td></tr>
    {evidence_row}
    <tr><td style="padding:10px 0;border-bottom:1px solid #223;font-size:13px;">
      <strong style="color:#9999ff;">{'ChEMBL' if is_chemistry else 'arXiv'}</strong> &nbsp; {arxiv or 'Not checked'}
    </td></tr>
    {proof_preview}
    {report_link}
  </table>
</div></body></html>"""



def send_email(finding: dict, report_path: Path = None):
    if not EMAIL_FROM or not EMAIL_PASS or not EMAIL_TO:
        log.warning("Email not configured")
        return

    is_chemistry  = finding.get("type") == "chemistry"
    status        = finding.get("status", "verified").upper()
    conjecture    = finding.get("conjecture", "")[:80]
    dock_best     = finding.get("dock_best", "")
    prefix        = "[Nova Chemistry]" if is_chemistry else "[Nova Research]"

    msg            = MIMEMultipart("alternative")
    msg["Subject"] = f"{prefix} {status}: {conjecture}..."
    msg["From"]    = f"Nova Researcher <{EMAIL_FROM}>"
    msg["To"]      = EMAIL_TO

    if is_chemistry:
        plain = (
            f"Nova Cancer Researcher — {status}\n\n"
            f"Compound:     {finding.get('conjecture', '')}\n"
            f"Domain:       {finding.get('domain', '')}\n"
            f"Docking:      {dock_best or 'N/A'}\n"
            f"ChEMBL:       {finding.get('arxiv', '')}\n\n"
            f"Full report: {str(report_path) if report_path else 'Not saved'}\n\n"
            f"Analysis:\n{finding.get('proof', '') or 'None'}\n"
        )
    else:
        plain = (
            f"Nova Math Researcher — {status}\n\n"
            f"Conjecture: {finding.get('conjecture', '')}\n"
            f"Domain:     {finding.get('domain', '')}\n"
            f"Evidence:   {finding.get('cases', 0):,} cases\n\n"
            f"Full report: {str(report_path) if report_path else 'Not saved'}\n\n"
            f"Analysis:\n{finding.get('proof', '') or 'None'}\n"
        )

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(_build_email_html(finding, report_path), "html"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.login(EMAIL_FROM, EMAIL_PASS)
            smtp.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
        log.info(f"Email sent to {EMAIL_TO}")
    except Exception as e:
        log.error(f"Email failed: {e}")

def send_email_async(finding: dict, report_path: Path = None):
    threading.Thread(target=send_email, args=(finding, report_path), daemon=True).start()

# ---------------------------------------------------------------------------
# ResearchWatcher
# ---------------------------------------------------------------------------

class ResearchWatcher:
    def __init__(self, nova_app):
        self.app  = nova_app
        self.root = nova_app.root

    def start(self):
        self.root.after(POLL_INTERVAL, self._poll)
        self.app.log("[ResearchWatcher] Started — polling every 30s for research alerts")

    def _poll(self):
        try:
            if ALERT_FILE.exists():
                finding = json.loads(ALERT_FILE.read_text(encoding="utf-8"))
                ALERT_FILE.unlink()
                self._handle(finding)
            if CHEM_ALERT_FILE.exists():
                finding = json.loads(CHEM_ALERT_FILE.read_text(encoding="utf-8"))
                CHEM_ALERT_FILE.unlink()
                self._handle_chemistry(finding)
        except Exception as e:
            self.app.log(f"[ResearchWatcher] Poll error: {e}")
        self.root.after(POLL_INTERVAL, self._poll)

    def _handle_chemistry(self, finding: dict):
        status = finding.get("status", "escalated")
        conjecture = finding.get("conjecture", "")
        domain = finding.get("domain", "")
        dock_best = finding.get("dock_best", "")
        report = finding.get("report_path", "")

        self.app.log(f"[CHEMISTRY] 🧬 [{status.upper()}] {conjecture[:80]}")

        msg = (
            f"🧬 **Chemistry Alert** — [{status.upper()}]\n\n"
            f"**{conjecture}**\n\n"
            f"Target: {domain}\n"
            f"Best docking score: {dock_best}\n"
        )
        if report:
            msg += f"\n📄 Full report: {report}"
        self.app._append_conv("assistant", msg)

        spoken = (
            f"Dr Moir, the cancer researcher has found a compound. "
            f"{conjecture[:120]}. "
            f"Best docking score {dock_best}."
        )
        try:
            self.app.speak_text(spoken)
        except Exception as e:
            self.app.log(f"[ResearchWatcher] TTS error: {e}")

        send_email_async(finding, Path(report) if report else None)


    def _handle(self, finding: dict):
        status     = finding.get("status", "verified")
        domain     = finding.get("domain", "mathematics")
        cases      = finding.get("cases", 0)
        conjecture = finding.get("conjecture", "")

        self.app.log(f"[RESEARCH] ★ [{status.upper()}] {conjecture[:80]}")

        # Save HTML report
        report_path = None
        try:
            report_path = save_finding_as_html(finding)
        except Exception as e:
            self.app.log(f"[RESEARCH] Report save failed: {e}")

        # Show in conversation
        msg = (
            f"★ **Research Alert** — [{status.upper()}]\n\n"
            f"**{conjecture}**\n\n"
            f"Domain: {domain}\n"
            f"Evidence: {cases:,} consecutive test cases\n"
        )
        if finding.get("proof"):
            msg += f"\nAnalysis preview:\n{finding['proof'][:300]}..."
        if report_path:
            msg += f"\n\n📄 Full report: {report_path}"
        self.app._append_conv("assistant", msg)

        # Speak
        phrases = {
            "proved":    f"Dr Moir, a conjecture has been proved in {domain} "
                         f"after {cases:,} test cases. {conjecture[:150]}",
            "escalated": f"Dr Moir, a strong result in {domain} after {cases:,} cases. "
                         f"{conjecture[:150]}",
            "verified":  f"Dr Moir, a new finding in {domain} after {cases:,} cases. "
                         f"{conjecture[:150]}",
        }
        spoken = phrases.get(status, f"Dr Moir, new research result: {conjecture[:150]}")
        try:
            self.app.speak_text(spoken)
        except Exception as e:
            self.app.log(f"[ResearchWatcher] TTS error: {e}")

        # Email with report link
        send_email_async(finding, report_path)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    print("Nova Research Hooks — test")
    print(f"  FROM : {EMAIL_FROM or '(not set)'}")
    print(f"  TO   : {EMAIL_TO   or '(not set)'}")

    if "--test-email" in sys.argv:
        test = {
            "status":     "proved",
            "conjecture": r"For all $n \geq 1$, $\sum_{k=0}^{n} \binom{n}{k}^2 = \binom{2n}{n}$.",
            "domain":     "combinatorial identities",
            "cases":      500,
            "arxiv":      "No closely matching papers found",
            "proof":      "## Proof\n\nUsing the binomial theorem:\n$$(1+x)^n \\cdot (1+x)^n = (1+x)^{2n}$$\n\nThe coefficient of $x^n$ on the left is $\\sum_{k=0}^{n} \\binom{n}{k}^2$.\n\nOn the right it is $\\binom{2n}{n}$. Therefore:\n$$\\sum_{k=0}^{n} \\binom{n}{k}^2 = \\binom{2n}{n} \\quad \\blacksquare$$",
            "timestamp":  datetime.now().isoformat(),
        }
        print("\nSaving HTML report...")
        path = save_finding_as_html(test)
        print(f"Saved: {path}")
        print("\nSending test email...")
        send_email(test, path)
        print("Done — check your inbox and click the button to see equations rendered.")
    else:
        print("\nRun with --test-email to test.")
