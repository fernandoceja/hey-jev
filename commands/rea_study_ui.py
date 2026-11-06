"""Mac dialogs reached only through explicit Quick Command clicks; no audio."""
import subprocess
import sys
import threading
import time
from pathlib import Path
from .rea_study import STUDY
from .nxnative_build_ui import dialog


def form(title='REA Research', target=None, feature='', confirm=False):
    from AppKit import NSAlert, NSOpenPanel, NSPopUpButton, NSTextField, NSView
    apps = sorted({p for root in (Path('/Applications'), Path('~/Applications').expanduser())
                   if root.is_dir() for p in root.glob('*.app')}, key=lambda p: p.name.lower())
    if target is not None and target not in apps:
        apps.insert(0, Path(target))
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_('Choose a target, then describe one feature to study.')
    alert.addButtonWithTitle_('Cancel')
    alert.addButtonWithTitle_('Save' if confirm else 'Start')
    view = NSView.alloc().initWithFrame_(((0, 0), (420, 95)))
    picker = NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 60), (420, 28)), False)
    picker.addItemsWithTitles_(['Choose any file or folder…'] + [str(p) for p in apps])
    field = NSTextField.alloc().initWithFrame_(((0, 10), (420, 28)))
    field.setPlaceholderString_('Feature to study')
    field.setStringValue_(feature)
    if target in apps:
        picker.selectItemAtIndex_(apps.index(target) + 1)
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
    elif confirm:
        target = None
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
    for title in ('Cancel', 'NXNative', 'New App', 'Existing Repo'):
        alert.addButtonWithTitle_(title)
    choice = alert.runModal()
    if choice == 1001:
        INBOX.mkdir(parents=True, exist_ok=True)
        game = pick_folder('Choose existing Switch game in Inbox', INBOX)
        return ('nxnative', request, game) if game else None
    if choice == 1003:
        repo = repo_picker()
        slug = text_prompt('Existing Repo: new branch slug') if repo else None
        return ('existing', request, (repo, slug)) if slug else None
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


def click(ui, kind, prefill=None, *, wishlist_authorized=False):
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
        if kind == 'rea_wishlist':
            return wishlist_list(ui)
        if kind == 'rea_add_wishlist':
            return wishlist_add(prefill)
        request = None
        mode = {'rea_study': 'research', 'rea_research': 'research', 'rea_review': 'review', 'rea_replicate': 'replicate'}.get(kind)
        if kind == 'rea_send_builder':
            selection = builder_form()
        else:
            if mode is None:
                raise ValueError('Unknown REA command.')
            if mode == 'review':
                choice = review_choice()
                if choice is None:
                    return
                if choice == 'prior':
                    from .rea_study import ROOT
                    request = pick_folder('Choose existing REA request with spec or findings/build plan', ROOT)
                    if not request:
                        return
                    selection = form('REA Review against earlier study/spec')
                else:
                    target = repo_picker()
                    if not target:
                        return
                    selection = form('REA Review last change', target=target, feature='Review last change')
            else:
                values = {k: v for k, v in (prefill or {}).items() if k in ('target', 'feature')}
                target = values.get('target')
                if (wishlist_authorized and mode == 'replicate' and target is not None
                        and Path(target).exists() and values.get('feature', '').strip()):
                    selection = (target, values['feature'])
                else:
                    selection = form('REA ' + {'research': 'Research', 'replicate': 'Replicate Plan'}[mode], **values)
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
                    elif builder == 'existing':
                        from .rea_existing import start
                        show(start(folder, *value, done, zoe=commands.zoe_mode_active()))
                    else:
                        show(start_new_app(folder, value, done, zoe=commands.zoe_mode_active()))
                else:
                    with STUDY.lock:
                        line = STUDY.start(*selection, callback=done, zoe=commands.zoe_mode_active(), mode=mode, request=request)
                        if prefill and prefill.get('wishlist_id') and STUDY.active and not line.startswith('Cannot'):
                            from .rea_workflows import Wishlist
                            Wishlist().change('update', prefill['wishlist_id'], status='planned', request_folder=str(STUDY.active['output']))
                    show(line)
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
    if result.get('mode') == 'existing_builder':
        return existing_finished(ui, result)
    try:
        yes, _ = dialog(result['message'], '' if result['success'] else result['tail'],
                        'Open Folder' if result['success'] else 'Open Log')
        if yes:
            subprocess.Popen(['open', str(result['output'] if result['success'] else result['log'])])
    except Exception:
        ui._show_bar_reply('Log: ' + str(result['log']))


def text_prompt(title):
    from AppKit import NSAlert, NSTextField
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    field = NSTextField.alloc().initWithFrame_(((0, 0), (420, 28)))
    alert.setAccessoryView_(field)
    alert.addButtonWithTitle_('Cancel')
    alert.addButtonWithTitle_('Continue')
    return str(field.stringValue()).strip() if alert.runModal() == 1001 else None


def repo_picker():
    from AppKit import NSAlert, NSPopUpButton
    from .rea_workflows import presets
    rows = presets()
    alert = NSAlert.alloc().init()
    alert.setMessageText_('Choose your repository')
    picker = NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 0), (420, 28)), False)
    picker.addItemsWithTitles_([r[0] for r in rows] + ['Other…'])
    alert.setAccessoryView_(picker)
    alert.addButtonWithTitle_('Cancel')
    alert.addButtonWithTitle_('Choose')
    if alert.runModal() != 1001:
        return None
    index = picker.indexOfSelectedItem()
    return rows[index][1] if index < len(rows) else pick_folder('Choose repository', Path('~/Developer').expanduser())


def review_choice():
    from AppKit import NSAlert
    alert = NSAlert.alloc().init()
    alert.setMessageText_('REA Review')
    for title in ('Cancel', 'Review against earlier study/spec', 'Review last change'):
        alert.addButtonWithTitle_(title)
    return {1001: 'prior', 1002: 'last'}.get(alert.runModal())


def wishlist_form(prefill):
    from AppKit import NSAlert, NSTextField, NSView
    alert = NSAlert.alloc().init()
    alert.setMessageText_('Add to REA Wishlist')
    alert.setInformativeText_('Enter a feature, source app name or path, and optional notes.')
    view = NSView.alloc().initWithFrame_(((0, 0), (420, 130)))
    fields = []
    for y, placeholder, value in (
            (90, 'Feature', prefill.get('feature', '')),
            (50, 'Source app name or path', str(prefill.get('target') or prefill.get('app', ''))),
            (10, 'Notes (optional)', prefill.get('notes', ''))):
        field = NSTextField.alloc().initWithFrame_(((0, y), (420, 28)))
        field.setPlaceholderString_(placeholder)
        field.setStringValue_(value)
        view.addSubview_(field)
        fields.append(field)
    alert.setAccessoryView_(view)
    alert.addButtonWithTitle_('Cancel')
    alert.addButtonWithTitle_('Save')
    if alert.runModal() != 1001:
        return None
    feature, source_app, notes = (str(f.stringValue()).strip() for f in fields)
    if not feature:
        raise ValueError('Enter a feature.')
    return dict(feature=feature, source_app=source_app, notes=notes)


def wishlist_add(prefill=None):
    from .rea_workflows import Wishlist
    value = wishlist_form(prefill or {})
    if value:
        Wishlist().change('add', **value)


def wishlist_list(ui):
    from AppKit import NSAlert, NSPopUpButton
    from .rea_workflows import Wishlist, resolve_app
    store = Wishlist()
    rows = store.read()
    if not rows:
        ui._show_bar_reply('REA wishlist is empty.')
        return
    alert = NSAlert.alloc().init()
    alert.setMessageText_('REA Wishlist')
    picker = NSPopUpButton.alloc().initWithFrame_pullsDown_(((0, 0), (520, 28)), False)
    picker.addItemsWithTitles_([r['feature'] + ' — ' + r['source_app'] + ' (' + r['status'] + ')' for r in rows])
    alert.setAccessoryView_(picker)
    for title in ('Cancel', 'Replicate Plan', 'Mark Built', 'Remove'):
        alert.addButtonWithTitle_(title)
    choice = alert.runModal()
    row = rows[picker.indexOfSelectedItem()]
    if choice == 1001:
        source = Path(row['source_app']).expanduser()
        target = source if source.is_absolute() and source.exists() else resolve_app(source.stem)
        click(ui, 'rea_replicate', dict(target=target, feature=row['feature'], wishlist_id=row['id']), wishlist_authorized=True)
    elif choice == 1002:
        store.change('update', row['id'], status='built')
    elif choice == 1003 and confirm_action('Remove wishlist entry?'):
        store.change('remove', row['id'])


def confirm_action(title):
    from AppKit import NSAlert
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.addButtonWithTitle_('Cancel')
    alert.addButtonWithTitle_('Confirm')
    return alert.runModal() == 1001


def kickoff(ui, text):
    import commands
    from .rea_workflows import intent, resolve_app
    parsed = intent(text)
    if not parsed:
        return False
    if sys.platform != 'darwin' or commands.zoe_mode_active():
        ui._show_bar_reply('REA is grown-up work on this Mac only.')
        return True
    parsed['target'] = resolve_app(parsed['app'])
    kind = {'research': 'rea_research', 'replicate': 'rea_replicate', 'wishlist': 'rea_add_wishlist'}[parsed['mode']]
    ui._show_bar_reply('REA form ready. Confirm with a click.')
    click(ui, kind, parsed)
    return True


def existing_finished(ui, result):
    from AppKit import NSAlert
    import commands
    alert = NSAlert.alloc().init()
    alert.setMessageText_(result['message'])
    for title in ('Close', 'Open Folder', 'Show Diff', 'Push & Open PR', 'Discard Worktree'):
        alert.addButtonWithTitle_(title)
    choice = alert.runModal()
    try:
        from .rea_existing import push, discard, validate_live
        from .rea_workflows import git
        if commands.zoe_mode_active() or sys.platform != 'darwin':
            raise ValueError('REA requires this Mac outside Zoe mode.')
        if choice == 1001:
            subprocess.Popen(['open', str(result['output'])])
            return existing_finished(ui, result)
        elif choice == 1002:
            path = validate_live(result)
            ui._present_result('REA Diff', git(path, 'diff', 'origin/' + result['default'], '--stat') + '\n' + git(path, 'diff', 'origin/' + result['default']), False)
            return existing_finished(ui, result)
        elif choice == 1003 and result['success']:
            url = push(result, zoe=commands.zoe_mode_active())
            subprocess.Popen(['open', url])
        elif choice == 1004 and confirm_action('Discard this clean, unpushed REA worktree and local branch?'):
            discard(result, zoe=commands.zoe_mode_active())
    except Exception as exc:
        ui._show_bar_reply('REA: ' + str(exc))
