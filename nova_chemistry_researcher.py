"""
nova_chemistry_researcher.py  — Cancer Drug Discovery Edition
=============================================================
Autonomous background researcher focused on novel anticancer compounds.

Pipeline:
  Ollama          → hypothesis generation (free/local)
  RDKit           → structural validation + Lipinski + scaffold classification (free)
  PubChem API     → novelty check + IUPAC naming (free)
  ChEMBL API      → similar known anticancer compounds (free)
  RDKit ADMET     → ADMET prediction (free, replaces SwissADME)
  AutoDock Vina   → molecular docking vs validated cancer targets (free)
  Claude          → deep oncology analysis (paid, escalation only)

Dashboard  → http://localhost:8083
Alerts     → writes chemistry_alert.json (Nova ResearchWatcher picks up)

Requirements:
    pip install rdkit httpx python-dotenv
    vina.exe on PATH or VINA_EXE env variable
"""
# Note, if you are not interested in autonomous research in the background you can ignore all this
import asyncio
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Optional

import httpx

try:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, Lipinski, rdMolDescriptors, AllChem
    from rdkit.Chem.FilterCatalog import FilterCatalog, FilterCatalogParams
    RDKIT_AVAILABLE = True
except ImportError:
    RDKIT_AVAILABLE = False
    print("[WARNING] RDKit not installed — pip install rdkit")

try:
    from nova_docking import dock_molecule, TARGETS as DOCK_TARGETS
    DOCKING_AVAILABLE = True
except ImportError:
    DOCKING_AVAILABLE = False
    print("[WARNING] nova_docking not found — docking disabled")

from dotenv import load_dotenv
load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OLLAMA_BASE           = "http://localhost:11434"
OLLAMA_MODEL          = "qwen3-coder:30b" # Change this to other models if you like
OPENROUTER_KEY        = os.getenv("OPENROUTER_KEY", "")
OPENROUTER_MODEL      = "anthropic/claude-sonnet-4-5"

JOURNAL_PATH          = Path("chemistry_journal.json")
ALERT_FILE            = Path("chemistry_alert.json")
REPORTS_DIR           = Path("nova_outputs") / "chemistry"
LOG_PATH              = Path("nova_chemistry_researcher.log")
DASHBOARD_PORT        = 8083

LOOP_INTERVAL_S       = 20
PUBCHEM_DELAY_S       = 0.5
CHEMBL_SIMILARITY     = 70

DOCK_SCORE_THRESHOLD  = -5.5   # kcal/mol (calibrated for OpenBabel prep)
DOCK_EXHAUSTIVENESS   = 8

TARGET_KEYWORDS = {
    "EGFR":  ["egfr", "her2", "erbb", "tyrosine kinase", "erlotinib", "gefitinib", "lung"],
    "BCL2":  ["bcl", "apoptosis", "bh3", "venetoclax", "lymphoma", "leukaemia", "leukemia", "cll"],
    "CDK2":  ["cdk", "cyclin", "palbociclib", "ribociclib", "abemaciclib", "breast", "cell cycle"],
    "PARP1": ["parp", "brca", "dna repair", "olaparib", "niraparib", "ovarian"],
}

RESEARCH_DOMAINS = [
    "novel kinase inhibitor scaffolds targeting EGFR/HER2 overexpressed in breast and lung cancer",
    "small molecule PARP inhibitors for BRCA-mutated ovarian and breast cancer",
    "CDK4/6 inhibitor analogues for hormone receptor positive breast cancer",
    "novel HDAC inhibitor scaffolds for haematological malignancies",
    "PD-L1 small molecule inhibitors to block immune checkpoint in solid tumours",
    "BCL-2/BCL-XL inhibitors for apoptosis resistance in lymphoma and CLL",
    "novel proteasome inhibitor scaffolds for multiple myeloma",
    "VEGFR inhibitors targeting tumour angiogenesis in colorectal cancer",
    "IDH1/IDH2 mutant inhibitors for acute myeloid leukaemia",
    "novel aurora kinase inhibitors for mitotic regulation in solid tumours",
    "mTOR pathway inhibitors for renal cell carcinoma and breast cancer",
    "novel RAS/RAF pathway inhibitors for KRAS-mutant pancreatic cancer",
]

LIPINSKI_MW_MAX   = 500
LIPINSKI_LOGP_MAX = 5
LIPINSKI_HBD_MAX  = 5
LIPINSKI_HBA_MAX  = 10

# Scaffold SMARTS — order matters (most specific first)
SCAFFOLD_PATTERNS = {
    "Quinazoline":   "c1nc2ccccc2nc1",
    "Triazine":      "c1ncncn1",
    "Quinolone":     "O=c1cccc2ccccc12",
    "Hydantoin":     "[#7]1C(=O)[#7]CC1=O",
    "Pyrazolone":    "[#7]1[#7]C(=O)CC1",
    "Indole":        "c1ccc2[nH]ccc2c1",
    "Benzimidazole": "c1ccc2[nH]cnc2c1",
    "Purine":        "c1ncnc2[nH]cnc12",
    "Pyrimidine":    "c1ccnc(n1)",
    "Piperazine":    "C1CNCCN1",
    "Piperidine":    "C1CCNCC1",
    "Indazole":      "c1ccc2[nH]ncc2c1",
    "Oxazole":       "c1cnco1",
    "Thiazole":      "c1cncs1",
    "Triazole":      "c1cn[nH]n1",
    "Imidazole":     "c1cn[nH]c1",
}
# ---------------------------------------------------------------------------
# Status dict
# ---------------------------------------------------------------------------

STATUS = {
    "state":        "Starting up...",
    "phase":        "idle",
    "domain":       "",
    "hypothesis":   "",
    "smiles":       "",
    "target":       "",
    "cancer_type":  "",
    "cycle_count":  0,
    "found_count":  0,
    "started":      datetime.now().isoformat(),
    "last_cycle":   "",
    "next_cycle":   "",
    "log_tail":     [],
    "rdkit":        RDKIT_AVAILABLE,
    "docking":      DOCKING_AVAILABLE,
    "dock_scores":  {},
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
log = logging.getLogger("NovaCancerResearcher")

# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

class ChemJournal:
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

    def recent_survivors(self, n: int = 6) -> list:
        all_e = self._load()
        survivors = [e for e in all_e if e.get("status") in ("novel", "escalated", "promising")]
        return survivors[-n:]

# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

async def ollama_generate(prompt: str, system: str = "", timeout: int = 400) -> str:
    payload = {
        "model":   OLLAMA_MODEL,
        "prompt":  prompt,
        "system":  system,
        "stream":  False,
        "options": {"temperature": 0.8, "num_predict": 1024},
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r   = await client.post(f"{OLLAMA_BASE}/api/generate", json=payload)
            r.raise_for_status()
            raw = r.json().get("response", "").strip()
            # Strip qwen3 thinking blocks
            raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
            return raw
    except Exception as e:
        log.warning(f"Ollama generate failed: {e}")
        return ""

# ---------------------------------------------------------------------------
# Claude
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
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers, json=payload,
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"Claude generate failed: {e}")
        return "[Claude analysis failed]"

# ---------------------------------------------------------------------------
# PubChem
# ---------------------------------------------------------------------------

async def pubchem_check(smiles: str, name: str) -> dict:
    result = {"found": False, "cid": None}
    if not smiles:
        return result
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/cids/JSON",
                params={"smiles": smiles}
            )
            if r.status_code == 200:
                data      = r.json()
                cids      = data.get("IdentifierList", {}).get("CID", [])
                real_cids = [c for c in cids if c > 0]
                if real_cids:
                    result["found"] = True
                    result["cid"]   = real_cids[0]
                    log.info(f"PubChem match — CID: {real_cids[0]}")
            elif r.status_code == 404:
                log.info("Not in PubChem — novel structure")
        await asyncio.sleep(PUBCHEM_DELAY_S)
    except Exception as e:
        log.warning(f"PubChem check failed: {e}")
    return result


async def get_iupac_name(smiles: str) -> str:
    """Query PubChem for IUPAC name of a structure."""
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(
                "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/smiles/property/IUPACName/JSON",
                params={"smiles": smiles}
            )
            if r.status_code == 200:
                props = r.json().get("PropertyTable", {}).get("Properties", [])
                if props:
                    return props[0].get("IUPACName", "")
    except Exception as e:
        log.warning(f"IUPAC name lookup failed: {e}")
    return ""


async def rename_compound(hypothesis: dict, smiles: str) -> str:
    """
    Get a proper name for the actual SMILES structure.
    Tries PubChem first, falls back to Ollama, validates result.
    Returns new name or empty string if no reliable name found.
    """
    iupac = await get_iupac_name(smiles)

    if not iupac:
        raw = await ollama_generate(
            f"Given this SMILES: {smiles}\n"
            f"Provide only the IUPAC name. No explanation, no markdown, just the name.",
            system="You are a cheminformatics expert. Output only the IUPAC chemical name, nothing else."
        )
        iupac = raw.strip().split("\n")[0] if raw.strip() else ""

    # Reject hallucinated recursive names
    if iupac and (len(iupac) > 300 or iupac.count("(4-(4-") > 3 or iupac.count("-(4-") > 8):
        log.warning("IUPAC name looks hallucinated — discarding")
        return ""

    return iupac

# ---------------------------------------------------------------------------
# ChEMBL
# ---------------------------------------------------------------------------

async def chembl_similarity_search(smiles: str) -> dict:
    result = {"similar_compounds": [], "known_anticancer": [], "max_similarity": 0}
    if not smiles:
        return result
    try:
        url = f"https://www.ebi.ac.uk/chembl/api/data/similarity/{smiles}/{CHEMBL_SIMILARITY}.json"
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return result
            data      = r.json()
            molecules = data.get("molecules", [])
            for mol in molecules[:10]:
                chembl_id  = mol.get("molecule_chembl_id", "")
                similarity = mol.get("similarity", 0)
                pref_name  = mol.get("pref_name", "") or ""
                max_phase  = mol.get("max_phase", 0) or 0
                result["similar_compounds"].append({
                    "chembl_id":  chembl_id,
                    "name":       pref_name,
                    "similarity": similarity,
                    "max_phase":  max_phase,
                })
                if float(similarity) > result["max_similarity"]:
                    result["max_similarity"] = float(similarity)
        await asyncio.sleep(0.5)
        if result["similar_compounds"]:
            top_id  = result["similar_compounds"][0]["chembl_id"]
            act_url = (
                f"https://www.ebi.ac.uk/chembl/api/data/activity.json"
                f"?molecule_chembl_id={top_id}&limit=5"
            )
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(act_url)
                if r.status_code == 200:
                    for act in r.json().get("activities", []):
                        tname    = act.get("target_pref_name", "")
                        std_type = act.get("standard_type", "")
                        std_val  = act.get("standard_value", "")
                        std_unit = act.get("standard_units", "")
                        if tname and std_type:
                            result["known_anticancer"].append(
                                f"{tname}: {std_type}={std_val} {std_unit}"
                            )
    except Exception as e:
        log.warning(f"ChEMBL search failed: {e}")
    return result

# ---------------------------------------------------------------------------
# RDKit ADMET
# ---------------------------------------------------------------------------

async def swissadme_predict(smiles: str) -> dict:
    """RDKit-based ADMET estimates."""
    result = {
        "gi_absorption":    "Unknown",
        "bbb_permeant":     "Unknown",
        "pgp_substrate":    "Unknown",
        "cyp_inhibitor":    "Unknown",
        "lipophilicity":    "Unknown",
        "water_solubility": "Unknown",
        "druglikeness":     "Unknown",
        "raw":              {},
    }
    if not RDKIT_AVAILABLE or not smiles:
        return result
    try:
        mol = Chem.MolFromSmiles(smiles)
        if not mol:
            return result
        mw   = Descriptors.MolWt(mol)
        logp = Descriptors.MolLogP(mol)
        tpsa = Descriptors.TPSA(mol)
        hbd  = Lipinski.NumHDonors(mol)
        hba  = Lipinski.NumHAcceptors(mol)
        rb   = rdMolDescriptors.CalcNumRotatableBonds(mol)
        arom = rdMolDescriptors.CalcNumAromaticRings(mol)

        gi  = "High" if tpsa <= 140 and rb <= 10 else "Low"
        bbb = "Yes"  if (tpsa < 90 and mw < 450 and logp > 0 and hbd <= 3) else "No"
        sol = ("High" if logp < 1 else "Good" if logp < 3 else "Moderate" if logp < 5 else "Poor")
        cyp = "Risk" if (arom >= 3 and logp > 3) else "Low risk"

        lip_ok   = (mw <= 500 and logp <= 5 and hbd <= 5 and hba <= 10)
        veber_ok = (tpsa <= 140 and rb <= 10)
        dl = ("Drug-like" if (lip_ok and veber_ok)
              else "Borderline" if lip_ok else "Non drug-like")

        result.update({
            "gi_absorption":    gi,
            "bbb_permeant":     bbb,
            "water_solubility": sol,
            "lipophilicity":    f"LogP={logp:.2f}",
            "cyp_inhibitor":    cyp,
            "druglikeness":     dl,
            "raw": {
                "mw": mw, "logp": logp, "tpsa": tpsa,
                "hbd": hbd, "hba": hba, "rotatable": rb,
                "aromatic_rings": arom,
            },
        })
    except Exception as e:
        log.warning(f"RDKit ADMET failed: {e}")
    return result

# ---------------------------------------------------------------------------
# RDKit verification + scaffold classification
# ---------------------------------------------------------------------------

def classify_scaffold(mol) -> str:
    try:
        for name, smarts in SCAFFOLD_PATTERNS.items():
            q = Chem.MolFromSmarts(smarts)
            if q and mol.HasSubstructMatch(q):
                return name
    except Exception:
        pass
    return "Unknown"


def verify_molecule(smiles: str) -> dict:
    result = {
        "valid": False, "mw": None, "logp": None,
        "hbd": None, "hba": None, "rotatable": None,
        "tpsa": None, "lipinski_ok": False,
        "violations": [], "alerts": [],
        "scaffold_class": "Unknown",
    }
    if not RDKIT_AVAILABLE or not smiles:
        result["valid"] = True
        return result
    try:
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            result["violations"].append("Invalid SMILES")
            return result

        result["valid"]     = True
        result["mw"]        = round(Descriptors.MolWt(mol), 2)
        result["logp"]      = round(Descriptors.MolLogP(mol), 2)
        result["hbd"]       = Lipinski.NumHDonors(mol)
        result["hba"]       = Lipinski.NumHAcceptors(mol)
        result["rotatable"] = rdMolDescriptors.CalcNumRotatableBonds(mol)
        result["tpsa"]      = round(Descriptors.TPSA(mol), 2)

        violations = []
        if result["mw"]   > LIPINSKI_MW_MAX:   violations.append(f"MW={result['mw']} > {LIPINSKI_MW_MAX}")
        if result["logp"] > LIPINSKI_LOGP_MAX:  violations.append(f"LogP={result['logp']} > {LIPINSKI_LOGP_MAX}")
        if result["hbd"]  > LIPINSKI_HBD_MAX:   violations.append(f"HBD={result['hbd']} > {LIPINSKI_HBD_MAX}")
        if result["hba"]  > LIPINSKI_HBA_MAX:   violations.append(f"HBA={result['hba']} > {LIPINSKI_HBA_MAX}")
        result["violations"]  = violations
        result["lipinski_ok"] = len(violations) <= 1

        try:
            params  = FilterCatalogParams()
            params.AddCatalog(FilterCatalogParams.FilterCatalogs.PAINS)
            catalog = FilterCatalog(params)
            matches = catalog.GetMatches(mol)
            result["alerts"] = [m.GetDescription() for m in matches]
        except Exception:
            pass

        result["scaffold_class"] = classify_scaffold(mol)

    except Exception as e:
        result["violations"].append(f"RDKit error: {e}")
    return result

# ---------------------------------------------------------------------------
# Docking helpers
# ---------------------------------------------------------------------------

def pick_dock_targets(target_text: str, cancer_text: str) -> list:
    combined = (target_text + " " + cancer_text).lower()
    scores   = {}
    for dock_target, keywords in TARGET_KEYWORDS.items():
        hit = sum(1 for kw in keywords if kw in combined)
        if hit:
            scores[dock_target] = hit
    ordered = sorted(scores, key=lambda t: scores[t], reverse=True)
    if not ordered:
        ordered = ["EGFR"]
    return ordered[:2]


async def run_docking(smiles: str, compound_name: str, target_text: str, cancer_text: str) -> dict:
    if not DOCKING_AVAILABLE:
        return {"available": False, "passes_filter": True}

    targets = pick_dock_targets(target_text, cancer_text)
    results = {}

    for t in targets:
        update_status(
            phase="docking",
            state=f"Docking vs {t} ({targets.index(t)+1}/{len(targets)})..."
        )
        log.info(f"Docking {compound_name} vs {t}...")
        r = await dock_molecule(
            smiles,
            target_name=t,
            compound_name=re.sub(r'[^\w]', '_', compound_name[:25]),
            exhaustiveness=DOCK_EXHAUSTIVENESS,
        )
        results[t] = r
        if r.get("success"):
            log.info(f"  {t}: {r['score']:.2f} kcal/mol [{r.get('grade','')}]")
        else:
            log.warning(f"  {t}: failed — {r.get('error','')}")

    scored = {
        t: r["score"]
        for t, r in results.items()
        if r.get("success") and r.get("score") is not None
    }

    if not scored:
        log.warning("All docking attempts failed — passing through")
        return {
            "available": True, "results": results,
            "passes_filter": True, "best_score": None,
            "best_target": None, "pose_warnings": {},
        }

    best_target = min(scored, key=scored.get)
    best_score  = scored[best_target]
    passes      = best_score <= DOCK_SCORE_THRESHOLD

    # Pose consistency check
    pose_warnings = {}
    for t, r in results.items():
        if r.get("success") and r.get("all_scores"):
            all_s  = r["all_scores"]
            valid  = [s for s in all_s if s < 0]
            spread = max(all_s) - min(all_s) if all_s else 0
            consistency = (
                "consistent"  if spread < 5  and len(valid) >= 5 else
                "moderate"    if spread < 15 and len(valid) >= 3 else
                "unreliable"
            )
            r["pose_spread"]  = round(spread, 2)
            r["pose_valid"]   = len(valid)
            r["pose_quality"] = consistency
            if consistency == "unreliable":
                pose_warnings[t] = f"spread={spread:.0f}, only {len(valid)}/9 negative poses"
                log.warning(f"  {t}: unreliable docking — {pose_warnings[t]}")

    STATUS["dock_scores"] = {t: f"{s:.2f}" for t, s in scored.items()}
    log.info(f"Docking summary: best={best_score:.2f} vs {best_target} | passes={passes}")

    return {
        "available":     True,
        "results":       results,
        "best_score":    best_score,
        "best_target":   best_target,
        "passes_filter": passes,
        "scored":        scored,
        "pose_warnings": pose_warnings,
    }

# ---------------------------------------------------------------------------
# Hypothesis generation
# ---------------------------------------------------------------------------

HYPOTHESIS_SYSTEM = """\
You are an expert medicinal chemist specialising in oncology drug discovery.
Generate one novel small molecule hypothesis for cancer treatment.

Rules:
1. Propose a specific compound targeting a validated cancer drug target
2. Provide a valid SMILES string — keep it simple, max 40 heavy atoms
3. Avoid stereocenters (@) and complex fused ring systems — these cause SMILES errors
4. Use well-known scaffolds (quinazoline, pyrimidine, indole, piperazine) with novel substituents
5. The novelty should come from substituent combinations, NOT from exotic ring systems
6. Specify the cancer type and mechanism clearly
7. Keep molecular weight strictly under 480 Da and LogP under 4.5 — leave margin for Lipinski

Respond ONLY with valid JSON (no markdown, no preamble):
{
  "name": "Compound name",
  "smiles": "Valid SMILES string",
  "hypothesis": "What this compound does and why it might work",
  "target": "Specific protein/pathway target (e.g. EGFR kinase, BCL-2)",
  "cancer_type": "Specific cancer type(s) this targets",
  "mechanism": "Mechanism of action (inhibitor/activator/degrader etc)",
  "domain": "Research domain",
  "rationale": "Why this scaffold was chosen based on known SAR",
  "novelty_claim": "How this differs from approved drugs in this class"
}"""


async def generate_hypothesis(domain: str) -> Optional[dict]:
    prompt = f"Generate a novel anticancer compound hypothesis for: {domain}"
    raw    = await ollama_generate(prompt, system=HYPOTHESIS_SYSTEM)
    if not raw:
        log.warning("Empty response from Ollama")
        return None
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        log.warning("No JSON in hypothesis output")
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        try:
            fixed = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r'\\\\', match.group())
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            log.warning(f"JSON parse error: {e}")
            return None


async def repair_smiles(smiles: str, compound_name: str) -> Optional[str]:
    """Ask Ollama to fix a broken SMILES string — one retry only."""
    prompt = (
        f"The following SMILES string for '{compound_name}' is chemically invalid:\n"
        f"{smiles}\n\n"
        f"Return ONLY a corrected valid SMILES string. "
        f"No explanation, no markdown, no extra text."
    )
    raw   = await ollama_generate(
        prompt,
        system="You are a cheminformatics expert. Output only a valid SMILES string."
    )
    fixed = raw.strip().split()[0] if raw.strip() else ""
    mol   = Chem.MolFromSmiles(fixed) if RDKIT_AVAILABLE and fixed else None
    if mol is not None:
        log.info(f"SMILES repaired: {fixed}")
        return fixed
    return None

# ---------------------------------------------------------------------------
# Claude oncology analysis
# ---------------------------------------------------------------------------

ONCOLOGY_SYSTEM = """\
You are an expert oncologist and medicinal chemist reviewing a novel drug hypothesis.
Provide a comprehensive analysis covering:

1. THERAPEUTIC POTENTIAL
2. MECHANISM OF ACTION
3. STRUCTURAL ANALYSIS — use the RDKit scaffold class to resolve any name/structure mismatch
4. DOCKING RESULTS — interpret AutoDock Vina scores; note any pose quality warnings
5. ADMET ASSESSMENT
6. DEVELOPMENT PATHWAY
7. VERDICT — Is this worth pursuing? Confidence level (Low/Medium/High)

Be critical, scientifically rigorous, and clinically relevant.
Focus analysis on the real scaffold (from RDKit), not the claimed one."""


async def oncology_analysis(
    hypothesis: dict,
    verification: dict,
    pubchem: dict,
    chembl: dict,
    admet: dict,
    docking: dict,
) -> str:
    smiles = hypothesis.get("smiles", "")

    mol_props = ""
    if verification.get("valid") and verification.get("mw"):
        mol_props = (
            f"MW={verification['mw']}, LogP={verification['logp']}, "
            f"HBD={verification['hbd']}, HBA={verification['hba']}, "
            f"TPSA={verification['tpsa']}, "
            f"Lipinski: {'PASS' if verification['lipinski_ok'] else 'FAIL'}"
        )
        if verification.get("violations"):
            mol_props += f", Violations: {', '.join(verification['violations'])}"
        if verification.get("alerts"):
            mol_props += f", PAINS: {', '.join(verification['alerts'][:2])}"
        if verification.get("scaffold_class"):
            mol_props += f", Scaffold (RDKit): {verification['scaffold_class']}"

    chembl_info = "No similar compounds found in ChEMBL"
    if chembl.get("similar_compounds"):
        top = chembl["similar_compounds"][:3]
        chembl_info = "Top similar: " + ", ".join(
            f"{c['name'] or c['chembl_id']} ({c['similarity']}% similar, Phase {c['max_phase']})"
            for c in top
        )
        if chembl.get("known_anticancer"):
            chembl_info += f"\nKnown activities: {'; '.join(chembl['known_anticancer'][:3])}"

    admet_info = (
        f"GI absorption: {admet['gi_absorption']}, "
        f"BBB: {admet['bbb_permeant']}, "
        f"Solubility: {admet['water_solubility']}, "
        f"CYP risk: {admet['cyp_inhibitor']}, "
        f"Druglikeness: {admet['druglikeness']}"
    )

    docking_info = "Docking not performed"
    if docking.get("available") and docking.get("results"):
        lines = []
        for t, r in docking["results"].items():
            if r.get("success") and r.get("score") is not None:
                target_note  = ""
                if DOCKING_AVAILABLE and t in DOCK_TARGETS:
                    target_note = f" ({DOCK_TARGETS[t].get('note', '')})"
                quality      = r.get("pose_quality", "")
                quality_note = f" ⚠️ {quality}" if quality in ("moderate", "unreliable") else ""
                lines.append(
                    f"  {t}{target_note}: {r['score']:.2f} kcal/mol "
                    f"[{r.get('grade', '')}]{quality_note} — {r.get('cancer', '')}"
                )
            else:
                lines.append(f"  {t}: failed")
        if docking.get("best_score") is not None:
            lines.append(
                f"Best: {docking['best_score']:.2f} kcal/mol vs {docking['best_target']}"
            )
        if docking.get("pose_warnings"):
            for t, w in docking["pose_warnings"].items():
                lines.append(f"  ⚠️ {t} pose warning: {w}")
        docking_info = "\n".join(lines)

    ollama_name = hypothesis.get("ollama_name", "")
    name_note   = (
        f" (originally labelled: {ollama_name})"
        if ollama_name and ollama_name != hypothesis.get("name") else ""
    )

    prompt = (
        f"Compound: {hypothesis.get('name', '')}{name_note}\n"
        f"SMILES: {smiles or 'Not provided'}\n"
        f"Actual scaffold (RDKit): {verification.get('scaffold_class', 'Unknown')}\n"
        f"Target: {hypothesis.get('target', '')}\n"
        f"Cancer type: {hypothesis.get('cancer_type', '')}\n"
        f"Mechanism: {hypothesis.get('mechanism', '')}\n"
        f"Hypothesis: {hypothesis.get('hypothesis', '')}\n"
        f"Rationale: {hypothesis.get('rationale', '')}\n"
        f"Novelty claim: {hypothesis.get('novelty_claim', '')}\n\n"
        f"Molecular properties: {mol_props or 'Not computed'}\n"
        f"PubChem: {'Already exists (CID: ' + str(pubchem.get('cid')) + ')' if pubchem.get('found') else 'Not found in PubChem — novel'}\n"
        f"ChEMBL similarity: {chembl_info}\n"
        f"ADMET prediction: {admet_info}\n\n"
        f"AutoDock Vina docking (OpenBabel prep, threshold {DOCK_SCORE_THRESHOLD} kcal/mol):\n"
        f"{docking_info}\n\n"
        "Provide comprehensive oncology analysis. The RDKit scaffold above is computed "
        "directly from the SMILES — use it to resolve any name/structure discrepancy."
    )
    return await claude_generate(prompt, system=ONCOLOGY_SYSTEM)

# ---------------------------------------------------------------------------
# HTML Report
# ---------------------------------------------------------------------------

def save_report_as_html(finding: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    h           = finding.get("hypothesis", {})
    status      = finding.get("status", "novel").upper()
    name        = h.get("name", "Unknown")
    smiles      = h.get("smiles", "")
    target      = h.get("target", "")
    cancer      = h.get("cancer_type", "")
    mechanism   = h.get("mechanism", "")
    scaffold    = finding.get("verification", {}).get("scaffold_class", "")
    ollama_name = h.get("ollama_name", "")
    analysis    = finding.get("analysis", "") or ""
    timestamp   = finding.get("timestamp", datetime.now().isoformat())[:16]
    v           = finding.get("verification", {})
    chembl      = finding.get("chembl", {})
    admet       = finding.get("admet", {})
    docking     = finding.get("docking", {})

    colour = {"NOVEL": "#00ff88", "ESCALATED": "#9999ff", "PROMISING": "#ff9900"}.get(status, "#00ff88")

    def md_to_html(text):
        text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', text)
        text = re.sub(r'^### (.*?)$', r'<h3>\1</h3>', text, flags=re.MULTILINE)
        text = re.sub(r'^## (.*?)$',  r'<h2>\1</h2>',  text, flags=re.MULTILINE)
        text = text.replace('\n\n', '</p><p style="margin-bottom:1em">').replace('\n', '<br>')
        return text

    # Molecular properties
    mol_props_html = ""
    if v.get("mw"):
        scaffold_stat = (
            f'<div class="stat"><span class="stat-label">Scaffold</span>'
            f'<span class="stat-value" style="color:#66ccff;font-size:0.9em">{scaffold}</span></div>'
            if scaffold and scaffold != "Unknown" else ""
        )
        mol_props_html = f"""
        <div class="section">
            <div class="section-title">Molecular Properties</div>
            <div class="stats">
                <div class="stat"><span class="stat-label">MW</span><span class="stat-value">{v['mw']}</span></div>
                <div class="stat"><span class="stat-label">LogP</span><span class="stat-value">{v['logp']}</span></div>
                <div class="stat"><span class="stat-label">HBD</span><span class="stat-value">{v['hbd']}</span></div>
                <div class="stat"><span class="stat-label">HBA</span><span class="stat-value">{v['hba']}</span></div>
                <div class="stat"><span class="stat-label">TPSA</span><span class="stat-value">{v['tpsa']}</span></div>
                <div class="stat"><span class="stat-label">Lipinski</span>
                    <span class="stat-value" style="color:{'#00ff88' if v.get('lipinski_ok') else '#ff6666'}">
                        {'PASS' if v.get('lipinski_ok') else 'FAIL'}
                    </span>
                </div>
                {scaffold_stat}
            </div>
            {'<p style="color:#ff6666;margin-top:8px;font-size:0.85em">Violations: ' + ', '.join(v['violations']) + '</p>' if v.get('violations') else ''}
            {'<p style="color:#ff9900;margin-top:4px;font-size:0.85em">PAINS alerts: ' + ', '.join(v["alerts"][:2]) + '</p>' if v.get('alerts') else ''}
        </div>"""

    # ADMET
    admet_html = ""
    if admet.get("gi_absorption") != "Unknown":
        admet_html = f"""
        <div class="section">
            <div class="section-title">ADMET Predictions</div>
            <div class="stats">
                <div class="stat"><span class="stat-label">GI Absorption</span><span class="stat-value" style="font-size:0.9em">{admet.get('gi_absorption','?')}</span></div>
                <div class="stat"><span class="stat-label">BBB Permeant</span><span class="stat-value" style="font-size:0.9em">{admet.get('bbb_permeant','?')}</span></div>
                <div class="stat"><span class="stat-label">Solubility</span><span class="stat-value" style="font-size:0.9em">{admet.get('water_solubility','?')}</span></div>
                <div class="stat"><span class="stat-label">CYP Risk</span><span class="stat-value" style="font-size:0.9em">{admet.get('cyp_inhibitor','?')}</span></div>
                <div class="stat"><span class="stat-label">Drug-like</span><span class="stat-value" style="font-size:0.9em">{admet.get('druglikeness','?')}</span></div>
            </div>
        </div>"""

    # ChEMBL
    chembl_html = ""
    if chembl.get("similar_compounds"):
        rows = ""
        for c in chembl["similar_compounds"][:5]:
            rows += (
                f"<tr><td>{c.get('name') or c['chembl_id']}</td>"
                f"<td>{c['similarity']}%</td>"
                f"<td>Phase {c['max_phase']}</td></tr>"
            )
        chembl_html = f"""
        <div class="section">
            <div class="section-title">Similar Known Compounds (ChEMBL)</div>
            <table style="width:100%;border-collapse:collapse;font-size:0.85em">
                <tr style="color:#9999ff">
                    <th style="text-align:left;padding:4px">Compound</th>
                    <th style="text-align:left;padding:4px">Similarity</th>
                    <th style="text-align:left;padding:4px">Clinical Phase</th>
                </tr>
                {rows}
            </table>
        </div>"""

    # Docking
    docking_html = ""
    if docking.get("available") and docking.get("results"):
        rows = ""
        for t, r in docking["results"].items():
            if r.get("success") and r.get("score") is not None:
                score     = r["score"]
                grade     = r.get("grade", "")
                is_best   = (t == docking.get("best_target"))
                score_col = "#00ff88" if score <= -7.0 else ("#ffcc00" if score <= -5.5 else "#ff9900")
                bold      = "font-weight:bold;" if is_best else ""
                pocket    = DOCK_TARGETS.get(t, {}).get("note", "") if DOCKING_AVAILABLE else ""
                row_style = 'style="background:#0a1a0a"' if is_best else ''
                star      = "★" if is_best else ""
                quality   = r.get("pose_quality", "")
                q_badge   = (
                    f' <span style="color:#ff9900;font-size:0.75em">⚠️ {quality}</span>'
                    if quality in ("moderate", "unreliable") else ""
                )
                rows += (
                    f"<tr {row_style}>"
                    f"<td style='{bold}color:#fff'>{t} {star}{q_badge}</td>"
                    f"<td style='{bold}color:{score_col}'>{score:.2f} kcal/mol</td>"
                    f"<td style='color:#88aaff;font-size:0.85em'>{grade}</td>"
                    f"<td style='color:#446;font-size:0.8em'>{pocket}</td>"
                    f"</tr>"
                )
            else:
                rows += (
                    f"<tr><td style='color:#446'>{t}</td>"
                    f"<td colspan='3' style='color:#333'>failed</td></tr>"
                )

        best_score  = docking.get("best_score")
        best_target = docking.get("best_target", "")
        passes      = docking.get("passes_filter", False)
        summary_col = "#00ff88" if passes else "#ff6666"
        summary = (
            f"Best: <strong style='color:{summary_col}'>{best_score:.2f} kcal/mol</strong> "
            f"vs {best_target} — "
            f"<span style='color:{summary_col}'>{'PASSES' if passes else 'FAILS'} "
            f"threshold ({DOCK_SCORE_THRESHOLD} kcal/mol)</span>"
        ) if best_score is not None else "All docking attempts failed"

        docking_html = f"""
        <div class="section">
            <div class="section-title">AutoDock Vina Binding Scores</div>
            <table style="width:100%;border-collapse:collapse;font-size:0.88em;margin-bottom:10px">
                <tr style="color:#9999ff">
                    <th style="text-align:left;padding:5px">Target</th>
                    <th style="text-align:left;padding:5px">Affinity</th>
                    <th style="text-align:left;padding:5px">Grade</th>
                    <th style="text-align:left;padding:5px">Pocket</th>
                </tr>
                {rows}
            </table>
            <p style="font-size:0.85em;margin-top:6px">{summary}</p>
            <p style="color:#335;font-size:0.75em;margin-top:4px">
                Scores calibrated for OpenBabel receptor preparation.
                Threshold: ≤{DOCK_SCORE_THRESHOLD} kcal/mol.
            </p>
        </div>"""

    # Analysis
    analysis_html = ""
    if analysis:
        analysis_html = f"""
        <div class="section">
            <div class="section-title">Nova Oncology Analysis</div>
            <div class="analysis-content">
                <p style="margin-bottom:1em">{md_to_html(analysis)}</p>
            </div>
        </div>"""

    # Ollama label note
    ollama_note = ""
    if ollama_name and ollama_name != name:
        ollama_note = f'<p style="color:#446;font-size:0.8em;margin-top:4px">Originally labelled: {ollama_name}</p>'

    scaffold_badge = (
        f'<span class="scaffold-badge">🔬 {scaffold}</span>'
        if scaffold and scaffold != "Unknown" else ""
    )
    scaffold_line = (
        f'<div class="mechanism-info" style="color:#aaaaff">Scaffold (RDKit): {scaffold}</div>'
        if scaffold and scaffold != "Unknown" else ""
    )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Nova Cancer Research — {name}</title>
<style>
* {{ box-sizing:border-box; margin:0; padding:0; }}
body {{ background:#04080F; color:#D0E8FF; font-family:'Segoe UI',Georgia,serif; max-width:960px; margin:0 auto; padding:40px 20px; line-height:1.8; }}
.header {{ border-bottom:2px solid #00ff88; padding-bottom:12px; margin-bottom:8px; }}
.header-title {{ color:#00ff88; font-size:1.3em; letter-spacing:3px; text-transform:uppercase; }}
.meta {{ color:#446; font-size:0.8em; margin-bottom:24px; margin-top:4px; }}
.badge {{ display:inline-block; padding:3px 16px; border-radius:4px; font-size:0.8em; font-weight:bold; letter-spacing:3px; border:1px solid {colour}; color:{colour}; background:#0a0a1a; margin-bottom:20px; }}
.cancer-badge {{ display:inline-block; padding:3px 12px; border-radius:4px; font-size:0.75em; background:#1a0505; border:1px solid #ff4444; color:#ff8888; margin-left:8px; }}
.scaffold-badge {{ display:inline-block; padding:3px 12px; border-radius:4px; font-size:0.75em; background:#0a0a2a; border:1px solid #6666ff; color:#aaaaff; margin-left:8px; }}
.section {{ background:#0a0f1a; border:1px solid #223; border-radius:8px; padding:20px 24px; margin-bottom:18px; }}
.section-title {{ color:#00cc66; font-size:0.75em; letter-spacing:3px; text-transform:uppercase; margin-bottom:12px; border-bottom:1px solid #223; padding-bottom:6px; }}
.compound-name {{ font-size:1.4em; color:#fff; margin-bottom:6px; }}
.target-info {{ color:#9999ff; font-size:0.95em; margin-bottom:4px; }}
.mechanism-info {{ color:#66ccff; font-size:0.9em; }}
.smiles {{ font-family:'Courier New',monospace; font-size:0.8em; color:#66ff88; background:#050f05; padding:8px 12px; border-radius:4px; word-break:break-all; margin-top:8px; }}
.hypothesis-text {{ font-size:1em; line-height:1.9; color:#eee; border-left:3px solid #00ff88; padding-left:16px; margin-top:8px; }}
.stats {{ display:flex; gap:24px; flex-wrap:wrap; }}
.stat {{ display:flex; flex-direction:column; }}
.stat-label {{ color:#446; font-size:0.72em; letter-spacing:1px; text-transform:uppercase; }}
.stat-value {{ color:{colour}; font-weight:bold; font-size:1.05em; }}
.analysis-content {{ color:#ccc; line-height:1.9; font-size:0.95em; }}
.analysis-content strong {{ color:#fff; }}
.analysis-content h2 {{ color:#00cc66; margin:16px 0 8px; font-size:1em; }}
.analysis-content h3 {{ color:#66ccff; margin:12px 0 6px; font-size:0.9em; }}
table td {{ padding:6px 8px; border-bottom:1px solid #223; color:#ccc; }}
.footer {{ text-align:center; margin-top:36px; color:#334; font-size:0.75em; border-top:1px solid #223; padding-top:14px; }}
</style>
</head>
<body>
<div class="header">
    <div class="header-title">🧬 Nova Cancer Drug Discovery</div>
</div>
<div class="meta">Generated: {timestamp} &nbsp;|&nbsp; Nova Autonomous Cancer Researcher</div>

<span class="badge">{status}</span>
<span class="cancer-badge">🎯 {cancer or 'Cancer'}</span>
{scaffold_badge}

<div class="section">
    <div class="compound-name">{name}</div>
    {ollama_note}
    <div class="target-info">Target: {target}</div>
    <div class="mechanism-info">Mechanism: {mechanism}</div>
    {scaffold_line}
    <div class="smiles">{smiles or 'SMILES not provided'}</div>
    <div class="section-title" style="margin-top:16px">Hypothesis</div>
    <div class="hypothesis-text">{h.get('hypothesis','')}</div>
</div>

{mol_props_html}
{admet_html}
{chembl_html}
{docking_html}
{analysis_html}

<div class="footer">
    Nova Autonomous Cancer Research System &nbsp;|&nbsp; {timestamp}
</div>
</body>
</html>"""

    ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r'[^\w]', '_', name[:40])
    filename  = f"cancer_{ts}_{safe_name}.html"
    path      = REPORTS_DIR / filename
    path.write_text(html, encoding="utf-8")
    log.info(f"Report saved → {path}")
    return path

# ---------------------------------------------------------------------------
# Nova alert
# ---------------------------------------------------------------------------

def notify_nova(finding: dict, report_path: Path = None):
    h       = finding.get("hypothesis", {})
    docking = finding.get("docking", {})
    best    = docking.get("best_score")
    payload = {
        "status":      finding.get("status", "novel"),
        "conjecture":  h.get("name", ""),
        "domain":      h.get("cancer_type", "") + " — " + h.get("target", ""),
        "cases":       0,
        "arxiv":       f"ChEMBL max similarity: {finding.get('chembl', {}).get('max_similarity', 0):.1f}%",
        "proof":       finding.get("analysis", "") or "",
        "timestamp":   finding.get("timestamp", datetime.now().isoformat()),
        "type":        "chemistry",
        "report_path": str(report_path) if report_path else "",
        "dock_best":   f"{best:.2f} kcal/mol vs {docking.get('best_target','')}" if best else "N/A",
    }
    try:
        ALERT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("Nova alert written")
    except Exception as e:
        log.warning(f"Alert write failed: {e}")

# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="5">
<title>Nova Cancer Researcher</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#000;color:#fff;font-family:'Courier New',monospace;padding:20px;font-size:14px}}
h1{{color:#00ff88;font-size:1.3em;letter-spacing:4px;text-transform:uppercase;border-bottom:2px solid #00ff88;padding-bottom:8px;margin-bottom:18px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
.panel{{background:#050f05;border:1px solid #143;border-radius:6px;padding:14px}}
.panel-title{{color:#00cc66;font-size:.72em;letter-spacing:3px;text-transform:uppercase;margin-bottom:10px;border-bottom:1px solid #143;padding-bottom:5px}}
.row{{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #0a1a0a;font-size:.83em}}
.lbl{{color:#557755}}.val{{color:#00ff88;font-weight:bold}}
.val.g{{color:#66ffaa}}.val.b{{color:#66ccff}}.val.r{{color:#ff6666}}.val.y{{color:#ffcc00}}
.cbox{{background:#030a03;border-left:3px solid #00ff88;padding:8px 12px;font-size:.78em;line-height:1.55;color:#ccc;margin-top:8px;min-height:55px;word-break:break-word}}
.logbox{{font-size:.7em;line-height:1.65;color:#335533}}
.logbox .w{{color:#ff6666}}.logbox .i{{color:#224422}}
.finding{{background:#030a03;border-left:3px solid #00cc66;padding:7px 11px;margin-bottom:7px;font-size:.79em;line-height:1.5}}
.badge{{display:inline-block;padding:1px 8px;border-radius:3px;font-size:.68em;font-weight:bold;margin-bottom:3px;letter-spacing:2px;text-transform:uppercase}}
.bn{{background:#0a2a1a;color:#00ff88}}.be{{background:#0a1a2a;color:#9999ff}}.bp{{background:#2a1a00;color:#ffcc00}}
.cancer{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:.65em;background:#1a0505;border:1px solid #ff4444;color:#ff8888;margin-left:4px}}
.dock{{display:inline-block;padding:1px 6px;border-radius:3px;font-size:.65em;background:#0a0a2a;border:1px solid #6666ff;color:#aaaaff;margin-left:4px}}
.phase-idle{{color:#224422}}.phase-generating{{color:#66ccff}}.phase-verifying{{color:#00ff88}}
.phase-pubchem{{color:#cc88ff}}.phase-chembl{{color:#ffcc00}}.phase-admet{{color:#66ffaa}}
.phase-docking{{color:#ff9900}}.phase-escalating{{color:#ff6666}}.phase-notifying{{color:#00ff88}}
.footer{{font-size:.72em;color:#112211;margin-top:14px;text-align:right}}
</style>
</head>
<body>
<h1>&#129516; Nova Cancer Researcher</h1>
<div class="grid">
<div class="panel">
  <div class="panel-title">System Status</div>
  <div class="row"><span class="lbl">Phase</span><span class="val phase-{phase}">{phase_upper}</span></div>
  <div class="row"><span class="lbl">Cycles run</span><span class="val">{cycle_count}</span></div>
  <div class="row"><span class="lbl">Survivors</span><span class="val g">{found_count}</span></div>
  <div class="row"><span class="lbl">Last cycle</span><span class="val b">{last_cycle}</span></div>
  <div class="row"><span class="lbl">Next cycle</span><span class="val b">{next_cycle}</span></div>
  <div class="row"><span class="lbl">Model</span><span class="val">{model}</span></div>
  <div class="row"><span class="lbl">RDKit</span><span class="val {rdkit_class}">{rdkit_s}</span></div>
  <div class="row"><span class="lbl">Docking</span><span class="val {docking_class}">{docking_s}</span></div>
</div>
<div class="panel">
  <div class="panel-title">Current Activity</div>
  <div class="row"><span class="lbl">State</span><span class="val">{state}</span></div>
  <div class="row"><span class="lbl">Cancer type</span><span class="val y">{cancer_type}</span></div>
  <div class="row"><span class="lbl">Target</span><span class="val b" style="font-size:.8em">{target}</span></div>
  <div class="row"><span class="lbl">Dock scores</span><span class="val" style="font-size:.75em;color:#ff9900">{dock_scores}</span></div>
  <div class="row"><span class="lbl">SMILES</span><span class="val" style="font-size:.7em;max-width:55%;text-align:right;word-break:break-all;color:#66ff88">{smiles}</span></div>
  <div class="panel-title" style="margin-top:8px">Active Hypothesis</div>
  <div class="cbox">{hypothesis}</div>
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
<div class="footer">Started: {started} &nbsp;|&nbsp; Refreshes every 5s &nbsp;|&nbsp; Cancer Drug Discovery + Docking</div>
</body>
</html>"""


def build_dashboard(journal: "ChemJournal") -> str:
    phase     = STATUS["phase"]
    survivors = journal.recent_survivors(5)

    if survivors:
        parts = []
        for s in reversed(survivors):
            st   = s.get("status", "novel")
            bc   = {"novel": "bn", "escalated": "be", "promising": "bp"}.get(st, "bn")
            h    = s.get("hypothesis", {})
            ts   = s.get("timestamp", "")[:16]
            dock = s.get("docking", {})
            best = dock.get("best_score")
            dock_tag = (
                f'<span class="dock">&#9875; {best:.2f} vs {dock.get("best_target","")}</span>'
                if best is not None else ""
            )
            parts.append(
                f'<div class="finding">'
                f'<span class="badge {bc}">{st.upper()}</span>'
                f'<span class="cancer">{h.get("cancer_type","")[:20]}</span>'
                f'{dock_tag}<br>'
                f'<strong>{h.get("name","")}</strong><br>'
                f'<span style="color:#335;font-size:.85em">Target: {h.get("target","")[:40]}</span><br>'
                f'<span style="color:#224;font-size:.8em">{ts}</span>'
                f'</div>'
            )
        findings_html = "".join(parts)
    else:
        findings_html = '<div style="color:#223;font-size:.85em;padding:8px">No survivors yet.</div>'

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
            secs       = int((datetime.fromisoformat(next_cycle) - datetime.now()).total_seconds())
            next_cycle = f"in {max(0,secs)}s"
        except Exception:
            pass

    last_cycle = STATUS.get("last_cycle", "")
    if last_cycle:
        last_cycle = last_cycle[11:19]

    dock_scores_raw = STATUS.get("dock_scores", {})
    dock_scores_str = "  ".join(f"{t}:{s}" for t, s in dock_scores_raw.items()) if dock_scores_raw else "—"

    rdkit_class   = 'g' if RDKIT_AVAILABLE else 'r'
    docking_class = 'g' if DOCKING_AVAILABLE else 'r'

    return DASHBOARD_HTML.format(
        phase=phase, phase_upper=phase.upper(),
        cycle_count=STATUS["cycle_count"], found_count=STATUS["found_count"],
        last_cycle=last_cycle or "—", next_cycle=next_cycle or "—",
        model=OLLAMA_MODEL,
        rdkit_s="✓ Available" if RDKIT_AVAILABLE else "✗ Not installed",
        rdkit_class=rdkit_class,
        docking_s="✓ Available" if DOCKING_AVAILABLE else "✗ Not found",
        docking_class=docking_class,
        state=STATUS["state"],
        cancer_type=STATUS.get("cancer_type", "—")[:30],
        target=STATUS.get("target", "—")[:40],
        dock_scores=dock_scores_str,
        smiles=STATUS["smiles"][:50] or "—",
        hypothesis=STATUS["hypothesis"][:250] or "Waiting...",
        log_lines=log_lines, findings_html=findings_html,
        started=STATUS["started"][:16],
    )


def make_handler(journal: ChemJournal):
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


def start_dashboard_server(journal: ChemJournal):
    server = HTTPServer(("0.0.0.0", DASHBOARD_PORT), make_handler(journal))
    Thread(target=server.serve_forever, daemon=True).start()
    log.info(f"Dashboard → http://localhost:{DASHBOARD_PORT}")

# ---------------------------------------------------------------------------
# Main research loop
# ---------------------------------------------------------------------------

class CancerResearcher:

    def __init__(self):
        self.journal      = ChemJournal()
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
        STATUS["dock_scores"]  = {}

        update_status(
            phase="generating", domain=domain,
            state="Asking Ollama for hypothesis...",
            hypothesis="", smiles="", target="", cancer_type=""
        )
        log.info(f"--- Cycle {STATUS['cycle_count']} | {domain[:70]} ---")

        # 1. Generate hypothesis
        hypothesis = await generate_hypothesis(domain)
        if not hypothesis:
            update_status(phase="idle", state="Generation failed")
            return

        name        = hypothesis.get("name", "Unknown")
        smiles      = hypothesis.get("smiles", "")
        target      = hypothesis.get("target", "")
        cancer_type = hypothesis.get("cancer_type", "")

        update_status(
            hypothesis=f"{name}: {hypothesis.get('hypothesis','')[:180]}",
            smiles=smiles[:50], target=target[:40],
            cancer_type=cancer_type[:30],
            state="Verifying structure..."
        )
        log.info(f"Hypothesis: {name} | Target: {target} | Cancer: {cancer_type}")

        # 2. RDKit validation
        update_status(phase="verifying")
        verification = verify_molecule(smiles)

        if smiles and not verification["valid"]:
            log.info("Invalid SMILES — attempting repair...")
            fixed = await repair_smiles(smiles, name)
            if fixed:
                smiles               = fixed
                hypothesis["smiles"] = fixed
                verification         = verify_molecule(fixed)
            if not verification["valid"]:
                log.info("Repair failed — discarded")
                update_status(phase="idle", state="Invalid structure — discarded")
                self.journal.append({
                    "type": "hypothesis", "hypothesis": hypothesis,
                    "verification": verification, "status": "invalid",
                })
                return

        if smiles and RDKIT_AVAILABLE and not verification["lipinski_ok"]:
            log.info(f"Lipinski fail: {verification['violations']}")
            update_status(phase="idle", state="Lipinski violations — discarded")
            self.journal.append({
                "type": "hypothesis", "hypothesis": hypothesis,
                "verification": verification, "status": "not_druglike",
            })
            return

        # 3. PubChem novelty check
        update_status(phase="pubchem", state="Checking PubChem...")
        pubchem = await pubchem_check(smiles, name)
        if pubchem["found"]:
            log.info(f"Found in PubChem (CID: {pubchem.get('cid')}) — not novel")
            update_status(phase="idle", state="Found in PubChem — not novel")
            self.journal.append({
                "type": "hypothesis", "hypothesis": hypothesis,
                "verification": verification, "pubchem": pubchem,
                "status": "known",
            })
            return

        log.info("Not in PubChem — potentially novel!")
        STATUS["found_count"] += 1

        # 3b. Rename from actual structure
        update_status(phase="pubchem", state="Getting IUPAC name...")
        hypothesis["ollama_name"] = hypothesis.get("name", "")
        iupac = await rename_compound(hypothesis, smiles)
        if iupac:
            hypothesis["name"] = iupac
            name               = iupac
            log.info(f"Renamed: {hypothesis['ollama_name']} → {name[:60]}")

        # 4. ChEMBL similarity
        update_status(phase="chembl", state="Searching ChEMBL...")
        chembl = await chembl_similarity_search(smiles)
        log.info(f"ChEMBL: max similarity {chembl['max_similarity']:.1f}%, "
                 f"{len(chembl['similar_compounds'])} similar found")

        # 5. ADMET
        update_status(phase="admet", state="Running ADMET predictions...")
        admet = await swissadme_predict(smiles)
        log.info(f"ADMET: GI={admet['gi_absorption']}, BBB={admet['bbb_permeant']}, "
                 f"Drug-like={admet['druglikeness']}")

        # 6. Docking
        docking = await run_docking(smiles, name, target, cancer_type)

        if DOCKING_AVAILABLE and not docking.get("passes_filter", True):
            best = docking.get("best_score")
            log.info(f"Docking filter: {best:.2f} kcal/mol — below threshold, discarded")
            update_status(phase="idle", state=f"Poor docking ({best:.2f} kcal/mol) — discarded")
            self.journal.append({
                "type": "hypothesis", "hypothesis": hypothesis,
                "verification": verification, "pubchem": pubchem,
                "chembl": chembl, "admet": admet, "docking": docking,
                "status": "poor_docking",
            })
            return

        if docking.get("best_score") is not None:
            log.info(
                f"Docking PASSED: {docking['best_score']:.2f} kcal/mol vs "
                f"{docking['best_target']} — escalating to Claude"
            )

        # 7. Claude oncology analysis
        update_status(phase="escalating", state="Escalating to Claude for oncology analysis...")
        analysis = await oncology_analysis(hypothesis, verification, pubchem, chembl, admet, docking)
        log.info(f"Analysis received ({len(analysis)} chars)")

        al     = analysis.lower()
        status = (
            "promising" if any(
                w in al for w in ["highly promising", "strong candidate", "excellent", "high confidence"]
            ) else "escalated"
        )

        # 8. Save report
        finding = {
            "type":         "hypothesis",
            "hypothesis":   hypothesis,
            "verification": verification,
            "pubchem":      pubchem,
            "chembl":       chembl,
            "admet":        admet,
            "docking":      docking,
            "analysis":     analysis,
            "status":       status,
        }
        self.journal.append(finding)

        report_path = None
        try:
            report_path = save_report_as_html(finding)
        except Exception as e:
            log.warning(f"Report save failed: {e}")

        # 9. Notify Nova
        update_status(phase="notifying", state=f"[{status.upper()}] {name} — notifying Nova...")
        notify_nova(finding, report_path)

        update_status(phase="idle", state=f"[{status.upper()}] {name}")
        log.info(f"Result [{status}]: {name} | Report: {report_path}")

    async def run(self):
        self.running = True
        start_dashboard_server(self.journal)
        log.info(f"Cancer Researcher started. Dashboard → http://localhost:{DASHBOARD_PORT}")
        if not RDKIT_AVAILABLE:
            log.warning("RDKit not available — pip install rdkit")
        if not DOCKING_AVAILABLE:
            log.warning("Docking not available — nova_docking.py must be in same directory")

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


async def main():
    researcher = CancerResearcher()
    try:
        await researcher.run()
    except KeyboardInterrupt:
        log.info("Shutting down.")
        researcher.stop()


if __name__ == "__main__":
    asyncio.run(main())
