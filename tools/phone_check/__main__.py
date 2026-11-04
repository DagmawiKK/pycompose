"""The command line: build or take an APK, then drive one device."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from tools.phone_check.checks import APP, drive
from tools.phone_check.device import Device, PhoneCheckError, serial_or_only_one


def main() -> int:
    """Build the release APK and drive the sample on the device.

    Returns:
        Zero when every check held, one when one did not.
    """
    parser = argparse.ArgumentParser(description="check the sample on a device")
    parser.add_argument("--serial", help="the device to drive, if several are attached")
    parser.add_argument("--apk", type=Path, help="check this APK, do not build")
    parser.add_argument(
        "--app", type=Path, default=APP, help="the app to build and drive"
    )
    parser.add_argument("--keep", action="store_true", help="keep the build directory")
    args = parser.parse_args()
    try:
        device = Device(args.serial or serial_or_only_one())
        if args.keep:
            work = Path(tempfile.mkdtemp(prefix="pycompose-phone-"))
            try:
                drive(args.app, args.apk, device, work)
            finally:
                print(f"\nkept {work}")
        else:
            with tempfile.TemporaryDirectory(prefix="pycompose-phone-") as directory:
                drive(args.app, args.apk, device, Path(directory))
    except PhoneCheckError as failure:
        print(f"\nFAILED: {failure}", file=sys.stderr)
        return 1
    print("\nall checks held")
    return 0


if __name__ == "__main__":
    sys.exit(main())
