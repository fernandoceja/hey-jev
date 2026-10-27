#!/usr/bin/env python3
"""Print salted hashes for a local REA money-id file.

The id file stays on this Mac and is gitignored. This script writes hashes
only. Pass a JSON object with ``bundle_ids`` and ``domains``:

    python3 scripts/rea_money_hashes.py rea-money-ids.local.json

Use the same salt as ``commands/rea_money_hashes.json``. Paste the printed
hashes into that file when the built-in set should grow. Do not commit the
id file.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from commands.rea_analyze import hashes_for_id_file


def main(argv):
    if len(argv) != 2:
        sys.stderr.write("usage: rea_money_hashes.py IDS.json\n")
        return 2
    try:
        payload = hashes_for_id_file(argv[1])
    except ValueError:
        sys.stderr.write("The id file must be a JSON object of string ids.\n")
        return 1
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
