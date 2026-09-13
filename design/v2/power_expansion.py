"""Power expansion candidate: mechanically reserved second battery bay.

The second pack is an envelope only until a purchased pack's drawing is
available.  It deliberately does not invent connector, BMS, or hole sizes.
"""
from pathlib import Path
import json

ROOT = Path(__file__).parent

def candidate():
    return {
        "status": "mechanical-reservation",
        "architecture": "separate protected battery source with fuse and ideal-diode OR-ing",
        "primary_pack": "Gens-Ace-GEA223S25T3GT",
        "secondary_pack": None,
        "secondary_envelope_mm": None,
        "mounting": "reuse battery-tray strap concept only after pack drawing and connector are selected",
        "mass_g": None,
        "mass_budget_warning": "current known assembly already exceeds 2.45 kg; no added pack may be claimed compliant",
        "required_evidence": ["supplier mechanical drawing", "BMS/charge specification", "connector rating", "thermal test", "fuse and wire gauge"],
    }

if __name__ == "__main__":
    print(json.dumps(candidate(), ensure_ascii=False, indent=2))
