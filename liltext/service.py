from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.navthings.liltext"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG_PATH = Path.home() / "Library" / "Logs" / "liltext.log"


def executable_root() -> Path:
    return Path(__file__).resolve().parent.parent


def plist_data() -> dict:
    python = sys.executable
    daemon = str(executable_root() / "liltextd")
    return {
        "Label": LABEL,
        "ProgramArguments": [python, daemon],
        "RunAtLoad": True,
        "KeepAlive": True,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "StandardOutPath": str(LOG_PATH),
        "StandardErrorPath": str(LOG_PATH),
        "EnvironmentVariables": {"PYTHONUNBUFFERED": "1"},
    }


def install() -> None:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plistlib.dumps(plist_data(), fmt=plistlib.FMT_XML, sort_keys=False))
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    subprocess.run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(PLIST_PATH)], check=True)
    subprocess.run(["launchctl", "enable", f"gui/{os.getuid()}/{LABEL}"], check=True)


def uninstall() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    PLIST_PATH.unlink(missing_ok=True)


def start() -> None:
    subprocess.run(["launchctl", "kickstart", f"gui/{os.getuid()}/{LABEL}"], check=True)


def stop() -> None:
    subprocess.run(["launchctl", "kill", "SIGTERM", f"gui/{os.getuid()}/{LABEL}"], check=True)


def restart() -> None:
    subprocess.run(["launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{LABEL}"], check=True)


def status() -> str:
    result = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{LABEL}"], text=True, capture_output=True)
    return result.stdout.strip() if result.returncode == 0 else "not running"


def validate_plist() -> None:
    plistlib.loads(PLIST_PATH.read_bytes())
