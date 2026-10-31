"""Bounded subprocesses. No shell, unlimited buffers, or model-supplied commands."""
from dataclasses import dataclass
import os
import signal
import subprocess
import threading
import time
from .errors import FactoryError


@dataclass
class ProcessResult:
    stdout: str
    stderr: str
    returncode: int
    elapsed: float


class ProcessFailure(FactoryError):
    def __init__(self, reason, stdout, stderr):
        super().__init__(reason)
        self.stdout, self.stderr = stdout, stderr


def kill_tree(process):
    if os.name == 'nt':
        try:
            subprocess.run([os.path.join(os.environ.get('SYSTEMROOT', r'C:\Windows'), 'System32', 'taskkill.exe'),
                            '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            if process.poll() is None:
                process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def run(argv, *, stdin='', cwd=None, timeout=60, max_bytes=1048576, env=None):
    if not isinstance(argv, list) or not argv or any(not isinstance(v, str) or '\x00' in v for v in argv):
        raise FactoryError('Invalid subprocess argument array')
    start = time.monotonic()
    options = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
    try:
        process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=cwd, env=env, shell=False, **options)
    except OSError as exc:
        raise FactoryError('Unable to launch configured executable') from exc
    chunks = [bytearray(), bytearray()]
    total = 0
    lock = threading.Lock()
    exceeded = threading.Event()
    def reader(stream, index):
        nonlocal total
        try:
            while data := stream.read(4096):
                with lock:
                    total += len(data)
                    if total > max_bytes:
                        exceeded.set()
                    else:
                        chunks[index].extend(data)
        finally:
            stream.close()
    def writer():
        try:
            process.stdin.write(stdin.encode('utf-8'))
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            process.stdin.close()
    threads = [threading.Thread(target=reader, args=(process.stdout, 0), daemon=True),
               threading.Thread(target=reader, args=(process.stderr, 1), daemon=True),
               threading.Thread(target=writer, daemon=True)]
    for thread in threads:
        thread.start()
    reason = None
    try:
        while process.poll() is None or any(t.is_alive() for t in threads[:2]):
            if exceeded.is_set():
                reason = 'Subprocess output limit exceeded'
                break
            if time.monotonic() - start > timeout:
                reason = 'Subprocess timeout exceeded'
                break
            time.sleep(.02)
    finally:
        if reason or process.poll() is None:
            kill_tree(process)
        process.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=2)
    if exceeded.is_set():
        reason = 'Subprocess output limit exceeded'
    if reason:
        raise ProcessFailure(reason, *(bytes(b).decode('utf-8', errors='replace') for b in chunks))
    return ProcessResult(*(bytes(b).decode('utf-8', errors='replace') for b in chunks),
                         process.returncode, time.monotonic() - start)
