"""macOS Trash access and actionable errors."""
import errno
import os

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
        raise TrashAccessError(SOURCE_ACCESS)
    raise OSError(str(error.localizedDescription()) if error else 'Finder did not return a Trash location.')


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
