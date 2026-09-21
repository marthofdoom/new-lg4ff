# Changelog

## 0.6.0 — 2026-09-20

Logitech G29 Windows-parity and force-feedback engine work. All verified on
a G29 (PS3 mode) with `scripts/check-*.py`.

### Added
- `sensitivity` (0–100, 50 = linear): steering response curve like the
  Logitech Windows software. Applied to ABS_X for every wheel; the position
  is re-emitted when the setting changes.
- `invert_pedals`: per-axis inversion bit mask (1 = ABS_Y, 2 = ABS_Z,
  4 = ABS_RZ). Pedals report 0 when released like gamepad triggers.
- `autocenter_persistent`: keep the sysfs centering spring even when a game
  sends `FF_AUTOCENTER 0`.
- `app_gain`: whether applications may adjust the gain (`FF_GAIN`). Default
  on, as before.
- Software-rendered condition effects: spring / damper / friction / inertia
  effects that don't get one of the three hardware slots are rendered from
  the measured wheel position instead of being dropped. Calibrated on a G29
  so they feel like their hardware counterparts.
- Real friction on wheels without the hardware friction command (G29, G923)
  instead of a damper cast; `friction_level` is now exposed for every wheel.
- `inertia_mode`: 0 (default) plays inertia as a damper like the Windows
  driver, 1 renders true inertia from wheel acceleration.
- `sw_conditions` (read-only): effects rendered in software this tick.
- `gain` accepts up to 98303 (150 %); the FFB meter shows the clipping.
- 32 simultaneous effects (was 16).
- `scripts/dev-reload.sh`, `scripts/check-features.py`,
  `scripts/check-sensitivity.py`, `scripts/check-ffb-engine.py`.

### Changed
- **G29 / G923 friction feel changes.** These wheels have no hardware
  friction command; friction effects used to be played as a damper on a
  hardware slot (scaled by `damper_level`). They are now real friction
  rendered in software, scaled by `friction_level` (default 30, same default
  as the old damper cast). Set `friction_level` to taste.

### Notes
- Oversteer's udev rule must grant access to the new attributes
  (Oversteer 0.9.0 does).
- The `autocenter_persistent` check uses a brief global flag; an
  application write racing a sysfs write on another CPU can slip through
  once. Benign.
