#!/usr/bin/env python3
"""Hands-off check of the steering sensitivity curve on a plugged-in wheel.

The centering spring pulls the wheel to centre while a weak constant force
pushes it away, so it settles off-centre. With the evdev node kept open
(the wheel only reports while something is listening), each sensitivity
change makes the driver re-emit the position through the new curve, which
is compared with the reference implementation. Keep hands off the wheel.
"""

import glob
import os
import sys
import time
from math import isqrt

from evdev import InputDevice, ecodes, ff

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

def reference(value, s, mn, mx):
    """Same integer maths as lg4ff_apply_sensitivity()."""
    if s == 50 or mx <= mn:
        return value
    half = (mx - mn + 1) // 2
    centre = mn + half
    neg = value < centre
    ax = (centre - value) if neg else (value - centre)
    ax = min(ax * 65535 // half, 65535)
    if s < 50:
        mix = (50 - s) * 2
        curved = ax * ax // 65535
    else:
        mix = (s - 50) * 2
        curved = isqrt(ax * 65535)
    out = (ax * (100 - mix) + curved * mix) // 100
    out = out * half // 65535
    return max(mn, centre - out) if neg else min(mx, centre + out)

def drain(dev, seconds):
    """Read events for a while; return the last ABS_X seen (or None)."""
    last = None
    t0 = time.time()
    while time.time() - t0 < seconds:
        e = dev.read_one()
        if e is None:
            time.sleep(0.005)
            continue
        if e.type == ecodes.EV_ABS and e.code == ecodes.ABS_X:
            last = e.value
    return last

def main():
    sysdir, dev = find_wheel()
    if dev is None:
        print("no Logitech wheel with force feedback found")
        return 1
    info = dev.absinfo(ecodes.ABS_X)
    mn, mx = info.min, info.max
    print("wheel:", dev.name, dev.path, " ABS_X range", mn, "..", mx)
    saved_ac = read(sysdir, 'autocenter')
    ok = True
    eid = None
    try:
        write(sysdir, 'sensitivity', 50)
        write(sysdir, 'autocenter', 30000)
        # Nudge the wheel so it reports at least once (a wheel already at
        # centre stays silent and the cached value would be stale).
        nudge = ff.Effect(ecodes.FF_CONSTANT, -1, 0x4000, ff.Trigger(0, 0), ff.Replay(150, 0),
                          ff.EffectType(ff_constant_effect=ff.Constant(level=9000)))
        nid = dev.upload_effect(nudge)
        dev.write(ecodes.EV_FF, nid, 1)
        drain(dev, 2.5)
        dev.erase_effect(nid)
        centre = dev.absinfo(ecodes.ABS_X).value
        print("wheel's own centre with spring on: {} (offset {:+} from {})".format(centre, centre - (mn + (mx - mn + 1) // 2), mn + (mx - mn + 1) // 2))

        effect = ff.Effect(ecodes.FF_CONSTANT, -1, 0x4000, ff.Trigger(0, 0), ff.Replay(0, 0),
                           ff.EffectType(ff_constant_effect=ff.Constant(level=int(os.environ.get('PUSH', 12000)))))
        eid = dev.upload_effect(effect)
        dev.write(ecodes.EV_FF, eid, 1)
        drain(dev, 2.5)
        raw = dev.absinfo(ecodes.ABS_X).value
        print("parked off-centre at {} (offset {:+})".format(raw, raw - centre))
        if abs(raw - (mn + (mx - mn + 1) // 2)) < 1500:
            print("  note: less than 1500 counts off centre; set PUSH=<level> higher for a stronger test")

        for s in (0, 25, 75, 100, 50):
            write(sysdir, 'sensitivity', s)
            got = drain(dev, 0.3)
            exp = reference(raw, s, mn, mx)
            line = "  sensitivity {:3}: driver={!s:>6} reference={:6}".format(s, got, exp)
            if got is None:
                print(line + "  FAIL (no re-emitted event)")
                ok = False
            elif abs(got - exp) > 300:
                print(line + "  FAIL (diff {:+})".format(got - exp))
                ok = False
            else:
                print(line + "  ok")
    finally:
        if eid is not None:
            dev.write(ecodes.EV_FF, eid, 0)
            dev.erase_effect(eid)
        write(sysdir, 'sensitivity', 50)
        write(sysdir, 'autocenter', saved_ac)
    print("\nCURVE OK" if ok else "\nFAILURES")
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
