"""Model-check every protocol specification in this directory with TLC.

TLC is fetched once, pinned by version and SHA-256, into a user cache, and run
on each ``*.tla`` that has a matching ``*.cfg``. A violated invariant or
property fails the run with TLC's counterexample.

Usage:
    python tools/spec/check.py
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = "1.7.4"
SHA256 = "936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88"
URL = f"https://github.com/tlaplus/tlaplus/releases/download/v{VERSION}/tla2tools.jar"
HERE = Path(__file__).resolve().parent
CACHE = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pycompose"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tools() -> Path:
    """Return the pinned ``tla2tools.jar``, downloading it on first use.

    Returns:
        The verified jar.

    Raises:
        SystemExit: If the download does not match its pinned digest.
    """
    jar = CACHE / f"tla2tools-{VERSION}.jar"
    if jar.is_file() and _digest(jar) == SHA256:
        return jar
    if urllib.parse.urlsplit(URL).scheme != "https":
        raise SystemExit("refusing a download that is not HTTPS")
    CACHE.mkdir(parents=True, exist_ok=True)
    partial = jar.with_suffix(".download")
    with (
        urllib.request.urlopen(URL, timeout=120) as response,
        partial.open("wb") as out,
    ):
        shutil.copyfileobj(response, out)
    if _digest(partial) != SHA256:
        partial.unlink()
        raise SystemExit(f"tla2tools.jar does not match its pinned digest ({URL})")
    partial.replace(jar)
    return jar


def main() -> int:
    """Check every specification; stop at the first failure.

    Returns:
        0 when every model checks clean, 1 otherwise.
    """
    jar = tools()
    specs = sorted(
        path for path in HERE.glob("*.tla") if path.with_suffix(".cfg").is_file()
    )
    for spec in specs:
        with tempfile.TemporaryDirectory() as states:
            result = subprocess.run(
                [
                    "java",
                    "-XX:+UseParallelGC",
                    "-cp",
                    str(jar),
                    "tlc2.TLC",
                    "-workers",
                    "auto",
                    "-metadir",
                    states,
                    "-config",
                    spec.with_suffix(".cfg").name,
                    spec.name,
                ],
                cwd=HERE,
                capture_output=True,
                text=True,
                check=False,
            )
        if result.returncode != 0 or "No error has been found" not in result.stdout:
            print(result.stdout + result.stderr, file=sys.stderr)
            print(f"spec: {spec.name} failed", file=sys.stderr)
            return 1
        print(f"spec: {spec.name} checked clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
