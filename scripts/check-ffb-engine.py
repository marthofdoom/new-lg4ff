#!/usr/bin/env python3
"""Force feedback engine checks on a plugged-in wheel: software-rendered
condition effects (hardware slot overflow, software inertia), effect count
and gain above 100 %. Moves the wheel with moderate forces; hands off.
"""

import glob
import os
import sys
import time

from evdev import InputDevice, ecodes, ff
import ctypes, fcntl

class uinput_ff:
    """EVIOCSFF without python-evdev's GIL-holding wrapper"""
    EVIOCSFF = (1 << 30) | (ctypes.sizeof(ff.Effect) << 16) | (ord('E') << 8) | 0x80
    @staticmethod
    def upload_effect(fd, effect):
        fcntl.ioctl(fd, uinput_ff.EVIOCSFF, effect)
        return effect.id

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

def drain(dev, seconds):
    t0 = time.time()
    while time.time() - t0 < seconds:
        if dev.read_one() is None:
            time.sleep(0.003)

def condition(etype, coeff, sat, center=0, deadband=0):
    cond = ff.Condition(right_saturation=sat, left_saturation=sat, right_coeff=coeff,
                        left_coeff=coeff, deadband=deadband, center=center)
    return ff.Effect(etype, -1, 0x4000, ff.Trigger(0, 0), ff.Replay(0, 0),
                     ff.EffectType(ff_condition_effect=(cond, cond)))

def constant(level, length_ms):
    return ff.Effect(ecodes.FF_CONSTANT, -1, 0x4000, ff.Trigger(0, 0), ff.Replay(length_ms, 0),
                     ff.EffectType(ff_constant_effect=ff.Constant(level=level)))

def pos(dev):
    return dev.absinfo(ecodes.ABS_X).value

def main():
    sysdir, dev = find_wheel()
    if dev is None:
        print("no Logitech wheel with force feedback found")
        return 1
    print("wheel:", dev.name, dev.path)
    ok = True
    saved = {k: read(sysdir, k) for k in ('gain', 'autocenter', 'inertia_mode')}
    playing = []

    def start(effect):
        eid = dev.upload_effect(effect)
        dev.write(ecodes.EV_FF, eid, 1)
        playing.append(eid)
        return eid

    def stop_all():
        while playing:
            eid = playing.pop()
            dev.write(ecodes.EV_FF, eid, 0)
            dev.erase_effect(eid)

    try:
        write(sysdir, 'autocenter', 0)
        write(sysdir, 'gain', 65535)
        write(sysdir, 'inertia_mode', 0)

        print("effect count")
        ok &= check(dev.ff_effects_count >= 32, "ff_effects_count = {} (>= 32)".format(dev.ff_effects_count))

        print("hardware slot overflow -> software rendering")
        # Three zero-saturation dampers occupy the hardware slots without producing force
        for _ in range(3):
            start(condition(ecodes.FF_DAMPER, 0x7fff, 0))
        drain(dev, 0.1)
        ok &= check(read(sysdir, 'sw_conditions') == '0', "3 condition effects: none in software")
        spring = start(condition(ecodes.FF_SPRING, 0x7fff, 0xffff))
        drain(dev, 0.1)
        ok &= check(read(sysdir, 'sw_conditions') == '1', "4th condition effect rendered in software")

        # The software spring must hold a push like the hardware spring does and
        # pull the wheel back afterwards. Start from centre (hardware autocenter),
        # full spring level so the push stays below saturation.
        centre = 32768
        saved['spring_level'] = read(sysdir, 'spring_level')
        write(sysdir, 'spring_level', 100)
        write(sysdir, 'autocenter', 30000); drain(dev, 1.2); write(sysdir, 'autocenter', 0); drain(dev, 0.3)
        push = start(constant(12000, 700))
        drain(dev, 0.55)                            # sample while the push is still on
        displaced = pos(dev)
        drain(dev, 1.5)
        returned = pos(dev)
        print("  wheel: pushed to {:+} from centre, spring returned it to {:+}".format(displaced - centre, returned - centre))
        ok &= check(200 < abs(displaced - centre) < 3000, "software spring held a 37 % push within hardware-like deflection (hardware: ~800)")
        ok &= check(abs(returned - centre) < 600, "software spring re-centred the wheel (gearbox stiction allows a few hundred counts)")
        write(sysdir, 'spring_level', saved['spring_level'])
        stop_all()
        drain(dev, 0.2)
        ok &= check(read(sysdir, 'sw_conditions') == '0', "software effects released")

        print("software inertia mode")
        write(sysdir, 'inertia_mode', 1)
        start(condition(ecodes.FF_INERTIA, 0x7fff, 0xffff))
        drain(dev, 0.1)
        ok &= check(read(sysdir, 'sw_conditions') == '1', "inertia effect rendered in software (no hardware slot)")
        # It must still leave all three hardware slots free
        for _ in range(3):
            start(condition(ecodes.FF_DAMPER, 0x7fff, 0))
        drain(dev, 0.1)
        ok &= check(read(sysdir, 'sw_conditions') == '1', "three hardware slots still available beside software inertia")
        stop_all()
        # True inertia must not turn quantisation noise into force: under a gentle
        # push the peak must stay near the push itself, far from saturation.
        saved['damper_level'] = read(sysdir, 'damper_level')
        write(sysdir, 'damper_level', 100)
        write(sysdir, 'autocenter', 30000); drain(dev, 1.2); write(sysdir, 'autocenter', 0); drain(dev, 0.3)
        start(condition(ecodes.FF_INERTIA, 0x7fff, 0xffff))
        drain(dev, 0.2)
        write(sysdir, 'peak_ffb_level', 0)
        start(constant(8000, 600)); drain(dev, 0.9); playing.pop()
        peak = int(read(sysdir, 'peak_ffb_level'))
        stop_all()
        write(sysdir, 'damper_level', saved['damper_level'])
        ok &= check(peak < 20000, "software inertia under a 24 % push: peak {} (noise would saturate at ~40000)".format(peak))
        write(sysdir, 'inertia_mode', 0)
        drain(dev, 0.1)
        start(condition(ecodes.FF_INERTIA, 0x7fff, 0xffff))
        drain(dev, 0.1)
        ok &= check(read(sysdir, 'sw_conditions') == '0', "inertia_mode=0: inertia takes a hardware slot (as damper)")
        stop_all()
        # A 4th inertia effect with inertia_mode=0 must still behave as a damper in software
        for _ in range(3):
            start(condition(ecodes.FF_DAMPER, 0x7fff, 0))
        start(condition(ecodes.FF_INERTIA, 0x7fff, 0xffff))
        drain(dev, 0.2)
        write(sysdir, 'peak_ffb_level', 0)
        start(constant(8000, 600)); drain(dev, 0.9); playing.pop()
        peak = int(read(sysdir, 'peak_ffb_level'))
        sw = read(sysdir, 'sw_conditions')
        stop_all()
        ok &= check(sw == '1' and peak < 20000, "overflow inertia with inertia_mode=0 rendered in software as damper (sw={}, peak {})".format(sw, peak))

        print("friction on a wheel without hardware friction (G29/G923) is rendered in software")
        if os.path.exists(os.path.join(sysdir, 'friction_level')):
            saved['friction_level'] = read(sysdir, 'friction_level')
            write(sysdir, 'friction_level', 100)
            start(condition(ecodes.FF_FRICTION, 0x7fff, 0xffff))
            drain(dev, 0.1)
            sw = read(sysdir, 'sw_conditions')
            print("  sw_conditions = {} (1 on G29/G923, 0 on wheels with hardware friction)".format(sw))
            # Motion check: with full friction a weak push should barely move the wheel
            write(sysdir, 'autocenter', 30000); drain(dev, 1.5); write(sysdir, 'autocenter', 0); drain(dev, 0.2)
            p0 = pos(dev)
            start(constant(-8000, 400)); drain(dev, 0.7); playing.pop()
            moved_with = abs(pos(dev) - p0)
            stop_all()
            write(sysdir, 'autocenter', 30000); drain(dev, 1.5); write(sysdir, 'autocenter', 0); drain(dev, 0.2)
            p0 = pos(dev)
            start(constant(-8000, 400)); drain(dev, 0.7); playing.pop()
            moved_without = abs(pos(dev) - p0)
            stop_all()
            print("  24 % push moved the wheel {} counts with friction, {} without".format(moved_with, moved_without))
            ok &= check(moved_with < moved_without / 2, "friction resists motion")
        else:
            print("  (no friction_level attribute)")

        print("rumble emulation")
        if ecodes.FF_RUMBLE in dev.capabilities().get(ecodes.EV_FF, []):
            saved['rumble_level'] = read(sysdir, 'rumble_level')
            write(sysdir, 'rumble_level', 50)
            write(sysdir, 'peak_ffb_level', 0)
            rumble = ff.Effect(ecodes.FF_RUMBLE, -1, 0, ff.Trigger(0, 0), ff.Replay(300, 0),
                               ff.EffectType(ff_rumble_effect=ff.Rumble(strong_magnitude=0x8000, weak_magnitude=0)))
            start(rumble); drain(dev, 0.6); playing.pop()
            peak = int(read(sysdir, 'peak_ffb_level'))
            ok &= check(7000 <= peak <= 9000, "strong rumble 0x8000 at rumble_level 50 -> peak {} (~8192)".format(peak))
            # Games re-upload rumble every frame; the vibration must carry on, not restart
            write(sysdir, 'peak_ffb_level', 0)
            eid = start(rumble)
            for _ in range(18):
                uinput_ff.upload_effect(dev.fd, ff.Effect(ecodes.FF_RUMBLE, eid, 0, ff.Trigger(0, 0), ff.Replay(300, 0),
                                        ff.EffectType(ff_rumble_effect=ff.Rumble(strong_magnitude=0x8000, weak_magnitude=0))))
                dev.write(ecodes.EV_FF, eid, 1)
                drain(dev, 0.016)
            drain(dev, 0.2)
            playing.pop(); dev.erase_effect(eid)
            peak = int(read(sysdir, 'peak_ffb_level'))
            ok &= check(7000 <= peak <= 9000, "rumble re-uploaded every 16 ms still peaks {} (~8192)".format(peak))
            write(sysdir, 'rumble_level', saved['rumble_level'])
        else:
            ok &= check(False, "FF_RUMBLE advertised")

        print("gain above 100 %")
        write(sysdir, 'gain', 98303)
        ok &= check(read(sysdir, 'gain') == '98303', "gain accepts 150 % (98303)")
        write(sysdir, 'gain', 200000)
        ok &= check(read(sysdir, 'gain') == '98303', "gain clamps to 150 %")
        write(sysdir, 'peak_ffb_level', 0)
        eid = start(constant(16000, 200))       # ~49 % request
        drain(dev, 0.5)
        peak = int(read(sysdir, 'peak_ffb_level'))
        stop_all()
        ok &= check(23000 <= peak <= 25000, "49 % constant at 150 % gain -> peak {} (~24000 expected)".format(peak))
        write(sysdir, 'gain', 65535)
    finally:
        stop_all()
        for k, v in saved.items():
            write(sysdir, k, v)
    print("\nALL OK" if ok else "\nFAILURES")
    return 0 if ok else 1

if __name__ == '__main__':
    sys.exit(main())
