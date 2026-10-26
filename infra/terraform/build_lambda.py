#!/usr/bin/env python3
"""Prepare an ignored Lambda archive directory. Installs wheels; never calls AWS."""
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DESTINATION = Path(__file__).resolve().parent / ".terraform" / "lambda-package"


def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Run this build with the project Python 3.11+ environment.")
    if DESTINATION.exists():
        shutil.rmtree(DESTINATION)
    DESTINATION.mkdir(parents=True)
    # Wheels avoid host-specific compiled artifacts (macOS build host, Lambda Linux).
    if importlib.util.find_spec("pip"):
        command = [
            sys.executable, "-m", "pip", "install", "--target", str(DESTINATION),
            "--platform", "manylinux2014_aarch64", "--python-version", "3.12",
            "--implementation", "cp", "--only-binary=:all:", "jsonschema==4.26.0",
        ]
    elif shutil.which("uv"):
        command = [
            "uv", "pip", "install", "--target", str(DESTINATION),
            "--python-platform", "aarch64-manylinux2014", "--python-version", "3.12",
            "--only-binary", ":all:", "jsonschema==4.26.0",
        ]
    else:
        raise SystemExit("Install pip or uv in your development environment first.")
    subprocess.run(command, check=True)
    package = DESTINATION / "src" / "iot_ops"
    package.mkdir(parents=True)
    for name in ("__init__.py", "validation.py", "telemetry.schema.json"):
        shutil.copy2(ROOT / "src" / "iot_ops" / name, package / name)
    shutil.copytree(ROOT / "schemas", DESTINATION / "schemas")
    shutil.copy2(Path(__file__).parent / "modules" / "lambda" / "handler.py", DESTINATION / "handler.py")
    print(f"Lambda package prepared: {DESTINATION}")


if __name__ == "__main__":
    main()
