"""Main-thread Mac dialogs; imported only by explicit Quick Command clicks."""
import subprocess
import sys
import threading
import time
from .nxnative_build import BUILD


def dialog(title, text, action, games=None):
    from AppKit import NSAlert, NSPopUpButton
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(text)
    alert.addButtonWithTitle_('Close')
    picker = None
    if games:
        picker = NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 0), (360, 28)), False)
        picker.addItemsWithTitles_([g.name for g in games])
        alert.setAccessoryView_(picker)
    if action:
        alert.addButtonWithTitle_(action)
    return alert.runModal() == 1001, picker.indexOfSelectedItem() if picker else 0


def click(ui, kind):
    import commands
    if sys.platform != 'darwin' or commands.zoe_mode_active():
        ui._show_bar_reply('NXNative builds are grown-up work on this Mac only.')
        return
    if kind == 'nx_cancel':
        ui._show_bar_reply(BUILD.cancel())
        return
    if BUILD.status():
        ui._show_bar_reply(BUILD.status())
        return
    try:
        games = BUILD.discover()
        if not games:
            yes, _ = dialog('No Inbox games', 'Drop a game folder with NSP/XCI files into ' + str(BUILD.root / 'Inbox'), 'Open Inbox in Finder')
            if yes:
                subprocess.Popen(['open', str(BUILD.root / 'Inbox')])
            return
        yes, index = dialog('Start NXNative Build',
                            'Confirm a game. First build: 30–60 minutes. Later builds reuse cached steps.',
                            'Start Build', games)
        if not yes:
            return
        def work():
            def show(line):
                ui.performSelectorOnMainThread_withObject_waitUntilDone_('showBarSentence:', line, False)
            def done(result):
                ui.performSelectorOnMainThread_withObject_waitUntilDone_('nxBuildFinished:', result, False)
            show(BUILD.start(games[index], done, zoe=commands.zoe_mode_active()))
            while BUILD.status():
                time.sleep(15)
                line = BUILD.status()
                if line:
                    show(line)
        threading.Thread(target=work, daemon=True).start()
    except Exception:
        ui._show_bar_reply('Could not open the NXNative picker. Check Inbox permissions.')


def finished(ui, result):
    ui._show_bar_reply(result['message'])
    if result['success']:
        try:
            from Foundation import NSUserNotification, NSUserNotificationCenter
            note = NSUserNotification.alloc().init()
            note.setTitle_('Hey Jev NXNative')
            note.setInformativeText_(result['message'])
            NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(note)
        except Exception:
            pass
    action = 'Show in Finder' if result['success'] else 'Ask Claude Code to fix'
    try:
        yes, _ = dialog(result['message'], '' if result['success'] else result['tail'],
                        None if result['cancelled'] else action)
        if yes:
            if result['success']:
                subprocess.Popen(['open', str(result['output'])])
            else:
                ui._show_bar_reply(BUILD.fix_prompt(result))
    except Exception:
        ui._show_bar_reply('Could not open the result action. Log: ' + str(result['log']))
