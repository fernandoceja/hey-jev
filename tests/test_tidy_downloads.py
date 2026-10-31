"""PR 8d: Tidy Downloads and Desktop, scan only. Pure functions over tmp_path trees. Headless."""
import ast
import os

import pytest

import commands
from commands import tidy_downloads as td
from commands.bridge import bridge_allowed
from commands.config import BRIDGE_ALLOW
from commands.zoe_mode import ZOE_ALLOW
from commands.routing import route_before_api

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAY = 86400.0
NOW = 1_800_000_000.0  # a fixed "now" so ages are exact


def make(folder, name, size=10, age_days=0.0):
    """A file of size bytes, dated age_days before NOW."""
    path = folder / name
    path.write_bytes(b"x" * size)
    stamp = NOW - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


# ---------------------------------------------------------------- phrases

@pytest.mark.parametrize("text, key", [
    ("tidy my downloads", "downloads"),
    ("Tidy My Downloads!", "downloads"),
    ("tidy up my downloads", "downloads"),
    ("tidy the downloads folder", "downloads"),
    ("tidy my desktop", "desktop"),
    ("  tidy   my  desktop  ", "desktop"),
    ("hey jev, tidy my downloads please", "downloads"),
    ("please tidy my desktop.", "desktop"),
])
def test_tidy_phrases_name_the_folder(text, key):
    assert td.tidy_folder_key(text) == key


@pytest.mark.parametrize("text", [
    "tidy my documents", "tidy my downloads tomorrow", "tidy", "tidy up", "clean up my downloads", "",
    "   ", "move my downloads", "tidy my downloads and delete the installers", "brief me",
])
def test_other_sentences_are_not_tidy_requests(text):
    assert td.tidy_folder_key(text) is None


def test_non_text_input_is_not_a_tidy_request():
    for value in (None, 7, b"tidy my downloads", ["tidy my downloads"]):
        assert td.tidy_folder_key(value) is None


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize("name, kind", [
    ("Chrome.dmg", "Installers"), ("setup.PKG", "Installers"), ("disk.iso", "Installers"),
    ("photo.HEIC", "Images"), ("shot.png", "Images"),
    ("report.pdf", "Documents"), ("sheet.xlsx", "Documents"),
    ("clip.mov", "Media"), ("song.m4a", "Media"),
    ("bundle.zip", "Archives"), ("src.tar.gz", "Archives"),
    ("notes", "Other"), ("data.bin", "Other"), (".hidden", "Other"),
])
def test_file_type_comes_from_the_extension(name, kind):
    assert td.file_type(name) == kind


def test_age_is_never_negative():
    assert td.age_days(NOW + 5 * DAY, now=NOW) == 0.0
    assert td.age_days(NOW - 2 * DAY, now=NOW) == pytest.approx(2.0)


@pytest.mark.parametrize("days, bucket", [
    (0, "Under 30 days"), (29.9, "Under 30 days"), (30, "30 days to a year"),
    (364.9, "30 days to a year"), (365, "Over a year"), (900, "Over a year"),
])
def test_age_buckets_have_clean_edges(days, bucket):
    assert td.age_bucket(days) == bucket


@pytest.mark.parametrize("size, text", [
    (0, "0 B"), (1023, "1023 B"), (1024, "1.0 KB"), (1536, "1.5 KB"),
    (5 * 1024 * 1024, "5.0 MB"), (int(1.2 * 1024 ** 3), "1.2 GB"), (3 * 1024 ** 4, "3.0 TB"),
    (-5, "0 B"),
])
def test_human_size(size, text):
    assert td.human_size(size) == text


# ---------------------------------------------------------------- scan

def test_scan_lists_top_level_files_only(tmp_path):
    make(tmp_path, "a.pdf", size=3)
    make(tmp_path, "B.dmg", size=5)
    (tmp_path / "sub").mkdir()
    make(tmp_path / "sub", "inner.pdf")
    make(tmp_path, ".DS_Store")
    files, truncated = td.scan_folder(str(tmp_path))
    assert [f["name"] for f in files] == ["a.pdf", "B.dmg"]  # sorted, case-insensitive
    assert files[0]["size"] == 3 and files[1]["size"] == 5
    assert truncated is False


def test_scan_skips_symlinks(tmp_path):
    target = make(tmp_path, "real.pdf")
    os.symlink(target, tmp_path / "link.pdf")
    files, _ = td.scan_folder(str(tmp_path))
    assert [f["name"] for f in files] == ["real.pdf"]


def test_scan_of_a_missing_folder_is_empty(tmp_path):
    assert td.scan_folder(str(tmp_path / "nope")) == ([], False)


def test_scan_caps_the_count_and_says_so(tmp_path):
    for i in range(5):
        make(tmp_path, "f{0}.txt".format(i))
    files, truncated = td.scan_folder(str(tmp_path), max_files=3)
    assert len(files) == 3
    assert truncated is True


def test_scan_leaves_the_tree_exactly_as_it_was(tmp_path):
    make(tmp_path, "Chrome.dmg", size=100, age_days=400)
    make(tmp_path, "report (1).pdf", size=20, age_days=2)
    make(tmp_path, "report.pdf", size=20, age_days=200)
    (tmp_path / "keep").mkdir()

    def snapshot():
        return sorted((e.name, e.stat().st_size, e.stat().st_mtime) for e in os.scandir(tmp_path))

    before = snapshot()
    td.tidy_scan("downloads", str(tmp_path), now=NOW)
    td.build_report(td.scan_folder(str(tmp_path))[0], now=NOW)
    assert snapshot() == before


# ---------------------------------------------------------------- duplicates

def test_a_copy_with_the_same_size_is_a_possible_duplicate(tmp_path):
    original = make(tmp_path, "report.pdf", size=50)
    copy_ = make(tmp_path, "report (1).pdf", size=50)
    files, _ = td.scan_folder(str(tmp_path))
    pairs = td.find_duplicates(files)
    assert [(c["name"], o["name"]) for c, o in pairs] == [("report (1).pdf", "report.pdf")]
    assert original.exists() and copy_.exists()


def test_a_copy_with_a_different_size_is_not_flagged(tmp_path):
    make(tmp_path, "report.pdf", size=50)
    make(tmp_path, "report copy.pdf", size=51)
    files, _ = td.scan_folder(str(tmp_path))
    assert td.find_duplicates(files) == []


def test_copy_words_and_numbers_both_match_and_the_extension_is_kept(tmp_path):
    make(tmp_path, "notes.txt", size=7)
    make(tmp_path, "notes copy 2.txt", size=7)
    make(tmp_path, "shot (3).png", size=9)
    make(tmp_path, "shot.png", size=9)
    make(tmp_path, "solo copy.txt", size=4)  # no original in the folder
    files, _ = td.scan_folder(str(tmp_path))
    names = sorted(c["name"] for c, _ in td.find_duplicates(files))
    assert names == ["notes copy 2.txt", "shot (3).png"]


def test_a_file_is_never_its_own_original():
    files = [{"name": "x (1).txt", "path": "", "size": 3, "mtime": 0.0}]
    assert td.find_duplicates(files) == []


def test_no_extension_copy_matches_the_bare_name():
    files = [{"name": "Notes", "size": 2, "path": "", "mtime": 0.0},
             {"name": "Notes (2)", "size": 2, "path": "", "mtime": 0.0}]
    assert [c["name"] for c, _ in td.find_duplicates(files)] == ["Notes (2)"]


# ---------------------------------------------------------------- report

def _f(name, size=1, age=0.0):
    return {"name": name, "path": "/x/" + name, "size": size, "mtime": NOW - age * DAY}


def test_old_installers_use_the_ninety_day_line():
    files = [_f("old.dmg", size=100, age=91), _f("edge.dmg", size=10, age=89), _f("new.pkg", size=5, age=3)]
    report = td.build_report(files, now=NOW)
    assert report["old_installers"]["count"] == 1
    assert report["old_installers"]["examples"] == ["old.dmg"]
    assert report["old_installers"]["bytes"] == 100


def test_old_documents_are_not_installers():
    report = td.build_report([_f("tax.pdf", age=400)], now=NOW)
    assert report["old_installers"]["count"] == 0
    assert report["ages"]["Over a year"] == 1


def test_large_files_are_at_least_the_threshold_and_biggest_first():
    big = td.LARGE_BYTES
    files = [_f("huge.mov", size=big * 2), _f("just.zip", size=big), _f("small.txt", size=big - 1)]
    report = td.build_report(files, now=NOW)
    assert report["large"]["count"] == 2
    assert report["large"]["examples"] == ["huge.mov", "just.zip"]


def test_counts_by_type_and_age_cover_every_file():
    files = [_f("a.dmg", size=3, age=1), _f("b.pdf", size=4, age=40), _f("c.mov", size=5, age=800),
             _f("d", size=6, age=0)]
    report = td.build_report(files, now=NOW)
    assert report["count"] == 4 and report["bytes"] == 18
    assert report["types"]["Installers"] == {"count": 1, "bytes": 3}
    assert report["types"]["Documents"] == {"count": 1, "bytes": 4}
    assert report["types"]["Media"] == {"count": 1, "bytes": 5}
    assert report["types"]["Other"] == {"count": 1, "bytes": 6}
    assert report["ages"] == {"Under 30 days": 2, "30 days to a year": 1, "Over a year": 1}


def test_duplicate_examples_are_listed_and_counted():
    files = [_f("r.pdf", size=2), _f("r (1).pdf", size=2), _f("r copy.pdf", size=2)]
    report = td.build_report(files, now=NOW)
    assert report["duplicates"]["count"] == 2
    assert report["duplicates"]["examples"] == ["r (1).pdf", "r copy.pdf"]


def test_an_empty_folder_gives_an_empty_report():
    report = td.build_report([], now=NOW)
    assert report["count"] == 0 and report["bytes"] == 0
    assert report["old_installers"]["count"] == 0 and report["large"]["count"] == 0
    assert report["duplicates"]["count"] == 0


# ---------------------------------------------------------------- formatting

def test_format_reports_groupings_and_says_nothing_was_moved():
    files = [_f("Chrome.dmg", size=2 * 1024 ** 3, age=120), _f("a.pdf", size=5, age=2)]
    report = td.build_report(files, now=NOW)
    line = td.format_report(report, "Downloads")
    assert line.startswith("Downloads: 2 files, 2.0 GB.")
    assert "By type:" in line and "installers 1" in line and "documents 1" in line
    assert "By age: under 30 days 1, 30 days to a year 1, over a year 0." in line
    assert "Old installers over 90 days: 1, 2.0 GB, e.g. Chrome.dmg." in line
    assert "Possible duplicates: none." in line
    assert "Large files over 500 MB: 1, 2.0 GB, e.g. Chrome.dmg." in line
    assert "I haven't moved, renamed or deleted anything." in line
    assert "\n" not in line


def test_format_names_examples_for_duplicates_and_large_files():
    files = [_f("r.pdf", size=2), _f("r (1).pdf", size=2), _f("movie.mov", size=td.LARGE_BYTES)]
    line = td.format_report(td.build_report(files, now=NOW), "Desktop")
    assert "Possible duplicates: 1, e.g. r (1).pdf." in line
    assert "Large files over 500 MB: 1, 500.0 MB, e.g. movie.mov." in line


def test_an_empty_folder_says_so_plainly():
    line = td.format_report(td.build_report([], now=NOW), "Downloads")
    assert line == "Downloads has no files at the top level, so there's nothing to tidy."


def test_a_truncated_scan_says_how_far_it_went():
    report = td.build_report([_f("a.txt")], now=NOW, truncated=True)
    assert "Only the first {0} files were checked.".format(td.MAX_FILES) in td.format_report(report, "Downloads")


def test_the_reply_stays_one_line_for_the_window_and_offer():
    files = [_f("n{0}.dmg".format(i), size=td.LARGE_BYTES, age=200) for i in range(9)]
    line = td.format_report(td.build_report(files, now=NOW), "Downloads")
    assert "\n" not in line
    assert line.count("e.g.") <= 3


# ---------------------------------------------------------------- end to end on a tmp tree

def test_tidy_scan_on_a_real_tree(tmp_path):
    make(tmp_path, "Chrome.dmg", size=1024, age_days=120)
    make(tmp_path, "scan.pdf", size=10, age_days=3)
    make(tmp_path, "scan (1).pdf", size=10, age_days=3)
    line = td.tidy_scan("downloads", str(tmp_path), now=NOW)
    assert line.startswith("Downloads: 3 files,")
    assert "Old installers over 90 days: 1, 1.0 KB, e.g. Chrome.dmg." in line
    assert "Possible duplicates: 1, e.g. scan (1).pdf." in line


def test_tidy_scan_of_a_missing_folder_says_so(tmp_path):
    assert td.tidy_scan("desktop", str(tmp_path / "gone"), now=NOW) == "I couldn't find your desktop folder."


def test_tidy_scan_from_text_uses_the_existing_folder_paths(tmp_path, monkeypatch):
    seen = []

    def fake_resolve(key):
        seen.append(key)
        return str(tmp_path)

    monkeypatch.setattr(td, "resolve_folder", fake_resolve)
    make(tmp_path, "a.txt")
    line = td.tidy_scan_from_text("tidy my downloads", now=NOW)
    assert seen == ["downloads"]
    assert line.startswith("Downloads: 1 files,")


def test_tidy_scan_from_text_is_none_for_other_text(monkeypatch):
    monkeypatch.setattr(td, "resolve_folder", lambda key: pytest.fail("must not resolve"))
    assert td.tidy_scan_from_text("tidy my documents") is None
    assert td.tidy_scan_from_text("brief me") is None


def test_tidy_scan_from_text_reports_an_unknown_folder(monkeypatch):
    monkeypatch.setattr(td, "resolve_folder", lambda key: None)
    assert td.tidy_scan_from_text("tidy my desktop", now=NOW) == "I couldn't find your desktop folder."


# ---------------------------------------------------------------- guarantees

def test_the_module_has_no_way_to_move_rename_trash_or_delete():
    with open(os.path.join(ROOT, "commands", "tidy_downloads.py"), encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    banned = {"remove", "unlink", "rename", "replace", "rmdir", "removedirs", "move", "rmtree", "trash",
              "system", "popen", "run", "call", "check_call", "check_output", "Popen"}
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            called.add(node.attr)
        elif isinstance(node, ast.Name):
            called.add(node.id)
    assert not (banned & called), banned & called
    imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom)) for alias in getattr(node, "names", [])}
    assert "shutil" not in imported and "subprocess" not in imported and "socket" not in imported


def test_tidy_is_not_routed_before_the_api_or_the_bridge():
    for phrase in ("tidy my downloads", "tidy my desktop", "Tidy Downloads!"):
        assert route_before_api(phrase) is None, phrase
        assert bridge_allowed(phrase) is None, phrase


def test_the_tidy_action_is_not_bridged_and_not_in_zoe_mode():
    assert "tidy_scan" not in BRIDGE_ALLOW
    assert "tidy_scan" not in ZOE_ALLOW


def test_the_bridge_module_never_mentions_tidy():
    with open(os.path.join(ROOT, "commands", "bridge.py"), encoding="utf-8") as handle:
        assert "tidy" not in handle.read().lower()


def test_siri_hooks_tidy_after_the_route_and_maps_it_to_the_scan():
    with open(os.path.join(ROOT, "siri.py"), encoding="utf-8") as handle:
        source = handle.read()
    tree = ast.parse(source)
    decide = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "decide")
    text = ast.get_source_segment(source, decide)
    assert text.index("route_before_api(text)") < text.index("tidy_folder_key(text)")
    assert "tidy_scan" in text
    assert '"tidy_scan": lambda _arg, text: commands.tidy_scan_from_text(text)' in source


def test_the_commands_package_exports_the_tidy_entry_points():
    assert commands.tidy_folder_key("tidy my desktop") == "desktop"
    assert callable(commands.tidy_scan_from_text)
