# MUFUS

**MUFUS is not RUFUS.**

A native Linux tool for writing bootable USB drives, built out of pure frustration.

## Why this exists

This exists because Balena Etcher kept failing to install cleanly on Linux, and Ventoy kept failing to flash a USB drive that actually worked. After enough of that, the answer was to just build a replacement instead of fighting with either one again.

MUFUS was written entirely by AI (Claude, via Claude Code) to solve that one specific, real problem. It is not a polished open-source project with a roadmap — it's a tool that exists because it had to, scoped to cover exactly what its author needed, and tested against real hardware and real ISOs until it actually worked. Expect it to be opinionated and minimal rather than feature-complete.

## What it does

MUFUS has two write modes:

- **DD Image** — direct clone (`dd`-style), for hybrid ISOs (most Linux distros: Manjaro, Ubuntu, Debian, Arch, etc.). Includes a sha256 verification pass after writing, comparing the source image against what actually landed on the device.
- **ISO Image** — extract-and-rebuild mode, for non-hybrid ISOs such as Windows installers (including community builds like Tiny10/Tiny11, which ship `install.esd` instead of `install.wim`). It partitions the target disk (MBR), formats a single FAT32 partition, and copies the ISO's contents onto it. This produces a drive that boots via **UEFI only** — see Limitations below.

Both modes:
- only ever list *removable* USB disks (via `lsblk`'s `RM` flag) — the system disk never shows up as a target
- show a destructive-action confirmation dialog naming the exact device and image before writing anything
- surface a toast + native desktop notification when a job finishes or fails

## Requirements

Tested on Manjaro/Arch. You need:

- `python-gobject`, `gtk4`, `libadwaita` (the GUI)
- `parted`, `dosfstools` (`mkfs.vfat`), `p7zip` (`7z`) (ISO mode: partitioning, formatting, extraction)
- `udisks2`, `polkit` (mounting, and the `pkexec` prompts for privileged operations)

If your `python3` is shadowed by pyenv/asdf/a venv without PyGObject, run it with the system interpreter — `run.sh` already does this via `/usr/bin/python3`.

## Usage

```
git clone https://github.com/IKGB105/MUFUS.git
cd MUFUS
./run.sh
```

Pick an image, pick a mode, pick your USB drive, confirm, done. You'll get a `pkexec` password prompt for the actual disk-level operations (partitioning, formatting, raw writes).

### Testing an install before touching real hardware

`test_vm.sh` boots a real USB stick inside a QEMU/OVMF (real UEFI firmware) virtual machine, so you can run a full Windows installer end-to-end without risking your actual laptop. It protects the physical device with a copy-on-write overlay — nothing the guest OS does can ever write back to the real USB.

```
./test_vm.sh /dev/sdX
```

## Known limitations

- **UEFI only.** ISO mode does not install a BIOS/legacy bootloader (that would mean chainloading into `bootmgr` via GRUB's `ntldr` module, which needed more validation than this project's scope justified). If your target machine is UEFI-capable — true for basically anything from the last ~12 years — you're fine.
- **No persistence mode** for Linux live USBs (Ventoy-style persistent storage) yet.
- **No bad-blocks scan** yet.
- Only really exercised against Manjaro (DD mode) and a Tiny10 (Windows 10 LTSC-based) ISO (ISO mode). Other distros/Windows builds should work the same way but haven't all been individually verified.

## Validation

This isn't theoretical — both modes were tested against real usage:

- **DD mode**: wrote a Manjaro live ISO to a real USB stick and booted it on real hardware.
- **ISO mode**: wrote a Tiny10 ISO to a real USB stick, booted it via real UEFI firmware (QEMU + OVMF), and completed a full Windows installation through to first boot.

## License

MIT — see [LICENSE](LICENSE).
