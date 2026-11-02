"""Run all five stage-one examples without shell binary redirection."""

import subprocess
import sys
from pathlib import Path


def main():
    """Save raw CLI stdout as PDF and print a readable execution log."""
    root = Path(__file__).resolve().parents[1]
    output = root / "output" / "pdf"
    output.mkdir(parents=True, exist_ok=True)
    for source in sorted((root / "examples").glob("*.json")):
        result = subprocess.run(
            [sys.executable, "-m", "ean8_service.cli", str(source)],
            capture_output=True, check=True,
        )
        target = output / (source.stem + ".pdf")
        target.write_bytes(result.stdout)
        print(f"{source.name} -> {target.name}: {len(result.stdout)} bytes")


if __name__ == "__main__":
    main()
