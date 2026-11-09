"""Explicit-save commands; never plays audio or falls back to another engine."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from commands.omnivoice_design import describe_to_tags
from commands.omnivoice_profiles import Profiles
from commands.omnivoice_voice import Worker


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    design = sub.add_parser("design")
    design.add_argument("--description", required=True)
    design.add_argument("--tags-only", action="store_true")
    design.add_argument("--text")
    design.add_argument("--output")
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
    for profile_parser in (clone, importer, render):
        profile_parser.add_argument("--profiles-root")
    for profile_parser in (clone, importer):
        profile_parser.add_argument("--auto-transcribe", action="store_true")
    importer.add_argument("--ref-text", default="")
    args = parser.parse_args(argv)
    if args.command == "design":
        mapping = describe_to_tags(args.description)
        if args.tags_only:
            print(mapping.message)
            return
        if not args.text or not args.output:
            parser.error("design requires --text and --output unless --tags-only")
        print(mapping.message, file=sys.stderr)
    profiles = Profiles(getattr(args, "profiles_root", None))
    if args.command == "clone":
        profiles.create(args.name, args.reference, consent=args.consent,
                        ref_text=args.ref_text, auto_transcribe=args.auto_transcribe)
    elif args.command == "import":
        profiles.import_voice(args.name, args.filename, consent=args.consent,
                              ref_text=args.ref_text, auto_transcribe=args.auto_transcribe)
    else:
        worker = Worker()
        try:
            if args.command == "design":
                if not args.description.strip():
                    parser.error("Description cannot be empty")
                result = worker.render(args.text, args.output, description=mapping.instruct)
            else:
                result = profiles.render(args.name, args.text, args.output, worker)
            print(result[0])
        finally:
            worker.close()


if __name__ == "__main__":
    main()
