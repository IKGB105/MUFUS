"""ISO Image mode: extract + rebuild a FAT32 USB, UEFI-boot only.

Windows installer ISOs are not hybrid images (no MBR/partition table), so a
raw dd write won't produce a reliably bootable disk. Instead we partition
the disk ourselves, format a single FAT32 partition, and copy the ISO's
files onto it. UEFI firmware finds efi/boot/bootx64.efi on that FAT32
partition on its own -- no bootloader installation needed. (BIOS legacy
boot is intentionally not supported: it would require chainloading into
bootmgr via GRUB's ntldr module, which needs real-hardware validation
before shipping.)
"""
import os
import re
import subprocess
import tempfile
import time

from . import devices as devices_mod
from .writer import WriterError, Progress


def _run_privileged(cmd: list[str], log_cb=None) -> subprocess.CompletedProcess:
    if log_cb:
        log_cb("$ " + " ".join(cmd))
    proc = subprocess.run(["pkexec"] + cmd, capture_output=True, text=True)
    if proc.stdout and log_cb:
        log_cb(proc.stdout.strip())
    if proc.returncode != 0:
        raise WriterError(f"'{' '.join(cmd)}' failed: {proc.stderr.strip() or proc.returncode}")
    return proc


def sanitize_fat_label(name: str) -> str:
    label = re.sub(r"[^A-Za-z0-9_]", "", name).upper()
    return (label or "USB")[:11]


def partition_device_path(device_path: str, index: int = 1) -> str:
    if re.search(r"\d$", device_path):  # e.g. /dev/nvme0n1, /dev/mmcblk0
        return f"{device_path}p{index}"
    return f"{device_path}{index}"


def partition_and_format(device_path: str, label: str, log_cb=None) -> str:
    """Wipe the disk and create a single bootable FAT32 partition.

    Returns the resulting partition's device path (e.g. /dev/sdb1).
    """
    devices_mod.unmount_all_partitions(device_path, log_cb=log_cb)

    if log_cb:
        log_cb(f"Partitioning {device_path} (MBR, FAT32, UEFI boot)...")
    _run_privileged(["parted", "--script", device_path, "mklabel", "msdos"], log_cb)
    _run_privileged(["parted", "--script", device_path, "mkpart", "primary", "fat32", "1MiB", "100%"], log_cb)
    _run_privileged(["parted", "--script", device_path, "set", "1", "boot", "on"], log_cb)
    subprocess.run(["partprobe", device_path], capture_output=True)

    part_path = partition_device_path(device_path)
    for _ in range(40):
        if os.path.exists(part_path):
            break
        time.sleep(0.25)
    else:
        raise WriterError(f"The kernel didn't expose partition {part_path} after partitioning.")

    if log_cb:
        log_cb(f'Formatting {part_path} as FAT32 ("{label}")...')
    _run_privileged(["mkfs.vfat", "-F", "32", "-n", label, part_path], log_cb)
    subprocess.run(["udevadm", "settle"], capture_output=True)
    return part_path


def extract_iso(iso_path: str, dest_dir: str, log_cb=None) -> None:
    if log_cb:
        log_cb(f"Extracting {iso_path}...")
    proc = subprocess.run(["7z", "x", f"-o{dest_dir}", "-y", iso_path],
                           capture_output=True, text=True)
    if proc.returncode != 0:
        raise WriterError(f"Could not extract the ISO: {proc.stderr.strip() or proc.stdout.strip()}")


def mount_partition(part_path: str, log_cb=None) -> str:
    last_err = ""
    for attempt in range(10):
        proc = subprocess.run(["udisksctl", "mount", "-b", part_path],
                               capture_output=True, text=True)
        if proc.returncode == 0:
            m = re.search(r"at (/\S+)", proc.stdout)
            if m:
                return m.group(1)
            last_err = f"Unexpected udisksctl mount response: {proc.stdout}"
        else:
            last_err = proc.stderr.strip()
        if attempt == 0 and log_cb:
            log_cb("udisks2 doesn't recognize the filesystem yet, retrying...")
        subprocess.run(["udevadm", "settle"], capture_output=True)
        time.sleep(0.5)
    raise WriterError(f"Could not mount {part_path} after several attempts: {last_err}")


def unmount_partition(part_path: str) -> None:
    subprocess.run(["udisksctl", "unmount", "-b", part_path], capture_output=True, text=True)


def _iter_files(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            full = os.path.join(dirpath, fn)
            yield full, os.path.relpath(full, root)


def copy_tree_with_progress(src_dir: str, dst_dir: str, progress_cb=None, log_cb=None) -> None:
    files = list(_iter_files(src_dir))
    total = sum(os.path.getsize(full) for full, _rel in files)

    done = 0
    for full, rel in files:
        dst_path = os.path.join(dst_dir, rel)
        os.makedirs(os.path.dirname(dst_path), exist_ok=True)
        with open(full, "rb") as fsrc, open(dst_path, "wb") as fdst:
            while True:
                chunk = fsrc.read(4 * 1024 * 1024)
                if not chunk:
                    break
                fdst.write(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(Progress(done, total))
    if log_cb:
        log_cb(f"Copied {len(files)} files ({total / 1e9:.2f} GB).")


def write_iso_image(iso_path: str, device_path: str, volume_label: str,
                     progress_cb=None, log_cb=None) -> None:
    label = sanitize_fat_label(volume_label)
    with tempfile.TemporaryDirectory(prefix="mufus-iso-") as tmpdir:
        extract_iso(iso_path, tmpdir, log_cb=log_cb)
        part_path = partition_and_format(device_path, label, log_cb=log_cb)
        mountpoint = mount_partition(part_path, log_cb=log_cb)
        try:
            if log_cb:
                log_cb(f"Copying files to {mountpoint}...")
            copy_tree_with_progress(tmpdir, mountpoint, progress_cb=progress_cb, log_cb=log_cb)
            subprocess.run(["sync"])
        finally:
            unmount_partition(part_path)
