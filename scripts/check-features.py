#!/usr/bin/env python3
"""Verify the sensitivity / autocenter_persistent / app_gain attributes on a
plugged-in wheel. Needs write access to the wheel's sysfs directory and
evdev node (the Oversteer udev rules give that to the user).

Briefly plays a weak constant force to check app_gain; keep hands off.
"""

import glob
import os
import sys
import time

from evdev import InputDevice, ecodes, ff, list_devices

def find_wheel():
    """The wheel's sysfs directory and an evdev handle. When Oversteer's proxy
    service holds the wheel (its node is then root-only), use the proxy's
    virtual device: it forwards effects and reports the same axes."""
    for sysdir in glob.glob('/sys/bus/hid/drivers/logitech/*:046D:*'):
        for ev in glob.glob(os.path.join(sysdir, 'input/input*/event*')):
            node = '/dev/input/' + os.path.basename(ev)
            if not os.access(node, os.R_OK | os.W_OK):
                node = _proxied(node)
                if node is None:
                    continue
            dev = InputDevice(node)
            if ecodes.EV_FF in dev.capabilities():
                return sysdir, dev
            dev.close()
    return None, None


def _proxied(node):
    try:
        import json
        status = json.load(open('/run/oversteer/proxies.json'))
    except (OSError, ValueError):
        return None
    for proxy in status.get('proxies', []):
        if node in proxy.get('sources', {}).values() and proxy.get('devnode'):
            print("note: {} is held by the Oversteer proxy; using {}".format(node, proxy['devnode']))
            return proxy['devnode']
    return None

def read(sysdir, name):
    with open(os.path.join(sysdir, name)) as f:
        return f.read().strip()

def write(sysdir, name, value):
    with open(os.path.join(sysdir, name), 'w') as f:
        f.write(str(value))

def check(cond, msg):
    print(('  ok   ' if cond else '  FAIL ') + msg)
    return cond

def main():
    sysdir, dev = find_wheel()
    if dev is None:
        print("no Logitech wheel with force feedback found")
        return 1
    print("wheel:", dev.name, dev.path, "sysfs:", sysdir)
    ok = True

    print("attributes")
    for name in ('sensitivity', 'autocenter_persistent', 'app_gain'):
        ok &= check(os.path.exists(os.path.join(sysdir, name)), name)
    if not ok:
        print("new driver not loaded?")
        return 1
    ok &= check(read(sysdir, 'sensitivity') == '50', "sensitivity default 50")
    ok &= check(read(sysdir, 'autocenter_persistent') == '0', "autocenter_persistent default 0")
    ok &= check(read(sysdir, 'app_gain') == '1', "app_gain default 1")

    print("sensitivity range checks")
    write(sysdir, 'sensitivity', 100); ok &= check(read(sysdir, 'sensitivity') == '100', "accepts 100")
    try:
        write(sysdir, 'sensitivity', 101); ok &= check(False, "rejects 101")
    except OSError:
        ok &= check(True, "rejects 101")
    write(sysdir, 'sensitivity', 50)

    print("persistent centering spring")
    saved_ac = read(sysdir, 'autocenter')
    write(sysdir, 'autocenter', 20000)
    write(sysdir, 'autocenter_persistent', 1)
    dev.write(ecodes.EV_FF, ecodes.FF_AUTOCENTER, 0)          # what a game does at start-up
    time.sleep(0.2)
    ok &= check(read(sysdir, 'autocenter') == '20000', "app FF_AUTOCENTER 0 ignored while persistent")
    write(sysdir, 'autocenter_persistent', 0)
    dev.write(ecodes.EV_FF, ecodes.FF_AUTOCENTER, 0)
    time.sleep(0.2)
    ok &= check(read(sysdir, 'autocenter') == '0', "app FF_AUTOCENTER 0 honoured when not persistent")
    write(sysdir, 'autocenter', saved_ac)

    print("app gain (plays a 10% constant force for 0.2 s twice)")
    effect = ff.Effect(ecodes.FF_CONSTANT, -1, 0x4000, ff.Trigger(0, 0), ff.Replay(200, 0),
                       ff.EffectType(ff_constant_effect=ff.Constant(level=3276)))
    eid = dev.upload_effect(effect)

    def play_and_peak():
        write(sysdir, 'peak_ffb_level', 0)
        dev.write(ecodes.EV_FF, eid, 1)
        time.sleep(0.4)
        return int(read(sysdir, 'peak_ffb_level'))

    dev.write(ecodes.EV_FF, ecodes.FF_GAIN, 0)                 # game sets gain to zero
    write(sysdir, 'app_gain', 1)
    peak_honoured = play_and_peak()
    write(sysdir, 'app_gain', 0)
    peak_ignored = play_and_peak()
    dev.write(ecodes.EV_FF, ecodes.FF_GAIN, 0xffff)
    write(sysdir, 'app_gain', 1)
    dev.erase_effect(eid)
    ok &= check(peak_honoured == 0, "app_gain=1: FF_GAIN 0 silences effect (peak {})".format(peak_honoured))
    ok &= check(2500 <= peak_ignored <= 4000, "app_gain=0: FF_GAIN 0 ignored, effect plays (peak {})".format(peak_ignored))

    print("invert pedals (nudges the wheel once so every axis has reported)")
    if not os.path.exists(os.path.join(sysdir, 'invert_pedals')):
        ok &= check(False, "invert_pedals attribute present")
    else:
        def drain(seconds):
            t0 = time.time()
            while time.time() - t0 < seconds:
                if dev.read_one() is None:
                    time.sleep(0.005)
        write(sysdir, 'invert_pedals', 0)
        nudge = ff.Effect(ecodes.FF_CONSTANT, -1, 0x4000, ff.Trigger(0, 0), ff.Replay(150, 0),
                          ff.EffectType(ff_constant_effect=ff.Constant(level=9000)))
        nid = dev.upload_effect(nudge)
        dev.write(ecodes.EV_FF, nid, 1)
        drain(1.5)
        dev.erase_effect(nid)
        axes = {ecodes.ABS_Y: 1, ecodes.ABS_Z: 2, ecodes.ABS_RZ: 4}
        raw = {code: dev.absinfo(code) for code in axes}
        for mask in (7, 2, 0):
            write(sysdir, 'invert_pedals', mask)
            drain(0.3)
            for code, bit in axes.items():
                info = raw[code]
                expected = (info.max + info.min - info.value) if mask & bit else info.value
                got = dev.absinfo(code).value
                ok &= check(got == expected, "mask {}: {} raw {} -> {} (expected {})".format(
                    mask, ecodes.ABS[code], info.value, got, expected))
        ok &= check(read(sysdir, 'invert_pedals') == '0', "invert_pedals back to 0")

    print("\nALL OK" if ok else "\nFAILURES")
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
