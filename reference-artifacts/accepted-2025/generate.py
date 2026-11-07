"""Replay the 2025 capture inputs through the working-tree calculation."""

import importlib
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
CAPTURE = ROOT / "reference-artifacts" / "current-config-2025" / "reproduce.py"

# Load the working packages and register them under the top-level names that
# the capture script imports. The capture script then adds its saved source to
# sys.path, but Python reuses these already-loaded modules. The checkout no
# longer has the legacy `config` package, so the replay uses the capture's
# identical saved copy.
sys.path.insert(0, str(ROOT))
for name in (
    "rating_fetcher.api_client",
    "rating_fetcher.processor",
    "results_processor.processor",
    "rilton_processor.processor",
    "standings_generator.excel_exporter",
    "standings_generator.processor",
):
    package = name.partition(".")[0]
    sys.modules[package] = importlib.import_module(f"senior_gp.{package}")
    sys.modules[name] = importlib.import_module(f"senior_gp.{name}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: generate.py NEW_OUTPUT_DIRECTORY")
    sys.argv = [str(CAPTURE), sys.argv[1]]
    runpy.run_path(str(CAPTURE), run_name="__main__")
