"""Start the configured visible browser without PowerShell script execution."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parent
candidate = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
python = str(candidate) if candidate.is_file() else sys.executable
sys.exit(subprocess.call([python, "-X", "utf8", "-B", str(root / "scripts/setup.py"),
                          "browser", *sys.argv[1:]]))
