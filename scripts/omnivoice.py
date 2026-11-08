"""Explicit-save commands; never plays audio or falls back to another engine."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commands.omnivoice_profiles import Profiles
from commands.omnivoice_voice import Worker


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    design = sub.add_parser("design")
    design.add_argument("--description", required=True)
    design.add_argument("--text", required=True)
    design.add_argument("--output", required=True)
    clone = sub.add_parser("clone")
    clone.add_argument("--name", required=True)
    clone.add_argument("--reference", required=True)
    clone.add_argument("--consent", action="store_true")
    clone.add_argument("--ref-text", default="")
    importer = sub.add_parser("import")
    importer.add_argument("--name", required=True)
    importer.add_argument("--filename", required=True)
    importer.add_argument("--consent", action="store_true")
    render = sub.add_parser("render")
    render.add_argument("--name", required=True)
    render.add_argument("--text", required=True)
    render.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    profiles = Profiles()
    if args.command == "clone":
        profiles.create(args.name, args.reference, consent=args.consent,
                        settings={"ref_text": args.ref_text})
    elif args.command == "import":
        profiles.import_voice(args.name, args.filename, consent=args.consent)
    else:
        worker = Worker()
        try:
            if args.command == "design":
                if not args.description.strip():
                    parser.error("Description cannot be empty")
                result = worker.render(args.text, args.output, description=args.description)
            else:
                result = profiles.render(args.name, args.text, args.output, worker)
            print(result[0])
        finally:
            worker.close()


if __name__ == "__main__":
    main()
