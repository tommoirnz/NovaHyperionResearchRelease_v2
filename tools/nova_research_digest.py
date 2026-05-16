"""
nova_research_digest.py
=======================
General research digest tool for Nova.
Reads any research journal and summarises or lists findings.

Supports:
  - research_journal.json     (math researcher)
  - chemistry_journal.json    (chemistry researcher)
  - Any future researcher journals

Place in Nova's tools/ folder — registers automatically.

Ask Nova:
  "What did you find overnight?"          → summary digest
  "Research digest"                       → summary digest
  "List all findings one by one"          → individual listing
  "Go through each finding"              → individual listing
  "What did the chemistry researcher find?" → chemistry only
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

# Journal files — add new researchers here
_HERE = Path(os.path.dirname(os.path.abspath(__file__)))

JOURNALS = {
    "math":      _HERE.parent / "research_journal.json",
    "chemistry": _HERE.parent / "chemistry_journal.json",
}

# Status values considered quality survivors
SURVIVOR_STATUSES = {"proved", "escalated", "verified", "novel", "promising"}

# Minimum passing cases for math (chemistry uses 0)
MIN_CASES = 100


def _load_journal(path: Path) -> list:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _summarise_math(entries: list, max_findings: int) -> tuple:
    quality = [
        e for e in entries
        if e.get("status") in SURVIVOR_STATUSES
        and e.get("verification", {}).get("passed", 0) >= MIN_CASES
        and e.get("conjecture", {}).get("conjecture")
    ]
    priority = {"proved": 0, "escalated": 1, "verified": 2}
    quality.sort(key=lambda e: (
        priority.get(e.get("status"), 3),
        -e.get("verification", {}).get("passed", 0)
    ))
    top = quality[:max_findings]

    text = ""
    for i, e in enumerate(top, 1):
        conj   = e.get("conjecture", {})
        verif  = e.get("verification", {})
        proof  = e.get("proof_attempt", "") or ""
        status = e.get("status", "").upper()
        text += (
            f"\n--- Finding {i} [{status}] ---\n"
            f"Conjecture: {conj.get('conjecture', '')}\n"
            f"Domain: {conj.get('domain', '')}\n"
            f"Evidence: {verif.get('passed', 0):,} consecutive cases\n"
        )
        if proof:
            text += f"Analysis: {proof[:400]}...\n"
    return top, text


def _summarise_chemistry(entries: list, max_findings: int) -> tuple:
    quality = [
        e for e in entries
        if e.get("status") in SURVIVOR_STATUSES
        and e.get("hypothesis", {}).get("name")
    ]
    priority = {"promising": 0, "escalated": 1, "novel": 2}
    quality.sort(key=lambda e: priority.get(e.get("status"), 3))
    top = quality[:max_findings]

    text = ""
    for i, e in enumerate(top, 1):
        h        = e.get("hypothesis", {})
        v        = e.get("verification", {})
        analysis = e.get("analysis", "") or ""
        status   = e.get("status", "").upper()
        pubchem  = e.get("pubchem", {})
        mol_info = ""
        if v.get("mw"):
            mol_info = f"MW={v['mw']}, LogP={v['logp']}, Lipinski={'OK' if v.get('lipinski_ok') else 'FAIL'}"
        text += (
            f"\n--- Finding {i} [{status}] ---\n"
            f"Compound: {h.get('name', '')}\n"
            f"Target: {h.get('target', '')}\n"
            f"SMILES: {h.get('smiles', 'N/A')}\n"
            f"Hypothesis: {h.get('hypothesis', '')[:200]}\n"
        )
        if mol_info:
            text += f"Properties: {mol_info}\n"
        if pubchem:
            text += f"PubChem: {'Found' if pubchem.get('found') else 'Not found (novel)'}\n"
        if analysis:
            text += f"Analysis: {analysis[:400]}...\n"
    return top, text


# ---------------------------------------------------------------------------
# Tool 1: get_research_digest — summary of all findings
# ---------------------------------------------------------------------------

def get_research_digest(query: str = "", ai=None, max_findings: int = 10) -> str:
    """
    General research digest tool for Nova.
    Reads all available research journals and returns a spoken summary.

    Parameters
    ----------
    query        : passed by Nova's tool system
    ai           : Nova's WorkingAI instance (for Claude summary)
    max_findings : max findings per journal
    """
    print(f"[DIGEST DEBUG] FUNCTION CALLED with query='{query}'", file=sys.stderr, flush=True)

    query_lower = query.lower()
    if "chem" in query_lower:
        journals_to_read = {"chemistry": JOURNALS["chemistry"]}
    elif any(w in query_lower for w in ["math", "maths", "conjecture", "number"]):
        journals_to_read = {"math": JOURNALS["math"]}
    else:
        journals_to_read = {k: v for k, v in JOURNALS.items() if v.exists()}

    if not journals_to_read:
        return "No research journals found. Are the researchers running?"

    all_summaries = []
    all_text      = ""
    total_cycles  = 0
    total_found   = 0

    for journal_type, path in journals_to_read.items():
        entries = _load_journal(path)
        if not entries:
            all_summaries.append(f"No entries yet in {journal_type} journal.")
            continue

        total_cycles += len(entries)

        if journal_type == "math":
            top, text = _summarise_math(entries, max_findings)
        elif journal_type == "chemistry":
            top, text = _summarise_chemistry(entries, max_findings)
        else:
            top, text = [], ""

        total_found += len(top)

        if not top:
            all_summaries.append(
                f"{journal_type.upper()} — {len(entries)} cycles run, no quality survivors yet."
            )
            continue

        all_summaries.append(f"{journal_type.upper()} — {len(top)} quality findings")
        all_text += f"\n\n=== {journal_type.upper()} RESEARCH ===\n{text}"

    if not all_text.strip():
        return (
            f"Researchers have run {total_cycles} cycles so far "
            f"but no quality survivors yet. Check back later."
        )

    stats = (
        f"Total cycles: {total_cycles}\n"
        f"Quality survivors: {total_found}\n"
        f"Journals: {', '.join(journals_to_read.keys())}\n"
    )

    if ai is not None:
        prompt = (
            f"You are Nova summarising research findings for Human researcher.\n\n"
            f"STATISTICS:\n{stats}\n"
            f"FINDINGS:\n{all_text}\n\n"
            f"Write a detailed spoken summary suitable for text-to-speech.\n"
            f"For chemistry findings: state the compound name, its cancer target, "
            f"the best docking score, and whether it is worth pursuing.\n"
            f"For math findings: state the conjecture in plain English, "
            f"the evidence count, and whether it was proved or verified.\n"
            f"Cover ALL findings, not just the top one.\n"
            f"Use plain English — no LaTeX, no SMILES strings.\n"
            f"Start with 'Human,' and end with the total number of findings."
        )
        try:
            summary = ai.generate(prompt, use_planning=False)
            if summary:
                print(f"[DIGEST DEBUG] Claude summary: {summary[:200]}", file=sys.stderr, flush=True)
                return summary
        except Exception as e:
            print(f"[DIGEST DEBUG] Claude summary failed: {e}", file=sys.stderr, flush=True)

    # Fallback — include full findings text so nothing is lost
    output = "\n".join([
        f"Research digest — {date.today()}",
        f"Cycles: {total_cycles} | Survivors: {total_found}",
        "",
    ] + all_summaries) + all_text
    print(f"[DIGEST DEBUG] Returning {len(output)} chars", file=sys.stderr, flush=True)
    return output

# ---------------------------------------------------------------------------
# Tool 2: list_research_findings — one by one listing
# ---------------------------------------------------------------------------
def list_research_findings(query: str = "", ai=None) -> str:
    """
    List all research findings one by one from all journals.
    Nova will read each finding individually via TTS.

    Parameters
    ----------
    query : passed by Nova's tool system
    ai    : Nova's WorkingAI instance
    """
    print(f"[LIST DEBUG] FUNCTION CALLED with query='{query}'", file=sys.stderr, flush=True)

    _ = query

    all_findings = []

    for journal_type, path in JOURNALS.items():
        entries = _load_journal(path)
        survivors = [
            e for e in entries
            if e.get("status") in SURVIVOR_STATUSES
        ]
        if journal_type == "math":
            survivors = [
                e for e in survivors
                if e.get("verification", {}).get("passed", 0) >= MIN_CASES
            ]
        for e in survivors:
            all_findings.append((journal_type, e))

    if not all_findings:
        return "No research findings recorded yet. The researchers are still working."

    REPORTS_DIR = _HERE.parent / "nova_outputs" / "research"

    lines = [f"Researcher, I have {len(all_findings)} research findings to report. Here they are:\n"]

    for i, (journal_type, e) in enumerate(all_findings, 1):
        if journal_type == "math":
            conj   = e.get("conjecture", {})
            verif  = e.get("verification", {})
            status = e.get("status", "").upper()
            text   = conj.get("conjecture", "")
            domain = conj.get("domain", "")
            cases  = verif.get("passed", 0)
            proof  = e.get("proof_attempt", "") or ""
            ts     = e.get("timestamp", "")[:10]

            lines.append(f"Finding {i} of {len(all_findings)} — {status}")
            lines.append(f"Domain: {domain}")
            lines.append(f"Date: {ts}")
            lines.append(f"Conjecture: {text}")
            lines.append(f"Evidence: {cases:,} consecutive test cases with no counterexamples.")
            if proof:
                import re
                plain_proof = re.sub(r'\$\$.*?\$\$', '[equation]', proof[:200], flags=re.DOTALL)
                plain_proof = re.sub(r'\$[^$\n]+\$', '[eq]', plain_proof)
                lines.append(f"Analysis summary: {plain_proof.strip()}...")

            # Add link to HTML report if it exists
            import re
            safe_name = re.sub(r'[^\w]', '_', text[:35])
            reports = sorted(REPORTS_DIR.glob(f"research_*{safe_name}*.html")) if REPORTS_DIR.exists() else []
            if reports:
                lines.append(f"Full report with equations: {reports[0]}")
                # Auto-open in browser
                import os
                try:
                    os.startfile(str(reports[0]))
                except Exception:
                    pass
        elif journal_type == "chemistry":
            h      = e.get("hypothesis", {})
            status = e.get("status", "").upper()
            ts     = e.get("timestamp", "")[:10]

            lines.append(f"Finding {i} of {len(all_findings)} — CHEMISTRY {status}")
            lines.append(f"Compound: {h.get('name', '')}")
            lines.append(f"Target: {h.get('target', '')}")
            lines.append(f"Date: {ts}")
            lines.append(f"Hypothesis: {h.get('hypothesis', '')[:200]}")

        lines.append("")

    # Ask Claude to narrate naturally
    if ai is not None:
        full_text = "\n".join(lines)
        print(f"[LIST DEBUG] lines sample: {chr(10).join(lines[5:15])}", file=sys.stderr, flush=True)
        prompt = (
            f"You are Nova reading out research findings one by one.\n\n"
            f"Read the following findings naturally for text-to-speech, "
            f"introducing each one clearly. Use plain English, no LaTeX.\n"
            f"Where a report path is listed, mention that a full report "
            f"with equations is available.\n"
            f"Keep each finding concise but complete.\n\n"
            f"{full_text}"
        )
        try:
            narrated = ai.generate(prompt, use_planning=False)
            if narrated:
                return narrated
        except Exception:
            pass

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utility: generate HTML reports for all existing journal entries
# ---------------------------------------------------------------------------

def generate_missing_reports() -> str:
    """
    One-off utility to generate HTML reports for all existing journal
    entries that predate the report system.

    Run from PowerShell:
        python -c "from tools.nova_research_digest import generate_missing_reports; print(generate_missing_reports())"
    """
    try:
        from nova_research_hooks import save_finding_as_html
    except ImportError:
        return "Could not import save_finding_as_html — check nova_research_hooks.py is in the project root."

    entries  = _load_journal(JOURNALS["math"])
    survivors = [
        e for e in entries
        if e.get("status") in SURVIVOR_STATUSES
        and e.get("verification", {}).get("passed", 0) >= MIN_CASES
    ]

    count = 0
    for e in survivors:
        finding = {
            "status":     e.get("status", "verified"),
            "conjecture": e.get("conjecture", {}).get("conjecture", ""),
            "domain":     e.get("conjecture", {}).get("domain", ""),
            "cases":      e.get("verification", {}).get("passed", 0),
            "arxiv":      e.get("arxiv", ""),
            "proof":      e.get("proof_attempt", "") or "",
            "timestamp":  e.get("timestamp", ""),
        }
        try:
            save_finding_as_html(finding)
            count += 1
        except Exception as ex:
            print(f"Failed for entry: {ex}")

    return f"Generated {count} HTML reports in nova_outputs/research/"
