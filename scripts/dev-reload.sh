#!/bin/sh
# Build the module from this tree and swap it into the running kernel
# without touching the DKMS install. Run as root. The wheel is re-probed
# automatically by the HID core when the module registers.
set -e
cd "$(dirname "$0")/.."
make
rmmod hid-logitech-new 2>/dev/null || rmmod hid_logitech_new 2>/dev/null || true
rmmod hid-logitech 2>/dev/null || true
insmod ./hid-logitech-new.ko ${OPTIONS}
sleep 1
for d in /sys/bus/hid/drivers/logitech/*:046D:*; do
    [ -d "$d" ] || continue
    echo "$(basename "$d"): range=$(cat "$d/range" 2>/dev/null) sensitivity=$(cat "$d/sensitivity" 2>/dev/null) autocenter_persistent=$(cat "$d/autocenter_persistent" 2>/dev/null) app_gain=$(cat "$d/app_gain" 2>/dev/null)"
done
