"""Phone check: Notes on a device, from a release APK, with no Python per frame.

What it proves, on a device or an emulator:

* a release APK of the sample packages no ``.py`` file -- neither in the APK
  nor inside Chaquopy's asset archives;
* toggling note previews costs one Python pass, and the rows then ease over
  frames the host draws alone;
* dragging the editor is read while laying out: the title follows the column's
  progress, and not one Python pass runs while the finger moves.

The APK is built from a copy of the app in a temporary directory and signed
with the machine's debug keystore. The release *variant* is what is under test
(R8, no sources, ``BuildConfig.DEBUG`` off), not the signing key.

    python -m tools.phone_check                # build, then drive the device
    python -m tools.phone_check --apk PATH     # drive an artifact already built
    python -m tools.phone_check --keep         # keep the build directory

The device must be unlocked and be the only one attached, or named with
``--serial``. The app is installed fresh: any notes on the device are lost.
"""
