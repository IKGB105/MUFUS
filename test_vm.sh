#!/bin/bash
# Prueba de instalación completa: bootea el USB real (solo lectura) en una VM
# UEFI y deja instalar Windows en un disco virtual nuevo, sin tocar hardware real.
set -e

USB_DEV="${1:-/dev/sdb}"
VM_DIR="$(dirname "$0")/vm-test"
VM_DISK="$VM_DIR/windows-test.qcow2"
USB_OVERLAY="$VM_DIR/usb-overlay.qcow2"
OVMF_CODE="/usr/share/edk2/x64/OVMF_CODE.4m.fd"
OVMF_VARS_TEMPLATE="/usr/share/edk2/x64/OVMF_VARS.4m.fd"
OVMF_VARS="$VM_DIR/OVMF_VARS.fd"

mkdir -p "$VM_DIR"

if [ ! -f "$VM_DISK" ]; then
    echo "Creando disco virtual de 40G para la instalación..."
    qemu-img create -f qcow2 "$VM_DISK" 40G
fi

if [ ! -f "$OVMF_VARS" ]; then
    cp "$OVMF_VARS_TEMPLATE" "$OVMF_VARS"
fi

echo "Dando acceso de lectura temporal a $USB_DEV para esta sesión..."
pkexec setfacl -m u:"$USER":r "$USB_DEV"

# Overlay qcow2 sobre el USB real: el firmware/Windows puede "escribir" sin
# problema (necesario para que UEFI no truene), pero esas escrituras caen
# aquí, nunca al dispositivo físico. Se recrea cada vez por si el USB físico
# cambió de nodo (/dev/sdX puede variar entre conexiones).
echo "Creando overlay de solo-lectura real sobre $USB_DEV..."
rm -f "$USB_OVERLAY"
qemu-img create -f qcow2 -b "$USB_DEV" -F raw "$USB_OVERLAY"

echo "Arrancando VM (UEFI real vía OVMF, USB protegido por overlay)..."
# Ambos discos van por AHCI/SATA (driver nativo de Windows Setup, sin
# necesitar drivers extra como con virtio) para que el instalador vea
# los DOS discos: el USB (de donde arranca) y el disco virtual (destino
# real de la instalación).
#
# El disco virtual tiene bootindex MÁS ALTO (1) que el USB (2) a propósito:
# la primera vez está vacío/sin bootloader, así que el firmware lo salta y
# cae al USB (arranca el instalador). Una vez que Setup instala el
# bootloader ahí, los siguientes reinicios ya encuentran algo booteable en
# el disco y arrancan eso en vez de volver a caer en el instalador del USB
# (evita el loop de "siempre vuelve al Setup" tras cada reinicio).
qemu-system-x86_64 \
    -enable-kvm \
    -machine q35,accel=kvm \
    -cpu host \
    -m 4096 \
    -smp 2 \
    -drive if=pflash,format=raw,readonly=on,file="$OVMF_CODE" \
    -drive if=pflash,format=raw,file="$OVMF_VARS" \
    -device ahci,id=ahci0 \
    -drive if=none,id=wintarget,file="$VM_DISK",format=qcow2 \
    -device ide-hd,drive=wintarget,bus=ahci0.0,bootindex=1 \
    -drive if=none,id=usbimg,file="$USB_OVERLAY",format=qcow2 \
    -device ide-hd,drive=usbimg,bus=ahci0.1,bootindex=2 \
    -vga virtio -display gtk \
    -audio driver=none
