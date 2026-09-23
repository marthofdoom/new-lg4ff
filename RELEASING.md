# Releasing new-lg4ff

Tag at good points: whenever a coherent set of features has been verified on
hardware and the tree builds cleanly. Never tag from a feature branch.

1. Merge the feature branches into `master` (`git merge --no-ff`).
2. Build against the running kernel (`make`) and, if available, the other
   kernels in the compat matrix.
3. Hardware checks on the G29 with the new module loaded
   (`sudo scripts/dev-reload.sh` then run each with the wheel plugged in,
   hands off):
   - `scripts/check-features.py`
   - `scripts/check-sensitivity.py`
   - `scripts/check-ffb-engine.py`
4. **Opus 5.5 diff review**: have Opus 5.5 (`claude-opus-5-5`) review
   `git diff <previous tag>..master` for correctness, concurrency, kernel API
   misuse, 32-bit overflow and behavioural regressions. Fix or consciously
   waive every finding before continuing.
5. Bump the version in `dkms.conf` (`PACKAGE_VERSION`) and `MODULE_VERSION`
   in `hid-lg4ff.c`/`hid-lg.c` (wherever it is defined); add a section to
   `CHANGELOG.md`.
6. Commit, tag `vX.Y.Z` (annotated), push `master` and the tag.
7. `gh release create vX.Y.Z --notes-file <notes>`; the notes are the
   changelog section plus the sysfs attributes added/changed and the udev
   rule update needed in Oversteer.
8. Re-install via DKMS for daily use:
   `sudo dkms remove new-lg4ff/<old> --all && sudo dkms install .`

Versioning: 0.x while Windows parity is incomplete; 1.0.0 when the G29
parity matrix (see the Oversteer repo, `docs/g29-windows-parity.md`) has no
red rows.
