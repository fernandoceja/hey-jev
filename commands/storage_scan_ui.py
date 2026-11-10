"""Click-only storage card embedded in the existing resizable chat window."""
from .cleanup_gate import CleanupGate
from .storage_scan import ScanTask
from .cleanup_view import SECTIONS, scan_home, sections

_CONTROLLER = None


def start(ui):
    global _CONTROLLER
    from . import zoe_mode_active
    if zoe_mode_active():
        return
    import objc
    from Foundation import NSObject
    from AppKit import NSButton, NSScrollView, NSView, NSTextField, NSMakeRect
    from PyObjCTools.AppHelper import callAfter
    if _CONTROLLER is None:
        class StorageCard(NSObject):
            @objc.python_method
            def build(self, host):
                self.host = host
                self.home = scan_home()
                self.gate = CleanupGate(home=self.home)
                self.show_protected = False
                self.card = None
                self.moves = []
                self.rows = []
                self.checks = []
                self.closed = False
                self.scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 300))
                self.scroll.setHasVerticalScroller_(True)
                self.doc = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, 400, 300))
                self.scroll.setDocumentView_(self.doc)
                host.full_root.addSubview_(self.scroll)
                self.render('Scanning storage… Read only.')
                self.task = ScanTask(lambda rows, free, error: callAfter(self.finished, rows, free, error), home=self.home)

            @objc.python_method
            def label(self, text, y, width):
                field = NSTextField.labelWithString_(text)
                field.setFrame_(NSMakeRect(12, y, width - 24, 42))
                self.doc.addSubview_(field)

            @objc.python_method
            def button(self, title, action, x, y, width):
                button = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, width, 30))
                button.setTitle_(title)
                button.setTarget_(self)
                button.setAction_(action)
                self.doc.addSubview_(button)
                return button

            @objc.python_method
            def layout(self):
                size = self.host.full_root.bounds().size
                self.scroll.setFrame_(NSMakeRect(212, 100, max(300, size.width - 224), max(180, size.height - 145)))

            @objc.python_method
            def render(self, message):
                self.message = message
                for view in list(self.doc.subviews()):
                    view.removeFromSuperview()
                self.layout()
                width = self.scroll.bounds().size.width - 18
                grouped = sections(self.rows)
                visible = {key: entries for key, entries in grouped.items()
                           if key not in ('left_alone', 'fernando') or self.show_protected}
                height = max(220, 160 + 42 * len(visible) + 92 * sum(map(len, visible.values())))
                self.doc.setFrame_(NSMakeRect(0, 0, width, height))
                self.label(message, height - 48, width)
                self.checks = []
                y = height - 88
                for key, entries in visible.items():
                    total = sum(row.size for _, row in entries)
                    self.label(f'{SECTIONS[key]} · {len(entries)} · {total / 1048576:.1f} MB', y, width)
                    y -= 42
                    for index, row in entries:
                        check = self.button(f'{row.category} · {row.size / 1048576:.1f} MB', 'toggle:', 10, y, width - 20)
                        check.setButtonType_(3)
                        check.setEnabled_(row.deletable and key in ('safe', 'your_call', 'apps'))
                        check.setState_(int(key == 'safe' and row.deletable))
                        self.checks.append((index, check))
                        self.label(f'{row.path}\n{row.reason}', y - 45, width)
                        y -= 92
                if self.rows:
                    self.button('Hide protected rows' if self.show_protected else 'Show protected rows',
                                'protected:', 10, 48, 190)
                if self.card:
                    self.button('Move selected to Trash', 'approve:', 10, 10, 220)
                elif self.moves:
                    self.button('Undo', 'undo:', 10, 10, 90)
                self.button('Cancel' if not self.moves else 'Close', 'cancel:', 235, 10, 90)

            def protected_(self, sender):
                self.show_protected = not self.show_protected
                self.render(self.message)

            def toggle_(self, sender):
                pass

            @objc.python_method
            def finished(self, rows, free, error):
                if self.closed:
                    return
                self.rows = rows
                self.card = self.gate.present(rows) if not error else None
                self.render(error or ('Storage scan — Free space: ' + ('{:.1f} GB'.format(free / 1e9) if free is not None else 'unavailable')))

            def approve_(self, sender):
                selected = [i for i, c in self.checks if c.state() and c.isEnabled()]
                # Safety traversal and filesystem operations stay off the UI thread.
                for view in self.doc.subviews():
                    if hasattr(view, 'setEnabled_'):
                        view.setEnabled_(False)
                import threading
                def work():
                    try:
                        token = self.gate.approve_click(self.card, selected)
                        results = self.gate.execute(token)
                        moves = [r for r in results if r in self.gate.moves]
                        message = '{} moved to Trash. {}'.format(len(moves), '; '.join(r for r in results if r not in moves))
                        callAfter(self.completed, moves, message)
                    except Exception as exc:
                        callAfter(self.failed, str(exc))
                threading.Thread(target=work, daemon=True).start()

            @objc.python_method
            def failed(self, message):
                if not self.closed:
                    self.render(message)

            @objc.python_method
            def completed(self, moves, message):
                self.moves = moves
                self.card = None
                self.rows = []
                if not self.closed:
                    self.render(message)

            def undo_(self, sender):
                import threading
                def work():
                    try:
                        for move in list(self.moves):
                            self.gate.undo(move)
                            self.moves.remove(move)
                        callAfter(self.completed, [], 'Restored to original locations.')
                    except Exception as exc:
                        callAfter(self.failed, str(exc))
                threading.Thread(target=work, daemon=True).start()

            def cancel_(self, sender):
                self.closed = True
                self.task.cancel.set()
                if self.card:
                    self.gate.cancel(self.card)
                self.scroll.removeFromSuperview()
                self.host._storage_card = None
        _CONTROLLER = StorageCard
    previous = getattr(ui, '_storage_card', None)
    if previous:
        previous.cancel_(None)
    ui._show_full_window()
    controller = _CONTROLLER.alloc().init()
    ui._storage_card = controller
    controller.build(ui)
