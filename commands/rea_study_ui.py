"""Mac dialogs reached only through explicit Quick Command clicks; no audio."""
import subprocess
import sys
import threading
import time
from pathlib import Path
from .rea_study import STUDY
from .nxnative_build_ui import dialog


def form(title='REA Research'):
    from AppKit import NSAlert, NSOpenPanel, NSPopUpButton, NSTextField, NSView
    apps = sorted({p for root in (Path('/Applications'), Path('~/Applications').expanduser())
                   if root.is_dir() for p in root.glob('*.app')}, key=lambda p: p.name.lower())
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_('Choose a target, then describe one feature to study.')
    alert.addButtonWithTitle_('Cancel')
    alert.addButtonWithTitle_('Start')
    view = NSView.alloc().initWithFrame_(((0, 0), (420, 95)))
    picker = NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 60), (420, 28)), False)
    picker.addItemsWithTitles_(['Choose any file or folder…'] + [str(p) for p in apps])
    field = NSTextField.alloc().initWithFrame_(((0, 10), (420, 28)))
    field.setPlaceholderString_('Feature to study')
    view.addSubview_(picker)
    view.addSubview_(field)
    alert.setAccessoryView_(view)
    if alert.runModal() != 1001:
        return None
    feature = str(field.stringValue()).strip()
    if not feature:
        raise ValueError('Enter a feature to study.')
    index = picker.indexOfSelectedItem()
    if index:
        target = apps[index - 1]
    else:
        panel = NSOpenPanel.openPanel()
        panel.setCanChooseFiles_(True)
        panel.setCanChooseDirectories_(True)
        panel.setAllowsMultipleSelection_(False)
        if panel.runModal() != 1:
            return None
        target = Path(str(panel.URL().path()))
    return target, feature


def pick_folder(title, root):
    from AppKit import NSOpenPanel
    from Foundation import NSURL
    panel = NSOpenPanel.openPanel()
    panel.setTitle_(title)
    panel.setDirectoryURL_(NSURL.fileURLWithPath_(str(root)))
    panel.setCanChooseFiles_(False)
    panel.setCanChooseDirectories_(True)
    panel.setAllowsMultipleSelection_(False)
    return Path(str(panel.URL().path())) if panel.runModal() == 1 else None


def builder_form():
    from AppKit import NSAlert, NSTextField
    from .rea_study import ROOT
    from .rea_handoff import load
    from .rea_builder import INBOX
    request = pick_folder('Choose REA request with spec/handoff.json', ROOT)
    if not request:
        return None
    load(request)
    alert = NSAlert.alloc().init()
    alert.setMessageText_('Send to Builder')
    for title in ('Cancel', 'NXNative', 'New App'):
        alert.addButtonWithTitle_(title)
    choice = alert.runModal()
    if choice == 1001:
        INBOX.mkdir(parents=True, exist_ok=True)
        game = pick_folder('Choose existing Switch game in Inbox', INBOX)
        return ('nxnative', request, game) if game else None
    if choice != 1002:
        return None
    alert = NSAlert.alloc().init()
    alert.setMessageText_('New App slug')
    field = NSTextField.alloc().initWithFrame_(((0, 0), (360, 28)))
    field.setPlaceholderString_('my-app')
    alert.setAccessoryView_(field)
    alert.addButtonWithTitle_('Cancel')
    alert.addButtonWithTitle_('Scaffold')
    return ('new_app', request, str(field.stringValue())) if alert.runModal() == 1001 else None


def click(ui, kind):
    import commands
    if sys.platform != 'darwin' or commands.zoe_mode_active():
        ui._show_bar_reply('REA studies are grown-up work on this Mac only.')
        return
    if kind == 'rea_cancel':
        ui._show_bar_reply(STUDY.cancel())
        return
    if STUDY.status():
        ui._show_bar_reply(STUDY.status())
        return
    try:
        request = None
        mode = {'rea_study': 'research', 'rea_research': 'research', 'rea_review': 'review', 'rea_replicate': 'replicate'}.get(kind)
        if kind == 'rea_send_builder':
            selection = builder_form()
        else:
            if mode is None:
                raise ValueError('Unknown REA command.')
            if mode == 'review':
                from .rea_study import ROOT
                request = pick_folder('Choose existing REA request', ROOT)
                if not request:
                    return
            selection = form('REA ' + {'research': 'Research', 'review': 'Review your own app or repo', 'replicate': 'Replicate Plan'}[mode])
        if not selection:
            return
        def work():
            def show(line):
                ui.performSelectorOnMainThread_withObject_waitUntilDone_('showBarSentence:', line, False)
            def done(result):
                ui.performSelectorOnMainThread_withObject_waitUntilDone_('reaStudyFinished:', result, False)
            try:
                if kind == 'rea_send_builder':
                    from .rea_builder import send_nxnative, start_new_app
                    builder, folder, value = selection
                    if builder == 'nxnative':
                        output = send_nxnative(folder, value, zoe=commands.zoe_mode_active())
                        done(dict(success=True, output=output, log=output, tail='', message='Spec copied. Next click Start NXNative Build.'))
                    else:
                        show(start_new_app(folder, value, done, zoe=commands.zoe_mode_active()))
                else:
                    show(STUDY.start(*selection, callback=done, zoe=commands.zoe_mode_active(), mode=mode, request=request))
            except Exception as exc:
                show('Cannot start REA: ' + str(exc))
            while STUDY.status():
                time.sleep(15)
                line = STUDY.status()
                if line:
                    show(line)
        threading.Thread(target=work, daemon=True).start()
    except Exception as exc:
        ui._show_bar_reply('Could not open REA study: {}'.format(exc))


def finished(ui, result):
    ui._show_bar_reply(result['message'])
    if result['success']:
        try:
            from Foundation import NSUserNotification, NSUserNotificationCenter
            note = NSUserNotification.alloc().init()
            note.setTitle_('Hey Jev REA')
            note.setInformativeText_(result['message'])
            NSUserNotificationCenter.defaultUserNotificationCenter().deliverNotification_(note)
        except Exception:
            pass
    try:
        yes, _ = dialog(result['message'], '' if result['success'] else result['tail'],
                        'Open Folder' if result['success'] else 'Open Log')
        if yes:
            subprocess.Popen(['open', str(result['output'] if result['success'] else result['log'])])
    except Exception:
        ui._show_bar_reply('Log: ' + str(result['log']))
