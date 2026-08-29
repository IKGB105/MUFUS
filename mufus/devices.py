"""Enumerate removable USB disks safely (never returns the system disk)."""
import json
import subprocess
from dataclasses import dataclass


def unmount_all_partitions(device_path: str, log_cb=None) -> None:
    out = subprocess.run(
        ["lsblk", "-J", "-o", "NAME,MOUNTPOINT", device_path],
        capture_output=True, text=True,
    ).stdout
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return
    for node in data.get("blockdevices", []):
        for child in node.get("children", []) or []:
            if child.get("mountpoint"):
                part = f"/dev/{child['name']}"
                if log_cb:
                    log_cb(f"Desmontando {part}...")
                subprocess.run(["udisksctl", "unmount", "-b", part],
                                capture_output=True, text=True)


@dataclass
class Device:
    path: str          # e.g. /dev/sda
    size_bytes: int
    model: str
    mountpoints: list[str]

    @property
    def label(self) -> str:
        size_gb = self.size_bytes / (1000 ** 3)
        return f"{self.path} — {self.model or 'Unknown'} ({size_gb:.1f} GB)"


def _collect_mountpoints(node: dict) -> list[str]:
    mps = []
    mp = node.get("mountpoint")
    if mp:
        mps.append(mp)
    for child in node.get("children", []) or []:
        mps.extend(_collect_mountpoints(child))
    return mps


def list_removable_devices() -> list[Device]:
    out = subprocess.run(
        ["lsblk", "-J", "-b", "-o", "NAME,SIZE,TYPE,RM,TRAN,MODEL,MOUNTPOINT"],
        capture_output=True, text=True, check=True,
    ).stdout
    data = json.loads(out)

    devices = []
    for node in data.get("blockdevices", []):
        if node.get("type") != "disk":
            continue
        if not node.get("rm"):
            continue
        size = int(node.get("size") or 0)
        if size <= 0:
            continue  # empty card reader slot, etc.
        devices.append(Device(
            path=f"/dev/{node['name']}",
            size_bytes=size,
            model=(node.get("model") or "").strip(),
            mountpoints=_collect_mountpoints(node),
        ))
    return devices
