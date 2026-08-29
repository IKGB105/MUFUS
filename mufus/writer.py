"""Raw image writing + verification, privilege-separated via pkexec.

No custom polkit rule is installed: `pkexec dd ...` uses PolicyKit's generic
"run a command as another user" action, so the desktop's polkit agent will
just prompt for the user's password each time a write/verify starts.
"""
import hashlib
import os
import re
import subprocess
from dataclasses import dataclass

from . import devices as devices_mod

DD_PROGRESS_RE = re.compile(rb"(\d+) bytes")


class WriterError(Exception):
    pass


@dataclass
class Progress:
    done: int
    total: int

    @property
    def fraction(self) -> float:
        return 0.0 if self.total <= 0 else min(self.done / self.total, 1.0)


def sha256_file(path: str, chunk_size: int = 4 * 1024 * 1024, progress_cb=None) -> str:
    total = os.path.getsize(path)
    done = 0
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(Progress(done, total))
    return h.hexdigest()


def unmount_partitions(device: devices_mod.Device, log_cb=None) -> None:
    devices_mod.unmount_all_partitions(device.path, log_cb=log_cb)


def write_image(image_path: str, device_path: str, progress_cb=None, log_cb=None) -> None:
    total = os.path.getsize(image_path)
    cmd = [
        "pkexec", "dd",
        f"if={image_path}",
        f"of={device_path}",
        "bs=4M",
        "conv=fsync",
        "status=progress",
    ]
    if log_cb:
        log_cb(f"Writing {image_path} -> {device_path} ({total} bytes)")

    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    buf = b""
    while True:
        chunk = proc.stderr.read(4096)
        if not chunk:
            break
        buf += chunk
        while b"\r" in buf or b"\n" in buf:
            idx_r = buf.find(b"\r")
            idx_n = buf.find(b"\n")
            candidates = [i for i in (idx_r, idx_n) if i != -1]
            idx = min(candidates)
            line, buf = buf[:idx], buf[idx + 1:]
            m = DD_PROGRESS_RE.search(line)
            if m and progress_cb:
                progress_cb(Progress(int(m.group(1)), total))
            elif line.strip() and log_cb:
                log_cb(line.decode(errors="replace").strip())

    ret = proc.wait()
    if ret != 0:
        raise WriterError(f"dd exited with code {ret} (did you cancel the authentication, or did the disk fail?)")
    if progress_cb:
        progress_cb(Progress(total, total))


def verify_device(device_path: str, expected_size: int, expected_sha256: str, log_cb=None) -> bool:
    if log_cb:
        log_cb("Verifying (reading the device back)...")
    dd = subprocess.Popen(
        ["pkexec", "dd", f"if={device_path}", "bs=4M", "status=none"],
        stdout=subprocess.PIPE,
    )
    head = subprocess.Popen(
        ["head", "-c", str(expected_size)],
        stdin=dd.stdout, stdout=subprocess.PIPE,
    )
    dd.stdout.close()
    sha = subprocess.Popen(["sha256sum"], stdin=head.stdout, stdout=subprocess.PIPE, text=True)
    head.stdout.close()
    out, _ = sha.communicate()
    head.wait()
    dd.wait()  # dd exits non-zero on the broken pipe from `head` closing early; expected, ignored.

    if not out.strip():
        raise WriterError("Could not read the device to verify it.")
    digest = out.split()[0]
    if log_cb:
        log_cb(f"sha256 image:  {expected_sha256}")
        log_cb(f"sha256 device: {digest}")
    return digest == expected_sha256
