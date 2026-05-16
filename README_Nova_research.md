# Nova Hyperion Research Engine
## Autonomous Multi-Domain Scientific Discovery

---

## Table of Contents

1. [Overview](#overview)
2. [Theoretical Foundation](#theoretical-foundation)
3. [Architecture](#architecture)
4. [Mathematical Research Engine](#mathematical-research-engine)
5. [Cancer Drug Discovery Engine](#cancer-drug-discovery-engine)
6. [Integration with Nova](#integration-with-nova)
7. [Operating the Research Engine](#operating-the-research-engine)
8. [Extending to New Research Domains](#extending-to-new-research-domains)
9. [Technical Reference](#technical-reference)
10. [Querying Nova for Research Results](#querying-nova-for-research-results)
11. [Academic Context and Originality](#academic-context-and-originality)

---

## Overview

The Nova Hyperion Research Engine is an autonomous, multi-agent scientific research system that runs continuously in the background, generating hypotheses, validating them computationally, and escalating only the most promising findings to a large language model for deep analysis. Nova (the main AI assistant) receives alerts in real time and can query the accumulated findings at any time.

The engine embodies a core principle: **use cheap, fast, local computation for 99% of the filtering, and reserve expensive API calls for the 1% that genuinely deserve deep analysis.**

Two research domains are currently implemented:

- **Mathematics** — autonomous conjecture generation and numerical verification
- **Cancer Drug Discovery** — autonomous molecule generation, validation, docking, and oncology analysis

Both share the same architectural pattern and can be extended to any domain where hypotheses can be generated cheaply and validated computationally.

---

## Theoretical Foundation

### The Escalation Funnel

The central idea is a multi-stage filter funnel. Each stage is faster and cheaper than the next, and only survivors of each stage proceed further.

```
Stage 1: Hypothesis Generation        (local LLM, free)
           ↓  ~50% pass
Stage 2: Structural / Formal Filter   (RDKit / symbolic, free)
           ↓  ~30% pass
Stage 3: Novelty Check                (public APIs, free)
           ↓  ~20% pass
Stage 4: Computational Validation     (docking / numerical, free)
           ↓  ~5% pass
Stage 5: Deep AI Analysis             (Claude via API, paid)
           ↓  ~2% of original
Stage 6: Human Review                 (Dr Moir)
```

This means Claude sees roughly 1–2 compounds per 50–100 cycles, keeping costs minimal while ensuring every analysis is genuinely warranted.

### Local-First Philosophy

All heavy computation runs locally:
- **Ollama** serves open-source LLMs (qwen3-coder:30b) for hypothesis generation on the RTX 5070 Ti GPU
- **RDKit** performs cheminformatics validation entirely in Python with no external calls
- **AutoDock Vina** runs molecular docking locally against pre-prepared receptor files
- **Whisper** handles voice recognition locally

Only the final escalation step calls an external paid API (OpenRouter → Claude Sonnet). This means the system can run indefinitely at near-zero marginal cost.

### Autonomous Loop Design

Each researcher runs as an infinite async loop with a configurable sleep interval between cycles. The loop is:

```
while running:
    domain = next_domain()
    hypothesis = generate()
    if not validate(hypothesis): continue
    if not novel(hypothesis): continue
    if not passes_computational_filter(hypothesis): continue
    analysis = escalate_to_claude(hypothesis)
    save_report(analysis)
    notify_nova(analysis)
    sleep(LOOP_INTERVAL_S)
```

This design means the researcher is fully autonomous — it requires no human intervention and generates a growing dataset of validated findings over time.

---

## Architecture

### Component Overview

```
NovaHyperionResearch_v1/
│
├── nova_assistant.py              # Nova main assistant
├── nova_research_hooks.py         # Alert watcher — polls for new findings
│
├── nova_math_researcher.py        # Mathematics research loop
├── nova_chemistry_researcher.py   # Cancer drug discovery loop
├── nova_docking.py                # AutoDock Vina pipeline
│
├── tools/
│   └── nova_research_digest.py    # Nova tool — query accumulated findings
│
├── chemistry_journal.json         # Chemistry findings database
├── research_journal.json          # Mathematics findings database
│
├── docking_data/
│   ├── receptors/                 # Prepared PDBQT receptor files (cached)
│   └── results/                   # Ligand PDBQT and docked output files
│
└── nova_outputs/
    ├── chemistry/                 # HTML reports for chemistry findings
    └── research/                  # HTML reports for math findings
```

### Data Flow

```
Ollama (local GPU)
    ↓ hypothesis JSON
Researcher loop
    ↓ SMILES / conjecture
RDKit / Python validator
    ↓ valid + drug-like
PubChem / arXiv API
    ↓ novel
AutoDock Vina (local)
    ↓ docking score ≤ threshold
Claude Sonnet (OpenRouter)
    ↓ full analysis
chemistry_journal.json
    ↓ written
chemistry_alert.json
    ↓ polled every 30s
ResearchWatcher (Nova)
    ↓ spoken + email
Dr Moir
```

---

## Mathematical Research Engine

### What It Does

The math researcher autonomously generates conjectures in number theory, combinatorics, and related areas, then tests them against thousands of cases numerically. Conjectures that survive are escalated to Claude for proof attempts.

### Hypothesis Generation

Ollama is prompted with a mathematical domain (e.g., "properties of prime gaps", "divisibility patterns in Fibonacci sequences") and asked to produce a structured conjecture:

```json
{
  "conjecture": "For all primes p > 2, p² - 1 is divisible by 24",
  "domain": "number theory",
  "variables": ["p"],
  "test_range": [3, 10000]
}
```

### Numerical Verification

The conjecture is parsed and tested against the specified range using Python's `sympy` and `mpmath` libraries. A conjecture passes if it holds for all test cases with no counterexample found:

```python
for p in primes_in_range(test_range):
    if not evaluate_conjecture(conjecture, p):
        return "counterexample_found"
return "verified", cases_tested
```

### Escalation Criteria

A conjecture escalates to Claude if:
- It holds for ≥ 100 consecutive cases with no counterexample
- It is not trivially equivalent to a known theorem (arXiv check)
- The symbolic verifier (`sympy_exec`) cannot immediately disprove it

### Output

Each verified conjecture produces:
- A JSON entry in `research_journal.json` with the conjecture text, domain, case count, and Claude's proof attempt
- An HTML report with MathJax-rendered equations
- A spoken alert via Nova's TTS
- An email with a clickable link to the full report

---

## Cancer Drug Discovery Engine

### What It Does

The chemistry researcher autonomously generates novel small molecule drug candidates, validates their chemical properties, checks for novelty, predicts ADMET (absorption, distribution, metabolism, excretion, toxicity) properties, docks them against validated cancer protein targets, and escalates survivors to Claude for full oncology analysis.

### The Drug Discovery Pipeline

#### Stage 1 — Hypothesis Generation (Ollama)

The qwen3-coder:30b model is prompted with a specific oncology research domain and asked to generate a structured drug hypothesis:

```json
{
  "name": "Compound name",
  "smiles": "CC1=CC(=CC(=C1N)...",
  "target": "CDK4/6 kinase",
  "cancer_type": "Hormone receptor positive breast cancer",
  "mechanism": "CDK4/6 inhibitor",
  "hypothesis": "This compound inhibits...",
  "novelty_claim": "Unlike palbociclib..."
}
```

The model is instructed to use well-known scaffolds (quinazoline, pyrimidine, piperazine) with novel substituent combinations, keeping MW under 480 Da and LogP under 4.5.

#### Stage 2 — Structural Validation (RDKit)

The SMILES string is parsed by RDKit. If invalid, Ollama is asked to repair it once. Valid structures are evaluated against Lipinski's Rule of Five:

| Property | Limit | Rationale |
|---|---|---|
| Molecular Weight (MW) | ≤ 500 Da | Oral bioavailability |
| LogP (lipophilicity) | ≤ 5 | Membrane permeability |
| H-bond donors (HBD) | ≤ 5 | Solubility |
| H-bond acceptors (HBA) | ≤ 10 | Absorption |

Compounds with more than one violation are discarded as not drug-like. PAINS (Pan-Assay Interference Compounds) alerts are also flagged.

RDKit also classifies the scaffold using SMARTS pattern matching:

```python
SCAFFOLD_PATTERNS = {
    "Quinazoline":   "c1nc2ccccc2nc1",
    "Hydantoin":     "[#7]1C(=O)[#7]CC1=O",
    "Piperazine":    "C1CNCCN1",
    "Triazine":      "c1ncncn1",
    # ... 15 patterns total
}
```

This allows Claude to immediately identify mismatches between what Ollama claimed the scaffold is and what RDKit actually found in the SMILES.

#### Stage 3 — Novelty Check (PubChem)

The SMILES is submitted to PubChem's REST API to check for exact structure matches:

```
GET https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/cids/JSON
```

If a real CID is returned (CID > 0), the compound is known and discarded. If not found, it is potentially novel. At this point, PubChem's IUPAC naming endpoint is also queried to get a proper chemical name for the structure, correcting Ollama's invented names.

ChEMBL is then searched for structurally similar compounds (≥ 70% Tanimoto similarity) to understand what the closest known drugs look like and their clinical phases.

#### Stage 4 — ADMET Prediction (RDKit)

Drug-like ADMET properties are estimated from molecular descriptors:

| Property | Method | Threshold |
|---|---|---|
| GI Absorption | Veber rules (TPSA ≤ 140, rotatable bonds ≤ 10) | High |
| BBB Permeability | TPSA < 90, MW < 450, LogP > 0, HBD ≤ 3 | Yes/No |
| Water Solubility | LogP estimate | High/Good/Moderate/Poor |
| CYP Inhibition Risk | Aromatic rings ≥ 3 and LogP > 3 | Risk/Low risk |
| Druglikeness | Lipinski + Veber combined | Drug-like/Borderline/Non drug-like |

#### Stage 5 — Molecular Docking (AutoDock Vina)

This is the key computational filter. The compound is docked against validated cancer protein targets to predict binding affinity.

**Receptor Preparation:**

Crystal structures are downloaded from RCSB Protein Data Bank and prepared using pdbfixer (missing atoms, hydrogens at pH 7.4) and OpenBabel (PDBQT format with Gasteiger charges). Receptors are cached after first preparation.

**Current Targets:**

| Target | PDB ID | Cancer | Drug Class |
|---|---|---|---|
| EGFR | 2ITY | NSCLC, breast | Erlotinib, gefitinib, osimertinib |
| BCL2 | 4LVT | CLL, lymphoma | Venetoclax |
| CDK2 | 1AQ1 | Breast, solid tumours | Palbociclib, ribociclib |
| PARP1 | 3L3M | BRCA-mutated ovarian, breast | Olaparib, niraparib |

**Binding Site Coordinates:**

Binding site centres are extracted from co-crystallised ligands in the PDB structures. For example, for PARP1 (3L3M), the NAD+ binding site centre is at (26.4, 11.2, 27.0) Å.

**Ligand Preparation:**

The SMILES is converted to a 3D conformer using RDKit's ETKDGv3 conformer generator, optimised with MMFF94 force field, then converted to PDBQT format via OpenBabel with Gasteiger charges.

**Scoring:**

AutoDock Vina uses a knowledge-based scoring function. The output is a binding affinity in kcal/mol (more negative = stronger predicted binding). Scores are calibrated for OpenBabel receptor preparation:

| Score (kcal/mol) | Grade | Interpretation |
|---|---|---|
| ≤ −7.0 | EXCELLENT | Comparable to approved drugs |
| ≤ −5.5 | GOOD | Promising lead |
| ≤ −4.0 | MODERATE | Weak, needs optimisation |
| > −4.0 | POOR | Unlikely to show activity |

**Pose Consistency:**

A novel quality check examines all 9 docking poses. Reliable docking shows a tight cluster of scores; unreliable docking shows a large spread or many positive-energy poses:

```python
spread = max(all_scores) - min(all_scores)
valid  = len([s for s in all_scores if s < 0])

if spread < 5 and valid >= 5:   quality = "consistent"
elif spread < 15 and valid >= 3: quality = "moderate"
else:                             quality = "unreliable"
```

An unreliable CDK2 score like `[-8.35, -1.99, 0.49, 3.17, 1189.0]` (spread = 1197) is flagged and Claude is told not to rely on it.

**Docking Filter:**

Compounds scoring above −5.5 kcal/mol against all targets are discarded with status `poor_docking`. Only those with at least one target below the threshold proceed to Claude.

#### Stage 6 — Claude Oncology Analysis

The surviving compound's full data package is assembled into a structured prompt:

```
Compound: [name]
SMILES: [smiles]
Actual scaffold (RDKit): [scaffold]
Target: [target]
Cancer type: [cancer]
Mechanism: [mechanism]
Molecular properties: MW=..., LogP=..., Scaffold=...
PubChem: Not found (novel)
ChEMBL similarity: [similar compounds]
ADMET: GI=High, BBB=No, Solubility=Good...
AutoDock Vina scores:
  PARP1 (NAD+ pocket): -9.67 kcal/mol [EXCELLENT]
  CDK2 (ATP cleft): -7.59 kcal/mol [EXCELLENT] ⚠️ moderate
```

Claude's ONCOLOGY_SYSTEM prompt instructs it to cover seven sections: therapeutic potential, mechanism of action, structural analysis (using the RDKit scaffold to resolve name/structure mismatches), docking interpretation, ADMET assessment, development pathway, and a verdict with confidence level.

---

## Integration with Nova

### ResearchWatcher

`nova_research_hooks.py` contains the `ResearchWatcher` class which polls two alert files every 30 seconds using Tkinter's `root.after()` scheduler:

```python
ALERT_FILE      = Path("research_alert.json")    # math
CHEM_ALERT_FILE = Path(r"C:\...\chemistry_alert.json")  # chemistry
```

When a new alert appears, the watcher:
1. Reads and deletes the alert file
2. Appends the finding to Nova's conversation
3. Speaks the alert via Edge TTS
4. Sends an email with a link to the HTML report

### Nova Tool — Research Digest

`tools/nova_research_digest.py` provides two Nova tools:

**`get_research_digest`** — Called when you ask Nova "What did the chemistry researcher find?" Returns a Claude-narrated summary of all survivors from the journal, with docking scores, compound properties, and verdicts.

**`list_research_findings`** — Returns all findings one by one with full detail, suitable for reading aloud.

The tool routes to the correct journal based on query keywords:
- "chem" → chemistry journal only
- "math", "conjecture" → math journal only
- anything else → both journals

### Asking Nova About Research

```
"What did the chemistry researcher find?"
"List all chemistry survivors with their docking scores"
"Show me the full research digest"
"What did you find overnight?"
"Show me finding five in detail"
```

---

## Operating the Research Engine

### Starting Both Researchers

Open two PowerShell terminals in the project directory:

**Terminal 1 — Chemistry Researcher:**
```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_chemistry_researcher.py
```

**Terminal 2 — Nova (with Math Researcher):**
```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_assistant.py
```

### Monitoring

**Chemistry Dashboard** — `http://localhost:8083` — refreshes every 5 seconds showing:
- Current cycle phase (generating / verifying / pubchem / docking / escalating)
- Active hypothesis and SMILES
- Live docking scores
- Recent survivors with scores
- Live log tail

### Configuration

Key settings in `nova_chemistry_researcher.py`:

```python
OLLAMA_MODEL          = "qwen3-coder:30b"    # Local model for generation
LOOP_INTERVAL_S       = 20                    # Seconds between cycles
DOCK_SCORE_THRESHOLD  = -5.5                  # kcal/mol filter threshold
DOCK_EXHAUSTIVENESS   = 8                     # Vina search exhaustiveness
CHEMBL_SIMILARITY     = 70                    # % similarity for ChEMBL search
```

Key settings in `nova_docking.py`:

```python
SCORE_EXCELLENT = -7.0   # Calibrated for OpenBabel prep
SCORE_GOOD      = -5.5
SCORE_MODERATE  = -4.0
```

### Journal Files

All findings are stored as JSON arrays in flat files. The chemistry journal entry structure:

```json
{
  "type": "hypothesis",
  "status": "promising",
  "timestamp": "2026-05-07T08:00:00",
  "hypothesis": {
    "name": "Compound name",
    "smiles": "...",
    "target": "PARP1",
    "cancer_type": "BRCA-mutated ovarian cancer",
    "ollama_name": "Original Ollama label"
  },
  "verification": {
    "valid": true,
    "mw": 348.32,
    "logp": 0.94,
    "lipinski_ok": true,
    "scaffold_class": "Pyrimidine",
    "violations": [],
    "alerts": []
  },
  "pubchem": { "found": false, "cid": null },
  "chembl": { "similar_compounds": [], "max_similarity": 0 },
  "admet": {
    "gi_absorption": "High",
    "bbb_permeant": "No",
    "water_solubility": "High",
    "druglikeness": "Drug-like"
  },
  "docking": {
    "best_score": -10.08,
    "best_target": "PARP1",
    "passes_filter": true,
    "pose_warnings": {},
    "results": {
      "PARP1": {
        "score": -10.08,
        "grade": "EXCELLENT",
        "pose_quality": "consistent",
        "pose_spread": 3.97,
        "pose_valid": 9
      }
    }
  },
  "analysis": "# Comprehensive Oncology Analysis..."
}
```

### HTML Reports

Each escalated finding generates a dark-theme HTML report at `nova_outputs/chemistry/cancer_YYYYMMDD_HHMMSS_[name].html` containing:
- Status badge and cancer type badge
- RDKit scaffold badge (🔬)
- Molecular properties table with Lipinski status
- ADMET predictions (GI, BBB, solubility, CYP risk, druglikeness)
- ChEMBL similar compounds table
- AutoDock Vina binding scores table with pose quality indicators
- Claude's full oncology analysis with markdown rendering

---

## Extending to New Research Domains

The architecture is domain-agnostic. Any research domain can be added by implementing three components:

### 1. Hypothesis Generator

Create a function that prompts Ollama (or any LLM) to generate a structured hypothesis JSON for your domain:

```python
async def generate_hypothesis(domain: str) -> Optional[dict]:
    system = """You are an expert in [your domain].
    Generate one hypothesis. Respond ONLY with valid JSON:
    {
      "name": "Hypothesis name",
      "description": "What this hypothesis claims",
      "testable_prediction": "What we can check computationally",
      "domain": "Specific sub-domain",
      "novelty_claim": "Why this is new"
    }"""
    raw = await ollama_generate(f"Generate a hypothesis for: {domain}", system=system)
    # parse JSON...
```

### 2. Computational Validator

Implement whatever local validation is appropriate for your domain:

| Domain | Validator |
|---|---|
| Chemistry | RDKit structural validation, Lipinski rules, docking |
| Mathematics | sympy symbolic verification, numerical testing |
| Materials Science | pymatgen structure validation, DFT energy estimation |
| Protein Engineering | BioPython structure validation, AlphaFold2 folding prediction |
| Epidemiology | Statistical significance tests, model fitting |
| Astrophysics | Orbital mechanics simulation, spectra matching |

The validator should return a dict with `valid: bool` and any computed properties.

### 3. Novelty Check

Check your domain's primary database for prior art:

| Domain | Novelty Database |
|---|---|
| Chemistry | PubChem, ChEMBL |
| Mathematics | arXiv, OEIS |
| Materials | Materials Project, ICSD |
| Biology | UniProt, PDB |
| Literature | Semantic Scholar, arXiv |

### 4. Register the Journal

Add the new journal to `tools/nova_research_digest.py`:

```python
JOURNALS = {
    "math":      _HERE.parent / "research_journal.json",
    "chemistry": _HERE.parent / "chemistry_journal.json",
    "materials": _HERE.parent / "materials_journal.json",  # new
}
```

And add a `_summarise_materials()` function following the same pattern as `_summarise_chemistry()`.

### 5. Register the Alert File

Add the new alert file to `nova_research_hooks.py`:

```python
CHEM_ALERT_FILE      = Path(r"...\chemistry_alert.json")
MATERIALS_ALERT_FILE = Path(r"...\materials_alert.json")  # new
```

And add a `_handle_materials()` method to `ResearchWatcher._poll()`.

### Example: Materials Science Extension

A materials researcher could generate hypotheses about novel crystal structures, validate them using pymatgen, check the Materials Project for novelty, run a quick DFT energy estimate with ASE, and escalate promising low-energy structures to Claude for analysis of their electronic and mechanical properties.

The same escalation funnel applies:

```
Ollama generates crystal structure hypothesis
    ↓
pymatgen validates symmetry and composition
    ↓
Materials Project checks for novelty
    ↓
ASE/DFT estimates formation energy
    ↓
Claude analyses thermodynamic stability and applications
    ↓
Nova alerts Dr Moir
```

---

## Technical Reference

### Dependencies

```
# Core
rdkit                 # Cheminformatics
httpx                 # Async HTTP
python-dotenv         # Environment variables

# Docking
openbabel-wheel       # Molecular file format conversion
pdbfixer              # PDB structure preparation
openmm                # Molecular mechanics

# Nova
openai-whisper        # Voice recognition
edge-tts              # Text-to-speech

# External binaries
AutoDock Vina 1.2.7   # Molecular docking
```

### Environment Variables (.env)

```
OPENROUTER_KEY=sk-or-...        # Required for Claude escalation
BRAVE_KEY=...                   # Optional for web search
NOTIFY_EMAIL_FROM=...           # Gmail for alerts
NOTIFY_EMAIL_TO=...
NOTIFY_EMAIL_PASS=...           # Gmail app password
VINA_EXE=C:\vina.exe           # Path to AutoDock Vina binary
```

### Docking Score Calibration

The scores reported by AutoDock Vina depend on how the receptor and ligand were prepared. This system uses OpenBabel for preparation, which consistently gives scores approximately 2–3 kcal/mol less negative than MGLTools-prepared structures. All thresholds are calibrated accordingly. The reference calibration was performed by docking erlotinib (an approved EGFR inhibitor) against the 2ITY structure, which yielded −6.7 kcal/mol with this pipeline vs. the literature-reported −9 to −11 kcal/mol from MGLTools. Thresholds were adjusted to match this systematic offset.

### Performance

On an RTX 5070 Ti with qwen3-coder:30b via Ollama:
- Hypothesis generation: ~45 seconds per cycle
- RDKit validation: < 0.1 seconds
- PubChem API check: ~1–2 seconds
- Docking (exhaustiveness=8): ~30–60 seconds per target
- Claude analysis: ~10–20 seconds

A full successful cycle (generation through Claude analysis) takes approximately 2–5 minutes. Failed cycles (discarded at early stages) complete in under 60 seconds. Expect 1–3 survivors per hour of running time.

### Troubleshooting

**No JSON in hypothesis output** — qwen3 may output `<think>...</think>` blocks before JSON. The `ollama_generate` function strips these automatically with `re.sub(r'<think>.*?</think>', '', raw)`.

**PubChem CID = 0** — The `/cids/JSON` endpoint returns 0 as a sentinel for "not found". Filter with `[c for c in cids if c > 0]`.

**Docking fails with BCL2** — The BCL2 receptor PDBQT may have formatting issues. Delete `docking_data/receptors/BCL2_receptor.pdbqt` and let it regenerate.

**Dashboard KeyError** — Conditional class expressions like `{'g' if x else 'r'}` inside `.format()` template strings cause KeyErrors. Pre-compute all conditional values as named variables before calling `.format()`.

---

---

## Querying Nova for Research Results

Nova can be asked about research findings at any time — whether the researcher has just started or has been running overnight. All queries are spoken naturally into the voice interface or typed into the web UI. The following sections cover every useful query pattern.

### Basic Queries — Chemistry

These trigger the `get_research_digest` tool directly and return a Claude-narrated spoken summary of all chemistry survivors:

```
"What did the chemistry researcher find?"
"Show me the chemistry results"
"What compounds has the cancer researcher discovered?"
"Give me a chemistry digest"
"What did you find in chemistry overnight?"
```

Any query containing the word **"chem"** routes automatically to the chemistry journal. Nova will respond with each survivor's compound name, cancer target, best docking score, ADMET summary, and a verdict on whether it is worth pursuing.

### Basic Queries — Mathematics

```
"What did the math researcher find?"
"Show me the conjecture results"
"What number theory findings are there?"
"Give me the maths digest"
```

Any query containing **"math"**, **"maths"**, **"conjecture"**, or **"number"** routes to the mathematics journal.

### Full Digest — Both Researchers

```
"Give me the full research digest"
"What did you find overnight?"
"Show me all research results"
"Research digest"
```

Queries with no domain keyword read both journals and return a combined summary.

### Listing All Findings in Detail

To get every finding listed individually rather than summarised:

```
"List all chemistry survivors with their docking scores"
"List all research findings one by one"
"Go through each chemistry finding"
"Show me all compounds and their scores"
```

This triggers `list_research_findings`, which reads each survivor from the journal and presents it with full compound name, target, docking score, molecular properties, and timestamp.

### Asking for a Specific Finding

Nova can retrieve and present a particular finding by number:

```
"Show me finding five in detail"
"Tell me about the third chemistry result"
"What was the best docking hit?"
"Which compound had the highest PARP1 score?"
```

When asking by number, the planner will first call `get_research_digest` to retrieve the full list, then the text agent will extract and present the requested finding in a formatted table.

### Asking About Specific Targets or Properties

```
"Which compounds docked well against EGFR?"
"Show me the PARP1 results"
"Which findings are drug-like?"
"Which compounds had consistent docking?"
"What were the escalated findings?"
"Which compounds passed Lipinski?"
```

Nova will search the digest for the relevant compounds and present only those matching the criteria.

### Asking Nova to Open a Report

Each finding generates an HTML report with full MathJax equations (for math) or docking tables and oncology analysis (for chemistry). Ask Nova to open one:

```
"Open the HTML report for finding three"
"Show me the full report for the PARP1 compound"
"Open the chemistry report"
```

Nova will use the `open_webpage` or `file_explorer` tool to open the report in the browser. The reports are stored at:

```
nova_outputs/chemistry/cancer_YYYYMMDD_HHMMSS_[name].html
nova_outputs/research/research_YYYYMMDD_HHMMSS_[name].html
```

### Controlling How Many Results Are Shown

The digest tool defaults to showing 10 findings. To explicitly request more or fewer:

```
"Show me all chemistry findings, don't limit to five"
"Give me just the top three chemistry results"
"Show me all findings with no limit"
```

Nova will pass the appropriate `max_findings` parameter to the tool.

### After an Alert — Immediate Follow-Up

When the ResearchWatcher fires and Nova announces a new finding, you can immediately follow up:

```
"Tell me more about that compound"
"What does Claude think about it?"
"Open the full report"
"How does it compare to olaparib?"
"What are the Lipinski properties?"
```

The finding will already be in Nova's conversation context from the alert, so these follow-ups work without needing to re-query the journal.

### Checking Progress

To see how many cycles have run and how many survivors have been found without reading all the details:

```
"How many cycles has the researcher run?"
"How many chemistry survivors are there so far?"
"Is the researcher still running?"
"How long has the researcher been going?"
```

Nova will call the digest tool and report the headline statistics from the journal.

### Complete Voice Command Reference

| Intent | Example Phrase |
|---|---|
| Chemistry summary | "What did the chemistry researcher find?" |
| Math summary | "What did the math researcher find?" |
| Full digest | "Give me the full research digest" |
| All findings listed | "List all chemistry survivors with docking scores" |
| Specific finding | "Show me finding five in detail" |
| Target filter | "Which compounds hit PARP1?" |
| Open report | "Open the HTML report for finding three" |
| Progress check | "How many chemistry survivors are there?" |
| After alert follow-up | "Tell me more about that compound" |
| Best result | "What was the best docking score overall?" |

---

## Academic Context and Originality

### Where This Work Sits in the Literature

The Nova Hyperion Research Engine was developed independently as a personal research tool by Dr Tom Moir in 2025–2026. It is not derived from any existing codebase or academic framework, but it operates in a space that has become very active in the research community. Understanding where it sits relative to published work clarifies both what is genuinely novel about this approach and where it aligns with broader trends.

### The General Idea — AI-Driven Scientific Discovery

The concept of using AI to autonomously generate and test scientific hypotheses is not new. The field now has a substantial body of literature, and several surveys have mapped the landscape comprehensively.

A 2024 survey on LLMs in scientific discovery examined the ability of language models to propose hypotheses, demonstrating their considerable capacity for generating novel yet valid hypotheses under open-ended constraints. Frameworks such as HypER generate literature-grounded hypotheses with clear provenance, while other approaches extend hypothesis generation into the biomedical domain.

By mid-2025, the field had progressed to multimodal agentic systems that listen, see, speak, and act — orchestrating cloud software and physical laboratory hardware — charting a course from automated literature synthesis and hypothesis generation to self-driving laboratories.

Google DeepMind's AlphaEvolve agent couples Gemini large language models to an evolutionary search loop that autonomously proposes, tests, and refines hypotheses. It recently discovered a 48-multiplication algorithm for 4×4 complex-valued matrix multiplication — beating a record that had stood since 1969.

The Nova engine follows the same fundamental pattern — generate, test, escalate — but does so as a lightweight personal system running on a single workstation rather than a cloud-scale institutional deployment.

### Autonomous Drug Discovery Pipelines

The chemistry research component has many parallels in the literature, though the existing academic systems are generally more complex, require cloud infrastructure, and are not integrated with a personal AI assistant.

The Prompt-to-Pill framework, published in 2025 and based on a systematic analysis of 51 LLM-based studies from 2022–2025, integrates specialised LLM agents for molecule generation, docking, property prediction, trial construction, patient matching, and outcome forecasting through a central orchestrator. Unlike prior frameworks confined to molecule-level reasoning, it establishes a pipeline from molecular ideation to virtual trial execution.

AgentD, an LLM-powered agent framework, supports drug discovery by performing biomedical data retrieval, generating seed molecule libraries via SMILES-based generative models, predicting ADMET-related properties, and refining molecular representations. In a case study targeting BCL-2 in lymphocytic leukaemia, the agent autonomously retrieved relevant information and generated chemically diverse molecules, with drug-like candidates increasing across iterative refinement rounds.

FROGENT is an end-to-end drug design multi-agent system that achieves substantial gains in efficiency and demonstrates the strong potential of LLM-based agentic systems to autonomously orchestrate drug development pipelines, significantly reducing reliance on manual, experience-driven human intervention.

**Key differences from Nova's approach:**

| Feature | Academic systems (e.g. Prompt-to-Pill, AgentD) | Nova Hyperion |
|---|---|---|
| Infrastructure | Cloud-scale, multi-server | Single workstation, RTX 5070 Ti |
| LLM for generation | GPT-4, LLaMA (API or large GPU) | qwen3-coder:30b (local Ollama) |
| Docking | Cloud docking services or RoseTTAFold | AutoDock Vina (local binary) |
| Cost per cycle | High (API calls throughout) | Near-zero (local compute + 1 escalation) |
| Integration | Standalone pipeline | Integrated with personal AI assistant |
| Real-time alerts | Not typically implemented | TTS + email via Nova ResearchWatcher |
| Human interface | Web dashboard or CLI | Voice + web UI via Nova |

The Nova system's most distinctive characteristic is the **local-first, escalation-funnel** architecture that keeps costs near zero while the loop runs indefinitely. Academic systems typically call paid APIs at every stage; Nova calls them only for the final analysis of survivors.

### Automated Mathematical Conjecture Generation

The mathematics researcher also has clear precedents, though again with important differences.

A 2025 paper on artificial intelligence in number theory evaluated large language models on algorithmic and computational tasks in number theory. Using Qwen2.5-Math, the study achieved high accuracy on algorithmic problems and computational questions from classical number-theoretic textbooks when given appropriate prompting.

LeanConjecturer, published in 2025, addresses automatic generation of mathematical conjectures for theorem proving. It uses an iterative pipeline where LLMs generate conjectures from Mathlib files, evaluate them, and iteratively refine, allowing continuous generation of novel conjectures while maintaining mathematical validity.

The Enumerate–Conjecture–Prove (ECP) framework, inspired by mathematician George Pólya's problem-solving methodology, combines the exploratory strengths of LLMs — which enumerate candidate answers through programmatic execution and generalise patterns to form conjectures — with the rigour of formal theorem-proving methods that verify these conjectures.

The Nova math researcher takes a simpler but highly practical approach: it does not attempt formal proof in Lean or Isabelle, but instead uses numerical verification across large test ranges and then asks Claude to attempt an informal proof sketch and assess plausibility. This is closer in spirit to the experimental mathematics tradition than to the formal verification literature.

### Multi-Agent Scientific Discovery

The planner → manager → executor → supervisor architecture in Nova has parallels in the broader multi-agent AI literature:

Frameworks such as ACCELMAT for materials science use a structured, iterative loop of proposal and critique among multiple agents to progressively enhance the quality of novel material hypotheses. VIRSCI extends this by simulating scientific teams using real-world academic data, enabling agents to form collaborative research teams and generate novel ideas through inter- and intra-team discussion. AstroAgents deploys domain-specific agents to interpret mass spectrometry data and hypothesise about prebiotic chemical pathways, with more than 30% of hypotheses validated as scientifically plausible by expert reviewers.

Prominent frameworks including ResearchAgent and Agent Laboratory have made strides in automating general research workflows such as citation management, document discovery, and academic survey generation. ChatMOF is an autonomous AI system for predicting and generating metal-organic frameworks.

### What Is Genuinely Novel About This System

Given the literature above, the following aspects of the Nova Hyperion Research Engine represent contributions that are either not present in or meaningfully different from published work:

**1. Integration with a persistent personal AI assistant.** No published system integrates an autonomous research loop with a continuously running personal assistant that can be queried by voice, send email alerts, speak findings via TTS, and maintain conversational context about prior findings. The ResearchWatcher / Nova integration is unique in this respect.

**2. Local-first, near-zero-cost indefinite operation.** Published drug discovery pipelines call cloud APIs at every stage. The Nova engine runs hypothesis generation, structural validation, novelty checking, ADMET prediction, and molecular docking entirely locally, calling a paid API only for the final escalation. This allows indefinite autonomous operation at negligible cost on consumer hardware.

**3. Pose consistency quality scoring for docking.** The systematic flagging of docking results as `consistent`, `moderate`, or `unreliable` based on the spread across all 9 Vina poses and the count of physically reasonable (negative energy) poses is a practical quality control step not commonly described in published LLM-docking pipelines.

**4. Scaffold correction feedback loop.** The explicit comparison of Ollama's claimed scaffold name against RDKit's SMARTS-based classification, passed directly to Claude's analysis prompt, creates a built-in structural sanity check. This corrects Ollama's frequent misidentification of scaffold classes and ensures Claude's analysis addresses the real structure rather than the hallucinated one.

**5. Domain-agnostic journal architecture.** The uniform JSON journal schema, alert file pattern, and `nova_research_digest.py` tool registration system allow any new research domain to be added by implementing a generator, a validator, and a novelty checker — with no changes to Nova itself.

### References

The following works are directly relevant to the techniques and concepts used in this system:

**Autonomous Scientific Discovery — Surveys**

- Zhang et al. (2025). *From Automation to Autonomy: A Survey on Large Language Models in Scientific Discovery*. arXiv:2505.13259.
- Schmidgall et al. (2025). *Agentic AI for Scientific Discovery: A Survey of Progress, Challenges, and Future Directions*. arXiv:2503.08979.
- Fink et al. (2024). *AI for Scientific Discovery*. World Economic Forum Top-10-Technologies Report.

**AI Drug Discovery Pipelines**

- ChatMED (2025). *Prompt-to-Pill: Multi-Agent Drug Discovery and Clinical Simulation Pipeline*. bioRxiv:2025.08.12.
- Cao et al. (2025). *Mozi: Governed Autonomy for Drug Discovery LLM Agents*. arXiv:2603.03655.
- Anonymous (2025). *Large Language Model Agent for Modular Task Execution in Drug Discovery (AgentD)*. arXiv:2507.02925.
- Anonymous (2025). *FROGENT: An End-to-End Full-process Drug Design Multi-Agent System*. arXiv:2508.10760.
- Kim et al. (2016). *PubChem Substance and Compound Databases*. Nucleic Acids Research, 44(D1):D1202–D1213.

**Molecular Docking**

- Eberhardt et al. (2021). *AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings*. Journal of Chemical Information and Modeling, 61(8):3891–3898.
- Landrum, G. (2023). *RDKit: Open-Source Cheminformatics*. https://www.rdkit.org.

**Mathematical AI and Conjecture Generation**

- Saraeb, A. (2025). *Artificial Intelligence in Number Theory: LLMs for Algorithm Generation and Ensemble Methods for Conjecture Verification*. arXiv:2504.19451.
- Anonymous (2025). *LeanConjecturer: Automatic Generation of Mathematical Conjectures for Theorem Proving*. arXiv:2506.22005.
- Anonymous (2025). *Enumerate–Conjecture–Prove: Formally Solving Answer-Construction Problems in Math Competitions*. arXiv:2505.18492.
- Dong & Ma (2025). *Self-Play and Conjecture Generation (STP)*. arXiv:2501.xxxxx.

**Multi-Agent Research Systems**

- Kumbhar et al. (2025). *Hypothesis Generation for Materials Discovery and Design Using Goal-Driven and Constraint-Guided LLM Agents (ACCELMAT)*. arXiv:2501.13299.
- Su et al. (2024). *VIRSCI: Simulating Scientific Teams Using Real-World Academic Data*. 
- Saeedi et al. (2025). *AstroAgents: Domain-Specific Agents for Mass Spectrometry and Prebiotic Chemistry*.
- Baek et al. (2024). *ResearchAgent: Iterative Research Idea Generation Using LLMs over Scientific Literature*.

**Google DeepMind AlphaEvolve**

- Gibney, E. (2025). *DeepMind's AlphaEvolve AI Discovers New Algorithm for Matrix Multiplication*. Nature News.

---

*Nova Hyperion Research Engine — Autonomous Scientific Discovery*
*Dr Tom Moir — Birkdale, Auckland, New Zealand*
*Built with Nova, Ollama, RDKit, AutoDock Vina, and Claude*

---

## Installation and Setup

This section covers everything that must be installed and configured before the research engine will run. Follow the steps in order.

---

### 1. Python Virtual Environment

The entire project runs inside a Python virtual environment. The `.venv` folder lives inside the project directory and keeps all dependencies isolated from other Python projects on the machine.

**Create and activate:**

```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
python -m venv .venv
.venv\Scripts\activate
```

The prompt changes to `(.venv)` when the environment is active. Every `pip install` below must be run with the environment active. Every time a new terminal is opened to run Nova or the researcher, activate first.

---

### 2. Python Packages

With the virtual environment active:

```powershell
pip install rdkit
pip install httpx
pip install python-dotenv
pip install sympy
pip install mpmath
pip install pdbfixer
pip install openmm
pip install openbabel-wheel
pip install openai-whisper
pip install edge-tts
pip install pyaudio
pip install SpeechRecognition
pip install requests
pip install aiohttp
pip install cryptography
pip install pillow
```

> **openbabel-wheel** — use this, not `pip install openbabel`. The plain version requires a C++ compiler and fails on Windows. The `-wheel` variant is pre-compiled and installs cleanly.

**For CUDA acceleration (RTX 5070 Ti):**

```powershell
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install faster-whisper
```

Match `cu128` to your installed CUDA version — run `nvcc --version` to check.

---

### 3. AutoDock Vina

Vina is a standalone binary, not a Python package.

Download from: `https://github.com/ccsb-scripps/AutoDock-Vina/releases`

Download `vina_1.2.7_windows_x86_64.exe`, rename it to `vina.exe`, and place it at:

```
C:\vina\vina.exe
```

Test with:

```powershell
vina --version
```

---

### 4. Ollama

Ollama serves local LLMs for hypothesis generation. Download the Windows installer from `https://ollama.com` and run it. Ollama installs as a background service that starts automatically on login and listens on `http://localhost:11434`.

Pull the model used for hypothesis generation:

```powershell
ollama pull qwen3-coder:30b
```

This downloads approximately 20 GB. Verify the model is available:

```powershell
ollama list
```

---

### 5. The .env File

The `.env` file stores all secrets and configuration that must not be hard-coded into source files. It lives in the project root alongside `nova_assistant.py`:

```
C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1\.env
```

Create it with any text editor. The complete contents:

```env
# ── OpenRouter (Claude access) ───────────────────────────────────────────────
OPENROUTER_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Brave Search (Nova web search) ──────────────────────────────────────────
BRAVE_KEY=BSAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Email alerts ─────────────────────────────────────────────────────────────
NOTIFY_EMAIL_FROM=yourgmailaddress@gmail.com
NOTIFY_EMAIL_TO=yourgmailaddress@gmail.com
NOTIFY_EMAIL_PASS=xxxx xxxx xxxx xxxx

# ── AutoDock Vina binary ─────────────────────────────────────────────────────
VINA_EXE=C:\vina\vina.exe
```

The file is read at startup by `python-dotenv`:

```python
from dotenv import load_dotenv
load_dotenv()
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "")
```

**The `.env` file must never be committed to Git or shared.** Add it to `.gitignore`:

```
.env
.venv/
```

---

### 6. OpenRouter API Key (`OPENROUTER_KEY`)

OpenRouter provides access to Claude Sonnet and many other models through a single unified API endpoint. It is the only paid external service the research engine calls — and only when a compound or conjecture passes all local filters and is escalated for deep analysis.

**Getting the key:**

1. Go to `https://openrouter.ai` and create a free account
2. Navigate to **Keys** in the left sidebar
3. Click **Create Key**, give it a name (e.g. `Nova Research`)
4. Copy the key — it starts with `sk-or-v1-`
5. Paste it into `.env` as `OPENROUTER_KEY=sk-or-v1-...`

**Adding credit:**

OpenRouter uses prepaid credit. Navigate to **Credits** in the dashboard and add a small amount — $5 covers many hundreds of escalated analyses at Claude Sonnet pricing. The research engine is very conservative: it only calls Claude for compounds that pass Lipinski, PubChem novelty, and docking threshold — typically 1–3 calls per hour of running time.

**Changing the model:**

The model is set in `nova_chemistry_researcher.py`:

```python
OPENROUTER_MODEL = "anthropic/claude-sonnet-4-5"
```

Any model listed at `https://openrouter.ai/models` can be substituted. Claude Opus gives more thorough analysis; cheaper models like DeepSeek reduce cost further.

---

### 7. Brave Search API Key (`BRAVE_KEY`)

The Brave Search key gives Nova access to web search for general queries and for the GOOF button in the code execution loop. It is not used directly by the chemistry or math researchers.

**Getting the key:**

1. Go to `https://api.search.brave.com`
2. Create a free developer account
3. Navigate to **API Keys** and create a new key
4. The free tier provides 2,000 queries per month — sufficient for personal use
5. Paste into `.env` as `BRAVE_KEY=BSA...`

If this key is left blank, Nova will still function but web search queries will fail silently.

---

### 8. Gmail App Password (`NOTIFY_EMAIL_PASS`)

The research engine sends email alerts when a finding passes all filters. It uses Gmail's SMTP server with a dedicated **App Password** — not your regular Gmail password. App Passwords are required because Google blocks standard password login over SMTP when two-factor authentication is enabled.

**Step 1 — Enable 2-Step Verification** (if not already on):

1. Go to `https://myaccount.google.com/security`
2. Under **How you sign in to Google**, click **2-Step Verification**
3. Follow the setup steps

**Step 2 — Create the App Password:**

1. Go to `https://myaccount.google.com/apppasswords`
   (or from Security → 2-Step Verification → scroll to bottom → App passwords)
2. In the **App name** field type `Nova Research`
3. Click **Create**
4. Google displays a 16-character password in the format `xxxx xxxx xxxx xxxx`
5. **Copy it immediately** — Google will not show it again
6. Paste it into `.env` as `NOTIFY_EMAIL_PASS=xxxx xxxx xxxx xxxx` (keep the spaces)

**SMTP settings used by the engine:**

```python
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587          # STARTTLS
```

The `FROM` and `TO` addresses can be the same Gmail account — you email yourself. The subject line will read `[Nova Chemistry] ESCALATED: Compound name...` or `[Nova Research] VERIFIED: Conjecture...`

**If you do not want email alerts**, leave all three `NOTIFY_EMAIL_*` variables blank. The engine logs a warning but continues running without sending emails.

---

### 9. Verifying the Setup

With `.env` in place and the virtual environment active, verify all components:

**Check environment variables loaded:**

```powershell
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
print('OpenRouter key:', 'OK' if os.getenv('OPENROUTER_KEY') else 'MISSING')
print('Brave key:     ', 'OK' if os.getenv('BRAVE_KEY') else 'MISSING')
print('Email from:    ', 'OK' if os.getenv('NOTIFY_EMAIL_FROM') else 'MISSING')
print('Email pass:    ', 'OK' if os.getenv('NOTIFY_EMAIL_PASS') else 'MISSING')

"
```

**Check RDKit:**

```powershell
python -c "from rdkit import Chem; m = Chem.MolFromSmiles('c1ccccc1'); print('RDKit OK — benzene:', m.GetNumAt# Nova Hyperion Research Engine
## Autonomous Multi-Domain Scientific Discovery

---

## Table of Contents

1. [Overview](#overview)
2. [Theoretical Foundation](#theoretical-foundation)
3. [Architecture](#architecture)
4. [Mathematical Research Engine](#mathematical-research-engine)
5. [Cancer Drug Discovery Engine](#cancer-drug-discovery-engine)
6. [Integration with Nova](#integration-with-nova)
7. [Operating the Research Engine](#operating-the-research-engine)
8. [Extending to New Research Domains](#extending-to-new-research-domains)
9. [Technical Reference](#technical-reference)
10. [Querying Nova for Research Results](#querying-nova-for-research-results)
11. [Academic Context and Originality](#academic-context-and-originality)

---

## Overview

The Nova Hyperion Research Engine is an autonomous, multi-agent scientific research system that runs continuously in the background, generating hypotheses, validating them computationally, and escalating only the most promising findings to a large language model for deep analysis. Nova (the main AI assistant) receives alerts in real time and can query the accumulated findings at any time.

The engine embodies a core principle: **use cheap, fast, local computation for 99% of the filtering, and reserve expensive API calls for the 1% that genuinely deserve deep analysis.**

Two research domains are currently implemented:

- **Mathematics** — autonomous conjecture generation and numerical verification
- **Cancer Drug Discovery** — autonomous molecule generation, validation, docking, and oncology analysis

Both share the same architectural pattern and can be extended to any domain where hypotheses can be generated cheaply and validated computationally.

---

## Theoretical Foundation

### The Escalation Funnel

The central idea is a multi-stage filter funnel. Each stage is faster and cheaper than the next, and only survivors of each stage proceed further.

```
Stage 1: Hypothesis Generation        (local LLM, free)
           ↓  ~50% pass
Stage 2: Structural / Formal Filter   (RDKit / symbolic, free)
           ↓  ~30% pass
Stage 3: Novelty Check                (public APIs, free)
           ↓  ~20% pass
Stage 4: Computational Validation     (docking / numerical, free)
           ↓  ~5% pass
Stage 5: Deep AI Analysis             (Claude via API, paid)
           ↓  ~2% of original
Stage 6: Human Review                 (Dr Moir)
```

This means Claude sees roughly 1–2 compounds per 50–100 cycles, keeping costs minimal while ensuring every analysis is genuinely warranted.

### Local-First Philosophy

All heavy computation runs locally:
- **Ollama** serves open-source LLMs (qwen3-coder:30b) for hypothesis generation on the RTX 5070 Ti GPU
- **RDKit** performs cheminformatics validation entirely in Python with no external calls
- **AutoDock Vina** runs molecular docking locally against pre-prepared receptor files
- **Whisper** handles voice recognition locally

Only the final escalation step calls an external paid API (OpenRouter → Claude Sonnet). This means the system can run indefinitely at near-zero marginal cost.

### Autonomous Loop Design

Each researcher runs as an infinite async loop with a configurable sleep interval between cycles. The loop is:

```
while running:
    domain = next_domain()
    hypothesis = generate()
    if not validate(hypothesis): continue
    if not novel(hypothesis): continue
    if not passes_computational_filter(hypothesis): continue
    analysis = escalate_to_claude(hypothesis)
    save_report(analysis)
    notify_nova(analysis)
    sleep(LOOP_INTERVAL_S)
```

This design means the researcher is fully autonomous — it requires no human intervention and generates a growing dataset of validated findings over time.

---

## Architecture

### Component Overview

```
NovaHyperionResearch_v1/
│
├── nova_assistant.py              # Nova main assistant
├── nova_research_hooks.py         # Alert watcher — polls for new findings
│
├── nova_math_researcher.py        # Mathematics research loop
├── nova_chemistry_researcher.py   # Cancer drug discovery loop
├── nova_docking.py                # AutoDock Vina pipeline
│
├── tools/
│   └── nova_research_digest.py    # Nova tool — query accumulated findings
│
├── chemistry_journal.json         # Chemistry findings database
├── research_journal.json          # Mathematics findings database
│
├── docking_data/
│   ├── receptors/                 # Prepared PDBQT receptor files (cached)
│   └── results/                   # Ligand PDBQT and docked output files
│
└── nova_outputs/
    ├── chemistry/                 # HTML reports for chemistry findings
    └── research/                  # HTML reports for math findings
```

### Data Flow

```
Ollama (local GPU)
    ↓ hypothesis JSON
Researcher loop
    ↓ SMILES / conjecture
RDKit / Python validator
    ↓ valid + drug-like
PubChem / arXiv API
    ↓ novel
AutoDock Vina (local)
    ↓ docking score ≤ threshold
Claude Sonnet (OpenRouter)
    ↓ full analysis
chemistry_journal.json
    ↓ written
chemistry_alert.json
    ↓ polled every 30s
ResearchWatcher (Nova)
    ↓ spoken + email
Dr Moir
```

---

## Mathematical Research Engine

### What It Does

The math researcher autonomously generates conjectures in number theory, combinatorics, and related areas, then tests them against thousands of cases numerically. Conjectures that survive are escalated to Claude for proof attempts.

### Hypothesis Generation

Ollama is prompted with a mathematical domain (e.g., "properties of prime gaps", "divisibility patterns in Fibonacci sequences") and asked to produce a structured conjecture:

```json
{
  "conjecture": "For all primes p > 2, p² - 1 is divisible by 24",
  "domain": "number theory",
  "variables": ["p"],
  "test_range": [3, 10000]
}
```

### Numerical Verification

The conjecture is parsed and tested against the specified range using Python's `sympy` and `mpmath` libraries. A conjecture passes if it holds for all test cases with no counterexample found:

```python
for p in primes_in_range(test_range):
    if not evaluate_conjecture(conjecture, p):
        return "counterexample_found"
return "verified", cases_tested
```

### Escalation Criteria

A conjecture escalates to Claude if:
- It holds for ≥ 100 consecutive cases with no counterexample
- It is not trivially equivalent to a known theorem (arXiv check)
- The symbolic verifier (`sympy_exec`) cannot immediately disprove it

### Output

Each verified conjecture produces:
- A JSON entry in `research_journal.json` with the conjecture text, domain, case count, and Claude's proof attempt
- An HTML report with MathJax-rendered equations
- A spoken alert via Nova's TTS
- An email with a clickable link to the full report

---

## Cancer Drug Discovery Engine

### What It Does

The chemistry researcher autonomously generates novel small molecule drug candidates, validates their chemical properties, checks for novelty, predicts ADMET (absorption, distribution, metabolism, excretion, toxicity) properties, docks them against validated cancer protein targets, and escalates survivors to Claude for full oncology analysis.

### The Drug Discovery Pipeline

#### Stage 1 — Hypothesis Generation (Ollama)

The qwen3-coder:30b model is prompted with a specific oncology research domain and asked to generate a structured drug hypothesis:

```json
{
  "name": "Compound name",
  "smiles": "CC1=CC(=CC(=C1N)...",
  "target": "CDK4/6 kinase",
  "cancer_type": "Hormone receptor positive breast cancer",
  "mechanism": "CDK4/6 inhibitor",
  "hypothesis": "This compound inhibits...",
  "novelty_claim": "Unlike palbociclib..."
}
```

The model is instructed to use well-known scaffolds (quinazoline, pyrimidine, piperazine) with novel substituent combinations, keeping MW under 480 Da and LogP under 4.5.

#### Stage 2 — Structural Validation (RDKit)

The SMILES string is parsed by RDKit. If invalid, Ollama is asked to repair it once. Valid structures are evaluated against Lipinski's Rule of Five:

| Property | Limit | Rationale |
|---|---|---|
| Molecular Weight (MW) | ≤ 500 Da | Oral bioavailability |
| LogP (lipophilicity) | ≤ 5 | Membrane permeability |
| H-bond donors (HBD) | ≤ 5 | Solubility |
| H-bond acceptors (HBA) | ≤ 10 | Absorption |

Compounds with more than one violation are discarded as not drug-like. PAINS (Pan-Assay Interference Compounds) alerts are also flagged.

RDKit also classifies the scaffold using SMARTS pattern matching:

```python
SCAFFOLD_PATTERNS = {
    "Quinazoline":   "c1nc2ccccc2nc1",
    "Hydantoin":     "[#7]1C(=O)[#7]CC1=O",
    "Piperazine":    "C1CNCCN1",
    "Triazine":      "c1ncncn1",
    # ... 15 patterns total
}
```

This allows Claude to immediately identify mismatches between what Ollama claimed the scaffold is and what RDKit actually found in the SMILES.

#### Stage 3 — Novelty Check (PubChem)

The SMILES is submitted to PubChem's REST API to check for exact structure matches:

```
GET https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/cids/JSON
```

If a real CID is returned (CID > 0), the compound is known and discarded. If not found, it is potentially novel. At this point, PubChem's IUPAC naming endpoint is also queried to get a proper chemical name for the structure, correcting Ollama's invented names.

ChEMBL is then searched for structurally similar compounds (≥ 70% Tanimoto similarity) to understand what the closest known drugs look like and their clinical phases.

#### Stage 4 — ADMET Prediction (RDKit)

Drug-like ADMET properties are estimated from molecular descriptors:

| Property | Method | Threshold |
|---|---|---|
| GI Absorption | Veber rules (TPSA ≤ 140, rotatable bonds ≤ 10) | High |
| BBB Permeability | TPSA < 90, MW < 450, LogP > 0, HBD ≤ 3 | Yes/No |
| Water Solubility | LogP estimate | High/Good/Moderate/Poor |
| CYP Inhibition Risk | Aromatic rings ≥ 3 and LogP > 3 | Risk/Low risk |
| Druglikeness | Lipinski + Veber combined | Drug-like/Borderline/Non drug-like |

#### Stage 5 — Molecular Docking (AutoDock Vina)

This is the key computational filter. The compound is docked against validated cancer protein targets to predict binding affinity.

**Receptor Preparation:**

Crystal structures are downloaded from RCSB Protein Data Bank and prepared using pdbfixer (missing atoms, hydrogens at pH 7.4) and OpenBabel (PDBQT format with Gasteiger charges). Receptors are cached after first preparation.

**Current Targets:**

| Target | PDB ID | Cancer | Drug Class |
|---|---|---|---|
| EGFR | 2ITY | NSCLC, breast | Erlotinib, gefitinib, osimertinib |
| BCL2 | 4LVT | CLL, lymphoma | Venetoclax |
| CDK2 | 1AQ1 | Breast, solid tumours | Palbociclib, ribociclib |
| PARP1 | 3L3M | BRCA-mutated ovarian, breast | Olaparib, niraparib |

**Binding Site Coordinates:**

Binding site centres are extracted from co-crystallised ligands in the PDB structures. For example, for PARP1 (3L3M), the NAD+ binding site centre is at (26.4, 11.2, 27.0) Å.

**Ligand Preparation:**

The SMILES is converted to a 3D conformer using RDKit's ETKDGv3 conformer generator, optimised with MMFF94 force field, then converted to PDBQT format via OpenBabel with Gasteiger charges.

**Scoring:**

AutoDock Vina uses a knowledge-based scoring function. The output is a binding affinity in kcal/mol (more negative = stronger predicted binding). Scores are calibrated for OpenBabel receptor preparation:

| Score (kcal/mol) | Grade | Interpretation |
|---|---|---|
| ≤ −7.0 | EXCELLENT | Comparable to approved drugs |
| ≤ −5.5 | GOOD | Promising lead |
| ≤ −4.0 | MODERATE | Weak, needs optimisation |
| > −4.0 | POOR | Unlikely to show activity |

**Pose Consistency:**

A novel quality check examines all 9 docking poses. Reliable docking shows a tight cluster of scores; unreliable docking shows a large spread or many positive-energy poses:

```python
spread = max(all_scores) - min(all_scores)
valid  = len([s for s in all_scores if s < 0])

if spread < 5 and valid >= 5:   quality = "consistent"
elif spread < 15 and valid >= 3: quality = "moderate"
else:                             quality = "unreliable"
```

An unreliable CDK2 score like `[-8.35, -1.99, 0.49, 3.17, 1189.0]` (spread = 1197) is flagged and Claude is told not to rely on it.

**Docking Filter:**

Compounds scoring above −5.5 kcal/mol against all targets are discarded with status `poor_docking`. Only those with at least one target below the threshold proceed to Claude.

#### Stage 6 — Claude Oncology Analysis

The surviving compound's full data package is assembled into a structured prompt:

```
Compound: [name]
SMILES: [smiles]
Actual scaffold (RDKit): [scaffold]
Target: [target]
Cancer type: [cancer]
Mechanism: [mechanism]
Molecular properties: MW=..., LogP=..., Scaffold=...
PubChem: Not found (novel)
ChEMBL similarity: [similar compounds]
ADMET: GI=High, BBB=No, Solubility=Good...
AutoDock Vina scores:
  PARP1 (NAD+ pocket): -9.67 kcal/mol [EXCELLENT]
  CDK2 (ATP cleft): -7.59 kcal/mol [EXCELLENT] ⚠️ moderate
```

Claude's ONCOLOGY_SYSTEM prompt instructs it to cover seven sections: therapeutic potential, mechanism of action, structural analysis (using the RDKit scaffold to resolve name/structure mismatches), docking interpretation, ADMET assessment, development pathway, and a verdict with confidence level.

---

## Integration with Nova

### ResearchWatcher

`nova_research_hooks.py` contains the `ResearchWatcher` class which polls two alert files every 30 seconds using Tkinter's `root.after()` scheduler:

```python
ALERT_FILE      = Path("research_alert.json")    # math
CHEM_ALERT_FILE = Path(r"C:\...\chemistry_alert.json")  # chemistry
```

When a new alert appears, the watcher:
1. Reads and deletes the alert file
2. Appends the finding to Nova's conversation
3. Speaks the alert via Edge TTS
4. Sends an email with a link to the HTML report

### Nova Tool — Research Digest

`tools/nova_research_digest.py` provides two Nova tools:

**`get_research_digest`** — Called when you ask Nova "What did the chemistry researcher find?" Returns a Claude-narrated summary of all survivors from the journal, with docking scores, compound properties, and verdicts.

**`list_research_findings`** — Returns all findings one by one with full detail, suitable for reading aloud.

The tool routes to the correct journal based on query keywords:
- "chem" → chemistry journal only
- "math", "conjecture" → math journal only
- anything else → both journals

### Asking Nova About Research

```
"What did the chemistry researcher find?"
"List all chemistry survivors with their docking scores"
"Show me the full research digest"
"What did you find overnight?"
"Show me finding five in detail"
```

---

## Operating the Research Engine

### Starting Both Researchers

Open two PowerShell terminals in the project directory:

**Terminal 1 — Chemistry Researcher:**
```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_chemistry_researcher.py
```

**Terminal 2 — Nova (with Math Researcher):**
```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_assistant.py
```

### Monitoring

**Chemistry Dashboard** — `http://localhost:8083` — refreshes every 5 seconds showing:
- Current cycle phase (generating / verifying / pubchem / docking / escalating)
- Active hypothesis and SMILES
- Live docking scores
- Recent survivors with scores
- Live log tail

### Configuration

Key settings in `nova_chemistry_researcher.py`:

```python
OLLAMA_MODEL          = "qwen3-coder:30b"    # Local model for generation
LOOP_INTERVAL_S       = 20                    # Seconds between cycles
DOCK_SCORE_THRESHOLD  = -5.5                  # kcal/mol filter threshold
DOCK_EXHAUSTIVENESS   = 8                     # Vina search exhaustiveness
CHEMBL_SIMILARITY     = 70                    # % similarity for ChEMBL search
```

Key settings in `nova_docking.py`:

```python
SCORE_EXCELLENT = -7.0   # Calibrated for OpenBabel prep
SCORE_GOOD      = -5.5
SCORE_MODERATE  = -4.0
```

### Journal Files

All findings are stored as JSON arrays in flat files. The chemistry journal entry structure:

```json
{
  "type": "hypothesis",
  "status": "promising",
  "timestamp": "2026-05-07T08:00:00",
  "hypothesis": {
    "name": "Compound name",
    "smiles": "...",
    "target": "PARP1",
    "cancer_type": "BRCA-mutated ovarian cancer",
    "ollama_name": "Original Ollama label"
  },
  "verification": {
    "valid": true,
    "mw": 348.32,
    "logp": 0.94,
    "lipinski_ok": true,
    "scaffold_class": "Pyrimidine",
    "violations": [],
    "alerts": []
  },
  "pubchem": { "found": false, "cid": null },
  "chembl": { "similar_compounds": [], "max_similarity": 0 },
  "admet": {
    "gi_absorption": "High",
    "bbb_permeant": "No",
    "water_solubility": "High",
    "druglikeness": "Drug-like"
  },
  "docking": {
    "best_score": -10.08,
    "best_target": "PARP1",
    "passes_filter": true,
    "pose_warnings": {},
    "results": {
      "PARP1": {
        "score": -10.08,
        "grade": "EXCELLENT",
        "pose_quality": "consistent",
        "pose_spread": 3.97,
        "pose_valid": 9
      }
    }
  },
  "analysis": "# Comprehensive Oncology Analysis..."
}
```

### HTML Reports

Each escalated finding generates a dark-theme HTML report at `nova_outputs/chemistry/cancer_YYYYMMDD_HHMMSS_[name].html` containing:
- Status badge and cancer type badge
- RDKit scaffold badge (🔬)
- Molecular properties table with Lipinski status
- ADMET predictions (GI, BBB, solubility, CYP risk, druglikeness)
- ChEMBL similar compounds table
- AutoDock Vina binding scores table with pose quality indicators
- Claude's full oncology analysis with markdown rendering

---

## Extending to New Research Domains

The architecture is domain-agnostic. Any research domain can be added by implementing three components:

### 1. Hypothesis Generator

Create a function that prompts Ollama (or any LLM) to generate a structured hypothesis JSON for your domain:

```python
async def generate_hypothesis(domain: str) -> Optional[dict]:
    system = """You are an expert in [your domain].
    Generate one hypothesis. Respond ONLY with valid JSON:
    {
      "name": "Hypothesis name",
      "description": "What this hypothesis claims",
      "testable_prediction": "What we can check computationally",
      "domain": "Specific sub-domain",
      "novelty_claim": "Why this is new"
    }"""
    raw = await ollama_generate(f"Generate a hypothesis for: {domain}", system=system)
    # parse JSON...
```

### 2. Computational Validator

Implement whatever local validation is appropriate for your domain:

| Domain | Validator |
|---|---|
| Chemistry | RDKit structural validation, Lipinski rules, docking |
| Mathematics | sympy symbolic verification, numerical testing |
| Materials Science | pymatgen structure validation, DFT energy estimation |
| Protein Engineering | BioPython structure validation, AlphaFold2 folding prediction |
| Epidemiology | Statistical significance tests, model fitting |
| Astrophysics | Orbital mechanics simulation, spectra matching |

The validator should return a dict with `valid: bool` and any computed properties.

### 3. Novelty Check

Check your domain's primary database for prior art:

| Domain | Novelty Database |
|---|---|
| Chemistry | PubChem, ChEMBL |
| Mathematics | arXiv, OEIS |
| Materials | Materials Project, ICSD |
| Biology | UniProt, PDB |
| Literature | Semantic Scholar, arXiv |

### 4. Register the Journal

Add the new journal to `tools/nova_research_digest.py`:

```python
JOURNALS = {
    "math":      _HERE.parent / "research_journal.json",
    "chemistry": _HERE.parent / "chemistry_journal.json",
    "materials": _HERE.parent / "materials_journal.json",  # new
}
```

And add a `_summarise_materials()` function following the same pattern as `_summarise_chemistry()`.

### 5. Register the Alert File

Add the new alert file to `nova_research_hooks.py`:

```python
CHEM_ALERT_FILE      = Path(r"...\chemistry_alert.json")
MATERIALS_ALERT_FILE = Path(r"...\materials_alert.json")  # new
```

And add a `_handle_materials()` method to `ResearchWatcher._poll()`.

### Example: Materials Science Extension

A materials researcher could generate hypotheses about novel crystal structures, validate them using pymatgen, check the Materials Project for novelty, run a quick DFT energy estimate with ASE, and escalate promising low-energy structures to Claude for analysis of their electronic and mechanical properties.

The same escalation funnel applies:

```
Ollama generates crystal structure hypothesis
    ↓
pymatgen validates symmetry and composition
    ↓
Materials Project checks for novelty
    ↓
ASE/DFT estimates formation energy
    ↓
Claude analyses thermodynamic stability and applications
    ↓
Nova alerts Dr Moir
```

---

## Technical Reference

### Dependencies

```
# Core
rdkit                 # Cheminformatics
httpx                 # Async HTTP
python-dotenv         # Environment variables

# Docking
openbabel-wheel       # Molecular file format conversion
pdbfixer              # PDB structure preparation
openmm                # Molecular mechanics

# Nova
openai-whisper        # Voice recognition
edge-tts              # Text-to-speech

# External binaries
AutoDock Vina 1.2.7   # Molecular docking
```

### Environment Variables (.env)

```
OPENROUTER_KEY=sk-or-...        # Required for Claude escalation
BRAVE_KEY=...                   # Optional for web search
NOTIFY_EMAIL_FROM=...           # Gmail for alerts
NOTIFY_EMAIL_TO=...
NOTIFY_EMAIL_PASS=...           # Gmail app password
VINA_EXE=C:\vina.exe           # Path to AutoDock Vina binary
```

### Docking Score Calibration

The scores reported by AutoDock Vina depend on how the receptor and ligand were prepared. This system uses OpenBabel for preparation, which consistently gives scores approximately 2–3 kcal/mol less negative than MGLTools-prepared structures. All thresholds are calibrated accordingly. The reference calibration was performed by docking erlotinib (an approved EGFR inhibitor) against the 2ITY structure, which yielded −6.7 kcal/mol with this pipeline vs. the literature-reported −9 to −11 kcal/mol from MGLTools. Thresholds were adjusted to match this systematic offset.

### Performance

On an RTX 5070 Ti with qwen3-coder:30b via Ollama:
- Hypothesis generation: ~45 seconds per cycle
- RDKit validation: < 0.1 seconds
- PubChem API check: ~1–2 seconds
- Docking (exhaustiveness=8): ~30–60 seconds per target
- Claude analysis: ~10–20 seconds

A full successful cycle (generation through Claude analysis) takes approximately 2–5 minutes. Failed cycles (discarded at early stages) complete in under 60 seconds. Expect 1–3 survivors per hour of running time.

### Troubleshooting

**No JSON in hypothesis output** — qwen3 may output `<think>...</think>` blocks before JSON. The `ollama_generate` function strips these automatically with `re.sub(r'<think>.*?</think>', '', raw)`.

**PubChem CID = 0** — The `/cids/JSON` endpoint returns 0 as a sentinel for "not found". Filter with `[c for c in cids if c > 0]`.

**Docking fails with BCL2** — The BCL2 receptor PDBQT may have formatting issues. Delete `docking_data/receptors/BCL2_receptor.pdbqt` and let it regenerate.

**Dashboard KeyError** — Conditional class expressions like `{'g' if x else 'r'}` inside `.format()` template strings cause KeyErrors. Pre-compute all conditional values as named variables before calling `.format()`.

---

---

## Querying Nova for Research Results

Nova can be asked about research findings at any time — whether the researcher has just started or has been running overnight. All queries are spoken naturally into the voice interface or typed into the web UI. The following sections cover every useful query pattern.

### Basic Queries — Chemistry

These trigger the `get_research_digest` tool directly and return a Claude-narrated spoken summary of all chemistry survivors:

```
"What did the chemistry researcher find?"
"Show me the chemistry results"
"What compounds has the cancer researcher discovered?"
"Give me a chemistry digest"
"What did you find in chemistry overnight?"
```

Any query containing the word **"chem"** routes automatically to the chemistry journal. Nova will respond with each survivor's compound name, cancer target, best docking score, ADMET summary, and a verdict on whether it is worth pursuing.

### Basic Queries — Mathematics

```
"What did the math researcher find?"
"Show me the conjecture results"
"What number theory findings are there?"
"Give me the maths digest"
```

Any query containing **"math"**, **"maths"**, **"conjecture"**, or **"number"** routes to the mathematics journal.

### Full Digest — Both Researchers

```
"Give me the full research digest"
"What did you find overnight?"
"Show me all research results"
"Research digest"
```

Queries with no domain keyword read both journals and return a combined summary.

### Listing All Findings in Detail

To get every finding listed individually rather than summarised:

```
"List all chemistry survivors with their docking scores"
"List all research findings one by one"
"Go through each chemistry finding"
"Show me all compounds and their scores"
```

This triggers `list_research_findings`, which reads each survivor from the journal and presents it with full compound name, target, docking score, molecular properties, and timestamp.

### Asking for a Specific Finding

Nova can retrieve and present a particular finding by number:

```
"Show me finding five in detail"
"Tell me about the third chemistry result"
"What was the best docking hit?"
"Which compound had the highest PARP1 score?"
```

When asking by number, the planner will first call `get_research_digest` to retrieve the full list, then the text agent will extract and present the requested finding in a formatted table.

### Asking About Specific Targets or Properties

```
"Which compounds docked well against EGFR?"
"Show me the PARP1 results"
"Which findings are drug-like?"
"Which compounds had consistent docking?"
"What were the escalated findings?"
"Which compounds passed Lipinski?"
```

Nova will search the digest for the relevant compounds and present only those matching the criteria.

### Asking Nova to Open a Report

Each finding generates an HTML report with full MathJax equations (for math) or docking tables and oncology analysis (for chemistry). Ask Nova to open one:

```
"Open the HTML report for finding three"
"Show me the full report for the PARP1 compound"
"Open the chemistry report"
```

Nova will use the `open_webpage` or `file_explorer` tool to open the report in the browser. The reports are stored at:

```
nova_outputs/chemistry/cancer_YYYYMMDD_HHMMSS_[name].html
nova_outputs/research/research_YYYYMMDD_HHMMSS_[name].html
```

### Controlling How Many Results Are Shown

The digest tool defaults to showing 10 findings. To explicitly request more or fewer:

```
"Show me all chemistry findings, don't limit to five"
"Give me just the top three chemistry results"
"Show me all findings with no limit"
```

Nova will pass the appropriate `max_findings` parameter to the tool.

### After an Alert — Immediate Follow-Up

When the ResearchWatcher fires and Nova announces a new finding, you can immediately follow up:

```
"Tell me more about that compound"
"What does Claude think about it?"
"Open the full report"
"How does it compare to olaparib?"
"What are the Lipinski properties?"
```

The finding will already be in Nova's conversation context from the alert, so these follow-ups work without needing to re-query the journal.

### Checking Progress

To see how many cycles have run and how many survivors have been found without reading all the details:

```
"How many cycles has the researcher run?"
"How many chemistry survivors are there so far?"
"Is the researcher still running?"
"How long has the researcher been going?"
```

Nova will call the digest tool and report the headline statistics from the journal.

### Complete Voice Command Reference

| Intent | Example Phrase |
|---|---|
| Chemistry summary | "What did the chemistry researcher find?" |
| Math summary | "What did the math researcher find?" |
| Full digest | "Give me the full research digest" |
| All findings listed | "List all chemistry survivors with docking scores" |
| Specific finding | "Show me finding five in detail" |
| Target filter | "Which compounds hit PARP1?" |
| Open report | "Open the HTML report for finding three" |
| Progress check | "How many chemistry survivors are there?" |
| After alert follow-up | "Tell me more about that compound" |
| Best result | "What was the best docking score overall?" |

---

## Academic Context and Originality

### Where This Work Sits in the Literature

The Nova Hyperion Research Engine was developed independently as a personal research tool by Dr Tom Moir in 2025–2026. It is not derived from any existing codebase or academic framework, but it operates in a space that has become very active in the research community. Understanding where it sits relative to published work clarifies both what is genuinely novel about this approach and where it aligns with broader trends.

### The General Idea — AI-Driven Scientific Discovery

The concept of using AI to autonomously generate and test scientific hypotheses is not new. The field now has a substantial body of literature, and several surveys have mapped the landscape comprehensively.

A 2024 survey on LLMs in scientific discovery examined the ability of language models to propose hypotheses, demonstrating their considerable capacity for generating novel yet valid hypotheses under open-ended constraints. Frameworks such as HypER generate literature-grounded hypotheses with clear provenance, while other approaches extend hypothesis generation into the biomedical domain.

By mid-2025, the field had progressed to multimodal agentic systems that listen, see, speak, and act — orchestrating cloud software and physical laboratory hardware — charting a course from automated literature synthesis and hypothesis generation to self-driving laboratories.

Google DeepMind's AlphaEvolve agent couples Gemini large language models to an evolutionary search loop that autonomously proposes, tests, and refines hypotheses. It recently discovered a 48-multiplication algorithm for 4×4 complex-valued matrix multiplication — beating a record that had stood since 1969.

The Nova engine follows the same fundamental pattern — generate, test, escalate — but does so as a lightweight personal system running on a single workstation rather than a cloud-scale institutional deployment.

### Autonomous Drug Discovery Pipelines

The chemistry research component has many parallels in the literature, though the existing academic systems are generally more complex, require cloud infrastructure, and are not integrated with a personal AI assistant.

The Prompt-to-Pill framework, published in 2025 and based on a systematic analysis of 51 LLM-based studies from 2022–2025, integrates specialised LLM agents for molecule generation, docking, property prediction, trial construction, patient matching, and outcome forecasting through a central orchestrator. Unlike prior frameworks confined to molecule-level reasoning, it establishes a pipeline from molecular ideation to virtual trial execution.

AgentD, an LLM-powered agent framework, supports drug discovery by performing biomedical data retrieval, generating seed molecule libraries via SMILES-based generative models, predicting ADMET-related properties, and refining molecular representations. In a case study targeting BCL-2 in lymphocytic leukaemia, the agent autonomously retrieved relevant information and generated chemically diverse molecules, with drug-like candidates increasing across iterative refinement rounds.

FROGENT is an end-to-end drug design multi-agent system that achieves substantial gains in efficiency and demonstrates the strong potential of LLM-based agentic systems to autonomously orchestrate drug development pipelines, significantly reducing reliance on manual, experience-driven human intervention.

**Key differences from Nova's approach:**

| Feature | Academic systems (e.g. Prompt-to-Pill, AgentD) | Nova Hyperion |
|---|---|---|
| Infrastructure | Cloud-scale, multi-server | Single workstation, RTX 5070 Ti |
| LLM for generation | GPT-4, LLaMA (API or large GPU) | qwen3-coder:30b (local Ollama) |
| Docking | Cloud docking services or RoseTTAFold | AutoDock Vina (local binary) |
| Cost per cycle | High (API calls throughout) | Near-zero (local compute + 1 escalation) |
| Integration | Standalone pipeline | Integrated with personal AI assistant |
| Real-time alerts | Not typically implemented | TTS + email via Nova ResearchWatcher |
| Human interface | Web dashboard or CLI | Voice + web UI via Nova |

The Nova system's most distinctive characteristic is the **local-first, escalation-funnel** architecture that keeps costs near zero while the loop runs indefinitely. Academic systems typically call paid APIs at every stage; Nova calls them only for the final analysis of survivors.

### Automated Mathematical Conjecture Generation

The mathematics researcher also has clear precedents, though again with important differences.

A 2025 paper on artificial intelligence in number theory evaluated large language models on algorithmic and computational tasks in number theory. Using Qwen2.5-Math, the study achieved high accuracy on algorithmic problems and computational questions from classical number-theoretic textbooks when given appropriate prompting.

LeanConjecturer, published in 2025, addresses automatic generation of mathematical conjectures for theorem proving. It uses an iterative pipeline where LLMs generate conjectures from Mathlib files, evaluate them, and iteratively refine, allowing continuous generation of novel conjectures while maintaining mathematical validity.

The Enumerate–Conjecture–Prove (ECP) framework, inspired by mathematician George Pólya's problem-solving methodology, combines the exploratory strengths of LLMs — which enumerate candidate answers through programmatic execution and generalise patterns to form conjectures — with the rigour of formal theorem-proving methods that verify these conjectures.

The Nova math researcher takes a simpler but highly practical approach: it does not attempt formal proof in Lean or Isabelle, but instead uses numerical verification across large test ranges and then asks Claude to attempt an informal proof sketch and assess plausibility. This is closer in spirit to the experimental mathematics tradition than to the formal verification literature.

### Multi-Agent Scientific Discovery

The planner → manager → executor → supervisor architecture in Nova has parallels in the broader multi-agent AI literature:

Frameworks such as ACCELMAT for materials science use a structured, iterative loop of proposal and critique among multiple agents to progressively enhance the quality of novel material hypotheses. VIRSCI extends this by simulating scientific teams using real-world academic data, enabling agents to form collaborative research teams and generate novel ideas through inter- and intra-team discussion. AstroAgents deploys domain-specific agents to interpret mass spectrometry data and hypothesise about prebiotic chemical pathways, with more than 30% of hypotheses validated as scientifically plausible by expert reviewers.

Prominent frameworks including ResearchAgent and Agent Laboratory have made strides in automating general research workflows such as citation management, document discovery, and academic survey generation. ChatMOF is an autonomous AI system for predicting and generating metal-organic frameworks.

### What Is Genuinely Novel About This System

Given the literature above, the following aspects of the Nova Hyperion Research Engine represent contributions that are either not present in or meaningfully different from published work:

**1. Integration with a persistent personal AI assistant.** No published system integrates an autonomous research loop with a continuously running personal assistant that can be queried by voice, send email alerts, speak findings via TTS, and maintain conversational context about prior findings. The ResearchWatcher / Nova integration is unique in this respect.

**2. Local-first, near-zero-cost indefinite operation.** Published drug discovery pipelines call cloud APIs at every stage. The Nova engine runs hypothesis generation, structural validation, novelty checking, ADMET prediction, and molecular docking entirely locally, calling a paid API only for the final escalation. This allows indefinite autonomous operation at negligible cost on consumer hardware.

**3. Pose consistency quality scoring for docking.** The systematic flagging of docking results as `consistent`, `moderate`, or `unreliable` based on the spread across all 9 Vina poses and the count of physically reasonable (negative energy) poses is a practical quality control step not commonly described in published LLM-docking pipelines.

**4. Scaffold correction feedback loop.** The explicit comparison of Ollama's claimed scaffold name against RDKit's SMARTS-based classification, passed directly to Claude's analysis prompt, creates a built-in structural sanity check. This corrects Ollama's frequent misidentification of scaffold classes and ensures Claude's analysis addresses the real structure rather than the hallucinated one.

**5. Domain-agnostic journal architecture.** The uniform JSON journal schema, alert file pattern, and `nova_research_digest.py` tool registration system allow any new research domain to be added by implementing a generator, a validator, and a novelty checker — with no changes to Nova itself.

### References

The following works are directly relevant to the techniques and concepts used in this system:

**Autonomous Scientific Discovery — Surveys**

- Zhang et al. (2025). *From Automation to Autonomy: A Survey on Large Language Models in Scientific Discovery*. arXiv:2505.13259.
- Schmidgall et al. (2025). *Agentic AI for Scientific Discovery: A Survey of Progress, Challenges, and Future Directions*. arXiv:2503.08979.
- Fink et al. (2024). *AI for Scientific Discovery*. World Economic Forum Top-10-Technologies Report.

**AI Drug Discovery Pipelines**

- ChatMED (2025). *Prompt-to-Pill: Multi-Agent Drug Discovery and Clinical Simulation Pipeline*. bioRxiv:2025.08.12.
- Cao et al. (2025). *Mozi: Governed Autonomy for Drug Discovery LLM Agents*. arXiv:2603.03655.
- Anonymous (2025). *Large Language Model Agent for Modular Task Execution in Drug Discovery (AgentD)*. arXiv:2507.02925.
- Anonymous (2025). *FROGENT: An End-to-End Full-process Drug Design Multi-Agent System*. arXiv:2508.10760.
- Kim et al. (2016). *PubChem Substance and Compound Databases*. Nucleic Acids Research, 44(D1):D1202–D1213.

**Molecular Docking**

- Eberhardt et al. (2021). *AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings*. Journal of Chemical Information and Modeling, 61(8):3891–3898.
- Landrum, G. (2023). *RDKit: Open-Source Cheminformatics*. https://www.rdkit.org.

**Mathematical AI and Conjecture Generation**

- Saraeb, A. (2025). *Artificial Intelligence in Number Theory: LLMs for Algorithm Generation and Ensemble Methods for Conjecture Verification*. arXiv:2504.19451.
- Anonymous (2025). *LeanConjecturer: Automatic Generation of Mathematical Conjectures for Theorem Proving*. arXiv:2506.22005.
- Anonymous (2025). *Enumerate–Conjecture–Prove: Formally Solving Answer-Construction Problems in Math Competitions*. arXiv:2505.18492.
- Dong & Ma (2025). *Self-Play and Conjecture Generation (STP)*. arXiv:2501.xxxxx.

**Multi-Agent Research Systems**

- Kumbhar et al. (2025). *Hypothesis Generation for Materials Discovery and Design Using Goal-Driven and Constraint-Guided LLM Agents (ACCELMAT)*. arXiv:2501.13299.
- Su et al. (2024). *VIRSCI: Simulating Scientific Teams Using Real-World Academic Data*. 
- Saeedi et al. (2025). *AstroAgents: Domain-Specific Agents for Mass Spectrometry and Prebiotic Chemistry*.
- Baek et al. (2024). *ResearchAgent: Iterative Research Idea Generation Using LLMs over Scientific Literature*.

**Google DeepMind AlphaEvolve**

- Gibney, E. (2025). *DeepMind's AlphaEvolve AI Discovers New Algorithm for Matrix Multiplication*. Nature News.

---

*Nova Hyperion Research Engine — Autonomous Scientific Discovery*
*Dr Tom Moir — Birkdale, Auckland, New Zealand*
*Built with Nova, Ollama, RDKit, AutoDock Vina, and Claude*

---

## Installation and Setup

This section covers everything that must be installed and configured before the research engine will run. Follow the steps in order.

---

### 1. Python Virtual Environment

The entire project runs inside a Python virtual environment. The `.venv` folder lives inside the project directory and keeps all dependencies isolated from other Python projects on the machine.

**Create and activate:**

```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
python -m venv .venv
.venv\Scripts\activate
```

The prompt changes to `(.venv)` when the environment is active. Every `pip install` below must be run with the environment active. Every time a new terminal is opened to run Nova or the researcher, activate first.

---

### 2. Python Packages

With the virtual environment active:

```powershell
pip install rdkit
pip install httpx
pip install python-dotenv
pip install sympy
pip install mpmath
pip install pdbfixer
pip install openmm
pip install openbabel-wheel
pip install openai-whisper
pip install edge-tts
pip install pyaudio
pip install SpeechRecognition
pip install requests
pip install aiohttp
pip install cryptography
pip install pillow
```

> **openbabel-wheel** — use this, not `pip install openbabel`. The plain version requires a C++ compiler and fails on Windows. The `-wheel` variant is pre-compiled and installs cleanly.

**For CUDA acceleration (RTX 5070 Ti):**

```powershell
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install faster-whisper
```

Match `cu128` to your installed CUDA version — run `nvcc --version` to check.

---

### 3. AutoDock Vina

Vina is a standalone binary, not a Python package.

Download from: `https://github.com/ccsb-scripps/AutoDock-Vina/releases`

Download `vina_1.2.7_windows_x86_64.exe`, rename it to `vina.exe`, and place it at:

```
C:\vina\vina.exe
```

Test with:

```powershell
vina --version
```

---

### 4. Ollama

Ollama serves local LLMs for hypothesis generation. Download the Windows installer from `https://ollama.com` and run it. Ollama installs as a background service that starts automatically on login and listens on `http://localhost:11434`.

Pull the model used for hypothesis generation:

```powershell
ollama pull qwen3-coder:30b
```

This downloads approximately 20 GB. Verify the model is available:

```powershell
ollama list
```

---

### 5. The .env File

The `.env` file stores all secrets and configuration that must not be hard-coded into source files. It lives in the project root alongside `nova_assistant.py`:

```
C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1\.env
```

Create it with any text editor. The complete contents:

```env
# ── OpenRouter (Claude access) ───────────────────────────────────────────────
OPENROUTER_KEY=sk-or-v1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Brave Search (Nova web search) ──────────────────────────────────────────
BRAVE_KEY=BSAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# ── Nova alert secret (internal API authentication) ──────────────────────────
NOVA_ALERT_SECRET=nova-research-secret

# ── Email alerts ─────────────────────────────────────────────────────────────
NOTIFY_EMAIL_FROM=yourgmailaddress@gmail.com
NOTIFY_EMAIL_TO=yourgmailaddress@gmail.com
NOTIFY_EMAIL_PASS=xxxx xxxx xxxx xxxx
```

> **Vina is not in `.env`** — the docking module defaults to `C:\vina.exe`. As long as `vina.exe` lives at `C:\vina.exe`, no entry is needed. Only add `VINA_EXE=C:\path\to\vina.exe` if yours is installed elsewhere.

The file is read at startup by `python-dotenv`:

```python
from dotenv import load_dotenv
load_dotenv()
OPENROUTER_KEY = os.getenv("OPENROUTER_KEY", "")
```

**The `.env` file must never be committed to Git or shared.** Add it to `.gitignore`:

```
.env
.venv/
```

---

### 6. OpenRouter API Key (`OPENROUTER_KEY`)

OpenRouter provides access to Claude Sonnet and many other models through a single unified API endpoint. It is the only paid external service the research engine calls — and only when a compound or conjecture passes all local filters and is escalated for deep analysis.

**Getting the key:**

1. Go to `https://openrouter.ai` and create a free account
2. Navigate to **Keys** in the left sidebar
3. Click **Create Key**, give it a name (e.g. `Nova Research`)
4. Copy the key — it starts with `sk-or-v1-`
5. Paste it into `.env` as `OPENROUTER_KEY=sk-or-v1-...`

**Adding credit:**

OpenRouter uses prepaid credit. Navigate to **Credits** in the dashboard and add a small amount — $5 covers many hundreds of escalated analyses at Claude Sonnet pricing. The research engine is very conservative: it only calls Claude for compounds that pass Lipinski, PubChem novelty, and docking threshold — typically 1–3 calls per hour of running time.

**Changing the model:**

The model is set in `nova_chemistry_researcher.py`:

```python
OPENROUTER_MODEL = "anthropic/claude-sonnet-4-5"
```

Any model listed at `https://openrouter.ai/models` can be substituted. Claude Opus gives more thorough analysis; cheaper models like DeepSeek reduce cost further.

---

### 7. Brave Search API Key (`BRAVE_KEY`)

The Brave Search key gives Nova access to web search for general queries and for the GOOF button in the code execution loop. It is not used directly by the chemistry or math researchers.

**Getting the key:**

1. Go to `https://api.search.brave.com`
2. Create a free developer account
3. Navigate to **API Keys** and create a new key
4. The free tier provides 2,000 queries per month — sufficient for personal use
5. Paste into `.env` as `BRAVE_KEY=BSA...`

If this key is left blank, Nova will still function but web search queries will fail silently.

---

### 8. Gmail App Password (`NOTIFY_EMAIL_PASS`)

The research engine sends email alerts when a finding passes all filters. It uses Gmail's SMTP server with a dedicated **App Password** — not your regular Gmail password. App Passwords are required because Google blocks standard password login over SMTP when two-factor authentication is enabled.

**Step 1 — Enable 2-Step Verification** (if not already on):

1. Go to `https://myaccount.google.com/security`
2. Under **How you sign in to Google**, click **2-Step Verification**
3. Follow the setup steps

**Step 2 — Create the App Password:**

1. Go to `https://myaccount.google.com/apppasswords`
   (or from Security → 2-Step Verification → scroll to bottom → App passwords)
2. In the **App name** field type `Nova Research`
3. Click **Create**
4. Google displays a 16-character password in the format `xxxx xxxx xxxx xxxx`
5. **Copy it immediately** — Google will not show it again
6. Paste it into `.env` as `NOTIFY_EMAIL_PASS=xxxx xxxx xxxx xxxx` (keep the spaces)

**SMTP settings used by the engine:**

```python
EMAIL_HOST = "smtp.gmail.com"
EMAIL_PORT = 587          # STARTTLS
```

The `FROM` and `TO` addresses can be the same Gmail account — you email yourself. The subject line will read `[Nova Chemistry] ESCALATED: Compound name...` or `[Nova Research] VERIFIED: Conjecture...`

**If you do not want email alerts**, leave all three `NOTIFY_EMAIL_*` variables blank. The engine logs a warning but continues running without sending emails.

---

### 9. Verifying the Setup

With `.env` in place and the virtual environment active, verify all components:

**Check environment variables loaded:**

```powershell
python -c "
import os
from dotenv import load_dotenv
load_dotenv()
print('OpenRouter key:    ', 'OK' if os.getenv('OPENROUTER_KEY') else 'MISSING')
print('Brave key:         ', 'OK' if os.getenv('BRAVE_KEY') else 'MISSING')
print('Nova alert secret: ', 'OK' if os.getenv('NOVA_ALERT_SECRET') else 'MISSING')
print('Email from:        ', 'OK' if os.getenv('NOTIFY_EMAIL_FROM') else 'MISSING')
print('Email pass:        ', 'OK' if os.getenv('NOTIFY_EMAIL_PASS') else 'MISSING')
"
```

**Check RDKit:**

```powershell
python -c "from rdkit import Chem; m = Chem.MolFromSmiles('c1ccccc1'); print('RDKit OK — benzene:', m.GetNumAtoms(), 'atoms')"
```

**Check Ollama:**

```powershell
ollama list
```

**Check Vina:**

```powershell
vina --version
```

**Check OpenBabel:**

```powershell
python -c "import openbabel; print('OpenBabel OK')"
```

All should return without errors before starting the researchers.

---

### 10. Starting the System

Once all checks pass, open two terminals with the virtual environment active:

**Terminal 1 — Chemistry Researcher:**

```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_chemistry_researcher.py
```

**Terminal 2 — Nova Assistant:**

```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_assistant.py
```

The chemistry dashboard will be live at `http://localhost:8083`. Nova's web interface will be at `https://192.168.x.x:8080` (LAN IP shown at startup).oms(), 'atoms')"
```

**Check Ollama:**

```powershell
ollama list
```

**Check Vina:**

```powershell
vina --version
```

**Check OpenBabel:**

```powershell
python -c "import openbabel; print('OpenBabel OK')"
```

All should return without errors before starting the researchers.

---

### 10. Starting the System

Once all checks pass, open two terminals with the virtual environment active:

**Terminal 1 — Chemistry Researcher:**

```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_chemistry_researcher.py
```

**Terminal 2 — Nova Assistant:**

```powershell
cd C:\Users\OEM\PycharmProjects\NovaHyperionResearch_v1
.venv\Scripts\activate
python nova_assistant.py
```

The chemistry dashboard will be live at `http://localhost:8083`. Nova's web interface will be at `https://192.168.x.x:8080` (LAN IP shown at startup).