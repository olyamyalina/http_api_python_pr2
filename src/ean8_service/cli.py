import argparse
import json
import sys
from pathlib import Path

from .barcode import generate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="UTF-8 JSON input file")
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        result = generate(data)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2
    sys.stdout.buffer.write(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
