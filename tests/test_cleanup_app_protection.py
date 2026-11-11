import plistlib
import threading

import pytest

from commands.cleanup_apps import unused_apps
from commands.cleanup_gate import CleanupGate, Proposal
from commands.cleanup_rules import CLAUDE_HANDLER_ID, CLAUDE_HANDLER_PATH


@pytest.mark.parametrize('relative', [CLAUDE_HANDLER_PATH, 'Applications/Renamed.app'])
def test_handler_is_report_only_and_cannot_be_approved(tmp_path, relative):
    app = tmp_path / relative
    info = app / 'Contents/Info.plist'
    info.parent.mkdir(parents=True)
    if relative != CLAUDE_HANDLER_PATH:
        info.write_bytes(plistlib.dumps({'CFBundleIdentifier': CLAUDE_HANDLER_ID}))

    rows = list(unused_apps(tmp_path, [app.parent], lambda _: pytest.fail('protected measurement'),
                            threading.Event()))
    assert len(rows) == 1 and not rows[0].deletable
    assert rows[0].bucket == 'fernando'
    gate = CleanupGate(home=tmp_path, protected_roots=(), trash=lambda _: pytest.fail('protected move'))
    for row in (rows[0], Proposal(str(app), 1, app.stem, '', 'safe')):
        card = gate.present([row])
        with pytest.raises(ValueError, match='protected path'):
            gate.approve_click(card, [0], skip_refused=True)
        assert gate.refusal(row) == 'protected path'
