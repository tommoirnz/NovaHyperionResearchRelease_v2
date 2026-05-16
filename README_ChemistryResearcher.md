# Optional Chemistry Stack (AutoDock Vina)

The following packages are **not included** in the main `requirements.txt` because `vina` requires
the Boost C++ libraries, which pip cannot install on Windows without conda.

**Packages:** `vina`, `rdkit`, `meeko`, `gemmi`

---

## Step 1 — Install Miniconda (if you don't have it)

Conda is not pre-installed on Windows. Download and install **Miniconda** (lightweight, ~100MB):

https://docs.conda.io/en/latest/miniconda.html

During setup, tick **"Add Miniconda to my PATH"** or use the **Anaconda Prompt** that gets added
to your Start menu after installation.

---

## Step 2 — Install the Chemistry Stack

Open **Anaconda Prompt** and run:

```bash
conda install -c conda-forge vina rdkit meeko gemmi
```

Conda bundles Boost automatically — no manual C++ setup needed.

---

## Step 3 — Verify

```python
from vina import Vina
from rdkit import Chem
import meeko, gemmi
print("Chemistry stack OK")
```

---

## pip alternative (advanced)

Only if you are comfortable with C++ build toolchains. You must first install the
[Boost C++ Libraries](https://www.boost.org/users/download/) manually and ensure they are on
your system PATH. Then:

```bash
pip install rdkit meeko gemmi vina
```

Not recommended on Windows.
