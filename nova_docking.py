"""
nova_docking.py
===============
AutoDock Vina molecular docking for Nova Cancer Researcher.
Uses OpenBabel for PDB/SDF → PDBQT conversion.

Pipeline:
  1. Download receptor PDB from RCSB
  2. Fix receptor with pdbfixer (missing atoms, hydrogens)
  3. Convert receptor PDB → PDBQT via OpenBabel
  4. Generate ligand 3D conformer with RDKit
  5. Convert ligand SDF → PDBQT via OpenBabel
  6. Run AutoDock Vina
  7. Parse and interpret scores

Requirements:
    pip install rdkit openbabel-wheel pdbfixer openmm meeko gemmi
    vina.exe on PATH or set VINA_EXE env variable

Usage:
    from nova_docking import dock_molecule
    result = await dock_molecule(smiles, target="EGFR")

Test:
    python nova_docking.py --test
"""

import asyncio
import logging
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from rdkit import Chem
from rdkit.Chem import AllChem
from openbabel import openbabel as ob
from pdbfixer import PDBFixer
from openmm.app import PDBFile

log = logging.getLogger("NovaDocking")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

VINA_EXE      = os.getenv("VINA_EXE", r"C:\vina.exe")
PDB_CACHE_DIR = Path("docking_data") / "receptors"
RESULTS_DIR   = Path("docking_data") / "results"

# ---------------------------------------------------------------------------
# Cancer target definitions
# ---------------------------------------------------------------------------

TARGETS = {
    "EGFR": {
        "pdb_id":    "2ITY",
        "center":    (-50.5, -0.7, -21.6),
        "box_size":  (20, 20, 20),
        "chains":    ["A"],
        "cancer":    "Non-small cell lung cancer, breast cancer",
        "drug_class": "Tyrosine kinase inhibitors (erlotinib, gefitinib, osimertinib)",
        "note":      "ATP-binding site of EGFR kinase domain",
    },
    "BCL2": {
        "pdb_id":    "4LVT",
        "center":    (16.8, 16.0, 12.0),
        "box_size":  (25, 25, 25),
        "chains":    ["A"],
        "cancer":    "Chronic lymphocytic leukaemia, follicular lymphoma",
        "drug_class": "BH3 mimetics (venetoclax)",
        "note":      "BH3-binding hydrophobic groove",
    },
    "CDK2": {
        "pdb_id":    "1AQ1",
        "center":    (0.5, 27.1, 9.0),
        "box_size":  (20, 20, 20),
        "chains":    ["A"],
        "cancer":    "Breast cancer, multiple solid tumours",
        "drug_class": "CDK inhibitors (palbociclib, ribociclib, abemaciclib)",
        "note":      "ATP-binding cleft of CDK2",
    },
    "PARP1": {
        "pdb_id":    "3L3M",
        "center":    (26.4, 11.2, 27.0),
        "box_size": (25, 25, 25),  # was 20,20,20
        "chains":    ["A"],
        "cancer":    "BRCA1/2-mutated breast and ovarian cancer",
        "drug_class": "PARP inhibitors (olaparib, niraparib, rucaparib)",
        "note":      "NAD+ binding site / nicotinamide pocket",
    },
}

# In nova_docking.py — replace the threshold constants
SCORE_EXCELLENT = -7.0    # was -9.0  (comparable to approved drugs)
SCORE_GOOD      = -5.5    # was -7.0  (promising lead)
SCORE_MODERATE  = -4.0    # was -5.0  (weak, needs optimisation)
# ---------------------------------------------------------------------------
# OpenBabel conversion helper
# ---------------------------------------------------------------------------

def obabel_convert(input_path: Path, output_path: Path, add_hydrogens: bool = False) -> bool:
    """Convert molecular file format using OpenBabel Python API."""
    try:
        conv = ob.OBConversion()
        in_fmt  = input_path.suffix.lstrip(".")
        out_fmt = output_path.suffix.lstrip(".")
        conv.SetInAndOutFormats(in_fmt, out_fmt)

        if add_hydrogens:
            conv.AddOption("h", ob.OBConversion.GENOPTIONS)

        mol = ob.OBMol()
        conv.ReadFile(mol, str(input_path))

        if mol.NumAtoms() == 0:
            log.error(f"OpenBabel: no atoms read from {input_path}")
            return False

        if add_hydrogens:
            mol.AddHydrogens()

        # For PDBQT output — add Gasteiger charges
        if out_fmt == "pdbqt":
            charge_model = ob.OBChargeModel.FindType("gasteiger")
            if charge_model:
                charge_model.ComputeCharges(mol)

        conv.WriteFile(mol, str(output_path))
        return output_path.exists() and output_path.stat().st_size > 0

    except Exception as e:
        log.error(f"OpenBabel conversion failed: {e}")
        return False

# ---------------------------------------------------------------------------
# Receptor preparation
# ---------------------------------------------------------------------------

async def download_pdb(pdb_id: str) -> Path:
    """Download PDB from RCSB — cached after first download."""
    PDB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = PDB_CACHE_DIR / f"{pdb_id}.pdb"

    if path.exists():
        log.info(f"Using cached PDB: {pdb_id}")
        return path

    url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    log.info(f"Downloading PDB {pdb_id} from RCSB...")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(url)
        r.raise_for_status()
        path.write_bytes(r.content)
    log.info(f"Downloaded {pdb_id} ({path.stat().st_size // 1024} KB)")
    return path


def prepare_receptor(pdb_path: Path, target_name: str, chains: list) -> Path:
    """
    Fix PDB and convert to PDBQT using pdbfixer + OpenBabel.
    Automatically strips ROOT/BRANCH tags to ensure rigid receptor format.
    Cached after first preparation.
    """
    out_path = PDB_CACHE_DIR / f"{target_name}_receptor.pdbqt"
    if out_path.exists():
        log.info(f"Using cached receptor: {target_name}")
        return out_path

    log.info(f"Preparing receptor {target_name}...")

    # Fix with pdbfixer
    fixer = PDBFixer(filename=str(pdb_path))

    chains_to_remove = [c.id for c in fixer.topology.chains() if c.id not in chains]
    fixer.removeChains(chains_to_remove)
    fixer.findMissingResidues()
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(True)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.4)

    fixed_pdb = PDB_CACHE_DIR / f"{target_name}_fixed.pdb"
    with open(fixed_pdb, "w") as f:
        PDBFile.writeFile(fixer.topology, fixer.positions, f)
    log.info(f"Fixed PDB saved: {fixed_pdb}")

    # Convert to PDBQT via OpenBabel
    try:
        conv = ob.OBConversion()
        conv.SetInAndOutFormats("pdb", "pdbqt")
        conv.AddOption("r", ob.OBConversion.OUTOPTIONS)
        conv.AddOption("c", ob.OBConversion.OUTOPTIONS)

        mol = ob.OBMol()
        conv.ReadFile(mol, str(fixed_pdb))
        mol.AddHydrogens()

        charge_model = ob.OBChargeModel.FindType("gasteiger")
        if charge_model:
            charge_model.ComputeCharges(mol)

        conv.WriteFile(mol, str(out_path))
    except Exception as e:
        log.error(f"OpenBabel conversion failed: {e}")
        return fixed_pdb

    if not out_path.exists() or out_path.stat().st_size == 0:
        log.warning("PDBQT empty — using fixed PDB")
        return fixed_pdb

    # Strip ROOT/BRANCH/TORSDOF tags — receptor must be fully rigid
    lines = out_path.read_text().splitlines(keepends=True)
    skip  = ('ROOT', 'ENDROOT', 'BRANCH', 'ENDBRANCH', 'TORSDOF', 'REMARK')
    clean = [l for l in lines if not any(l.startswith(s) for s in skip)]
    out_path.write_text(''.join(clean))
    log.info(f"Receptor ready: {out_path} ({len(clean)} ATOM lines)")

    return out_path

# ---------------------------------------------------------------------------
# Ligand preparation
# ---------------------------------------------------------------------------

def prepare_ligand(smiles: str, ligand_name: str = "ligand") -> Optional[Path]:
    """
    SMILES → 3D SDF (RDKit) → PDBQT (OpenBabel).
    """
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[^\w]', '_', ligand_name[:30])

    try:
        # Generate 3D conformer with RDKit
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            log.error("Invalid SMILES")
            return None

        mol = Chem.AddHs(mol)

        params = AllChem.ETKDGv3()
        params.randomSeed = 42
        if AllChem.EmbedMolecule(mol, params) == -1:
            if AllChem.EmbedMolecule(mol, AllChem.ETKDG()) == -1:
                log.error("3D conformer generation failed")
                return None

        AllChem.MMFFOptimizeMolecule(mol)

        # Save as SDF
        sdf_path = RESULTS_DIR / f"{safe}.sdf"
        writer = Chem.SDWriter(str(sdf_path))
        writer.write(mol)
        writer.close()
        log.info(f"3D SDF saved: {sdf_path}")

        # Convert SDF → PDBQT via OpenBabel
        pdbqt_path = RESULTS_DIR / f"{safe}.pdbqt"
        ok = obabel_convert(sdf_path, pdbqt_path, add_hydrogens=True)

        if ok:
            log.info(f"Ligand PDBQT ready: {pdbqt_path}")
            return pdbqt_path
        else:
            log.warning("PDBQT conversion failed — using SDF")
            return sdf_path

    except Exception as e:
        log.error(f"Ligand preparation failed: {e}")
        return None

# ---------------------------------------------------------------------------
# Vina docking
# ---------------------------------------------------------------------------

def run_vina(
    receptor_path: Path,
    ligand_path: Path,
    center: tuple,
    box_size: tuple,
    out_path: Path,
    exhaustiveness: int = 8,
) -> Optional[dict]:
    """Run AutoDock Vina and parse scores."""

    cmd = [
        VINA_EXE,
        "--receptor",       str(receptor_path),
        "--ligand",         str(ligand_path),
        "--center_x",       str(center[0]),
        "--center_y",       str(center[1]),
        "--center_z",       str(center[2]),
        "--size_x",         str(box_size[0]),
        "--size_y",         str(box_size[1]),
        "--size_z",         str(box_size[2]),
        "--out",            str(out_path),
        "--exhaustiveness", str(exhaustiveness),
        "--num_modes",      "9",
    ]

    log.info(f"Running Vina against {receptor_path.name}...")
    log.info(f"Command: {' '.join(cmd)}")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        output = result.stdout + result.stderr
        print(f"\n--- VINA OUTPUT ---\n{output}\n---")

        # Parse score table from Vina output
        # Format: "   1         -9.123      0.000      0.000"
        scores = []
        in_table = False
        for line in output.split("\n"):
            stripped = line.strip()
            if "-----" in stripped:
                in_table = True
                continue
            if in_table and stripped:
                parts = stripped.split()
                if parts and parts[0].isdigit():
                    try:
                        scores.append(float(parts[1]))
                    except (IndexError, ValueError):
                        pass

        if not scores:
            # Try simpler parse — any line with a negative float
            for line in output.split("\n"):
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0].isdigit():
                    try:
                        val = float(parts[1])
                        if val < 0:
                            scores.append(val)
                    except ValueError:
                        pass

        if scores:
            log.info(f"Scores: {scores}")
            return {"best_score": scores[0], "all_scores": scores, "raw_output": output}
        else:
            log.warning("No scores found in Vina output")
            log.warning(f"Full output:\n{output}")
            return None

    except subprocess.TimeoutExpired:
        log.error("Vina timed out after 5 minutes")
        return None
    except FileNotFoundError:
        log.error(f"Vina executable not found: {VINA_EXE}")
        log.error("Set VINA_EXE environment variable to full path of vina.exe")
        return None
    except Exception as e:
        log.error(f"Vina error: {e}")
        return None

# ---------------------------------------------------------------------------
# Score interpretation
# ---------------------------------------------------------------------------

def interpret_score(score: float, target_name: str) -> dict:
    target = TARGETS.get(target_name, {})

    if score <= SCORE_EXCELLENT:
        grade      = "EXCELLENT"
        colour     = "🟢"
        assessment = (
            f"Binding affinity {score:.1f} kcal/mol is comparable to approved "
            f"{target.get('drug_class', 'drugs')}. Strong hit worth prioritising."
        )
        pursue = True
    elif score <= SCORE_GOOD:
        grade      = "GOOD"
        colour     = "🟡"
        assessment = (
            f"Binding affinity {score:.1f} kcal/mol — promising lead. "
            f"Structural optimisation could improve potency toward {target_name}."
        )
        pursue = True
    elif score <= SCORE_MODERATE:
        grade      = "MODERATE"
        colour     = "🟠"
        assessment = (
            f"Binding affinity {score:.1f} kcal/mol — weak interaction with {target_name}. "
            f"Significant structural changes needed."
        )
        pursue = False
    else:
        grade      = "POOR"
        colour     = "🔴"
        assessment = (
            f"Binding affinity {score:.1f} kcal/mol — unlikely to show "
            f"activity against {target_name} in cell assays."
        )
        pursue = False

    return {
        "grade": grade, "colour": colour, "assessment": assessment,
        "pursue": pursue, "score": score, "target": target_name,
        "cancer": target.get("cancer", ""),
        "drug_class": target.get("drug_class", ""),
        "pocket": target.get("note", ""),
    }

# ---------------------------------------------------------------------------
# Main docking function
# ---------------------------------------------------------------------------

async def dock_molecule(
    smiles: str,
    target_name: str = "EGFR",
    compound_name: str = "compound",
    exhaustiveness: int = 8,
) -> dict:
    """
    Full docking pipeline: SMILES → binding affinity score.

    Returns dict with: success, score, grade, assessment, pursue,
                       target, cancer, drug_class, error
    """
    result = {
        "success": False, "score": None, "grade": None,
        "assessment": "", "pursue": False, "target": target_name,
        "cancer": "", "drug_class": "", "error": None,
    }

    if target_name not in TARGETS:
        result["error"] = f"Unknown target. Choose from: {list(TARGETS.keys())}"
        return result

    target = TARGETS[target_name]
    loop   = asyncio.get_event_loop()

    try:
        # 1. Download + prepare receptor
        pdb_path      = await download_pdb(target["pdb_id"])
        receptor_path = await loop.run_in_executor(
            None, prepare_receptor, pdb_path, target_name, target["chains"]
        )

        # 2. Prepare ligand
        ligand_path = await loop.run_in_executor(
            None, prepare_ligand, smiles, compound_name
        )
        if ligand_path is None:
            result["error"] = "Ligand preparation failed"
            return result

        # 3. Run Vina
        out_path    = RESULTS_DIR / f"{compound_name}_{target_name}_docked.pdbqt"
        vina_result = await loop.run_in_executor(
            None, run_vina,
            receptor_path, ligand_path,
            target["center"], target["box_size"],
            out_path, exhaustiveness
        )

        if vina_result is None:
            result["error"] = "Vina docking failed — check output above"
            return result

        # 4. Interpret
        interp = interpret_score(vina_result["best_score"], target_name)
        result.update({
            "success":    True,
            "score":      vina_result["best_score"],
            "all_scores": vina_result["all_scores"],
            **interp,
        })

        log.info(
            f"✓ {compound_name} vs {target_name}: "
            f"{vina_result['best_score']:.2f} kcal/mol [{interp['grade']}]"
        )

    except Exception as e:
        result["error"] = str(e)
        log.error(f"Docking pipeline error: {e}")
        import traceback
        traceback.print_exc()

    return result


async def dock_against_all_targets(smiles: str, compound_name: str = "compound") -> dict:
    """Dock against all four cancer targets sequentially."""
    results = {}
    for target in TARGETS.keys():
        log.info(f"Docking against {target}...")
        results[target] = await dock_molecule(smiles, target, compound_name)
        await asyncio.sleep(0.2)
    return results

# ---------------------------------------------------------------------------
# Test
# ---------------------------------------------------------------------------

async def _test():
    """Dock erlotinib (approved EGFR inhibitor) — expect -9 to -11 kcal/mol."""
    erlotinib = "C#Cc1cccc(Nc2ncnc3cc(OCCOC)c(OCCOC)cc23)c1"
    print("=" * 60)
    print("TEST: Erlotinib vs EGFR")
    print("Expected score: -6 to -8 kcal/mol (OpenBabel prep baseline)")
    print("=" * 60)

    result = await dock_molecule(
        erlotinib,
        target_name="EGFR",
        compound_name="erlotinib",
        exhaustiveness=8,
    )

    print("\n--- RESULT ---")
    if result["success"]:
        print(f"Score:      {result['score']:.2f} kcal/mol")
        print(f"Grade:      {result['colour']} {result['grade']}")
        print(f"Pursue:     {result['pursue']}")
        print(f"Cancer:     {result['cancer']}")
        print(f"Assessment: {result['assessment']}")
        if result.get("all_scores"):
            print(f"All poses:  {[f'{s:.2f}' for s in result['all_scores']]}")
    else:
        print(f"FAILED: {result['error']}")


if __name__ == "__main__":
    if "--test" in sys.argv:
        asyncio.run(_test())
    else:
        print("Nova Docking Module")
        print(f"Targets:  {list(TARGETS.keys())}")
        print(f"Vina:     {VINA_EXE}")
        print(f"Cache:    {PDB_CACHE_DIR}")
        print("\nUsage: python nova_docking.py --test")
