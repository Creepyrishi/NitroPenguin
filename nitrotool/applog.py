"""Activity log for NitroPenguin (GUI and daemon).

One line per event, pipe-delimited so the file stays easy to read,
grep, and load into a spreadsheet or pandas:

    2026-07-28T14:03:21.512 | gui | INFO | battery | Limiter on (direct write)

Each process calls setup() once; after that any module logs through the
standard logging module. Files rotate at ~200 KB so the log can never
grow unbounded. export_report() bundles a system snapshot plus every
log line, merged in time order, into one text file for bug reports.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import subprocess
import sys
import time
from pathlib import Path

LOG_DIR = Path.home() / ".config" / "nitrotool" / "logs"
PROCESSES = ("daemon", "gui")
SEP = " | "


def setup(proc: str) -> None:
    """Send this process's log records to logs/<proc>.log (rotating)."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / f"{proc}.log", maxBytes=200_000, backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        f"%(asctime)s.%(msecs)03d{SEP}{proc}{SEP}%(levelname)s{SEP}"
        f"%(name)s{SEP}%(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
    root = logging.getLogger()
    debug = bool(os.environ.get("NITROPENGUIN_DEBUG"))
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.addHandler(handler)
    sys.excepthook = _log_uncaught
    logging.getLogger("app").info("--- %s started (pid %d) ---",
                                  proc, os.getpid())


def _log_uncaught(exc_type, exc, tb) -> None:
    if not issubclass(exc_type, KeyboardInterrupt):
        logging.getLogger("app").critical(
            "Uncaught exception", exc_info=(exc_type, exc, tb)
        )
    sys.__excepthook__(exc_type, exc, tb)


# EXPORT

def export_report(dest: Path) -> None:
    """Write a self-contained debug report: system + driver snapshot,
    then every log line from both processes merged in time order."""
    from nitrotool import hw

    out: list[str] = []
    out.append("NITROPENGUIN DEBUG REPORT")
    out.append(f"generated: {time.strftime('%Y-%m-%dT%H:%M:%S')}")
    out.append("=" * 60)

    out.append("")
    out.append("[system]")
    out.append(f"model    = {_read('/sys/class/dmi/id/product_name')}")
    out.append(f"kernel   = {os.uname().release}")
    out.append(f"desktop  = {os.environ.get('XDG_CURRENT_DESKTOP', '?')}")
    out.append(f"commit   = {_git_commit(hw.PROJECT_DIR)}")
    out.append(f"daemon   = {'running' if hw.daemon_running() else 'not running'}")

    out.append("")
    out.append("[drivers]")
    for c in hw.components():
        out.append(
            f"{c.key:<8}= {c.status} (loaded={_yn(c.loaded)}, "
            f"boot={_yn(c.installed)})"
        )
    out.append(f"health_mode = {_read(hw.HEALTH_MODE)}")
    out.append(f"fan_speed   = {_read(hw.FAN_SPEED)}")
    cpu, igpu = hw.cpu_temp(), hw.igpu_temp()
    out.append(f"cpu_temp    = {cpu if cpu is not None else '?'}")
    out.append(f"igpu_temp   = {igpu if igpu is not None else '?'}")
    out.append(f"dgpu        = {'awake' if hw.dgpu_awake() else 'asleep'}")

    out.append("")
    out.append("[keyboard state]")
    out.append(_read(hw.CONFIG_DIR / "keyboard.json"))

    out.append("")
    out.append(f"[log]  time{SEP}process{SEP}level{SEP}component{SEP}message")
    entries = _merged_entries()
    out.extend(entries or ["(no log entries recorded yet)"])
    out.append("")

    dest.write_text("\n".join(out), encoding="utf-8")


def _yn(flag: bool) -> str:
    return "yes" if flag else "no"


def _read(path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return "(unavailable)"


def _git_commit(project_dir: Path) -> str:
    try:
        run = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=3,
        )
        return run.stdout.strip() or "(unknown)"
    except (OSError, subprocess.SubprocessError):
        return "(unknown)"


def _merged_entries() -> list[str]:
    entries: list[str] = []
    for proc in PROCESSES:
        for suffix in (".2", ".1", ""):
            entries.extend(_entries(LOG_DIR / f"{proc}.log{suffix}"))
    # ISO timestamps sort correctly as text; stable sort keeps each
    # file's internal order for same-millisecond lines.
    return sorted(entries, key=lambda e: e[:23])


def _entries(path: Path) -> list[str]:
    """One string per record; traceback lines stay glued to the record
    that produced them so sorting can't interleave them."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    entries: list[str] = []
    for line in text.splitlines():
        if line.startswith("20") and SEP in line[:30]:
            entries.append(line)
        elif entries:
            entries[-1] += "\n" + line
    return entries
