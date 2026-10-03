"""Run a command from an argument list. Never a shell string."""
import subprocess

def _run(args, timeout=30):
    """Run a command from an argument list. Never passes a shell string."""
    result = subprocess.run(list(args), capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or "command failed").strip())
    return result.stdout
