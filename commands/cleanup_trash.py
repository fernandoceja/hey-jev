"""macOS Trash access and actionable errors."""
import errno
import os
import stat
from pathlib import Path

FULL_DISK_ACCESS = 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'
FILES_AND_FOLDERS = 'x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders'
TRASH_ACCESS = 'Grant access in System Settings → Privacy & Security → Full Disk Access to let Jev read the Trash.'
SOURCE_ACCESS = 'Grant access in System Settings → Privacy & Security → Files and Folders to let Jev access this folder.'


class TrashAccessError(PermissionError):
    pass


def denied(error):
    while error is not None:
        domain, code = str(error.domain()), error.code()
        if (domain == 'NSPOSIXErrorDomain' and code in (errno.EPERM, errno.EACCES)
                or domain == 'NSCocoaErrorDomain' and code in (257, 513)):
            return True
        error = error.userInfo().get('NSUnderlyingError')
    return False


def recycle_result(destinations, source, error):
    destination = destinations.get(source) if destinations else None
    if destination is not None:
        return str(destination.path())
    if denied(error):
        raise TrashAccessError(SOURCE_ACCESS + ' ' + str(error.localizedDescription()))
    raise OSError(str(error.localizedDescription()) if error else 'Finder did not return a Trash location.')


def recycle_with_fallback(path, finder, foundation):
    """Retry only an explicit denial for the same source item."""
    original = os.lstat(path)
    try:
        return finder(path)
    except TrashAccessError as finder_error:
        try:
            if not os.path.samestat(original, os.lstat(path)):
                raise OSError('The source changed during the Trash move.')
        except FileNotFoundError:
            raise finder_error
        try:
            return foundation(path)
        except TrashAccessError as direct_error:
            if not os.path.samestat(original, os.lstat(path)):
                raise OSError('The source changed during the Trash move.')
            trash = Path.home() / '.Trash'
            try:
                with os.scandir(trash):
                    pass
            except PermissionError:
                raise TrashAccessError(TRASH_ACCESS) from direct_error
            return move_into_home_trash(path, trash)


def move_into_home_trash(path, trash):
    """Move into an existing, user-owned Trash without overwriting any entry."""
    import ctypes
    import uuid

    source = Path(path)
    info = trash.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or source.lstat().st_dev != info.st_dev):
        raise OSError('The existing home Trash is not suitable for a local move.')

    rename = ctypes.CDLL(None, use_errno=True).renamex_np
    rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    rename_excl = 0x00000004
    destination = trash / source.name
    for _ in range(2):
        if rename(os.fsencode(source), os.fsencode(destination), rename_excl) == 0:
            return str(destination)
        code = ctypes.get_errno()
        if code != errno.EEXIST:
            raise OSError(code, os.strerror(code), str(source), str(destination))
        destination = trash / ('Jev-' + uuid.uuid4().hex + source.suffix)
    raise FileExistsError('Could not reserve a unique Trash destination.')


def summary(trash, measure):
    try:
        with os.scandir(trash) as entries:
            count = sum(1 for _ in entries)
    except FileNotFoundError:
        return '0 items in home Trash · 0.0 MB', False
    except PermissionError:
        return TRASH_ACCESS, True
    except OSError as error:
        return f'Could not read Trash: {error.strerror}', False
    size, partial = measure(trash)
    if partial:
        return f'{count} items in home Trash · {size / 1048576:.1f} MB measured (partial). {TRASH_ACCESS}', True
    return f'{count} items in home Trash · {size / 1048576:.1f} MB', False
