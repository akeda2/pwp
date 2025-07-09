#!/usr/bin/env python3
"""
rapl_power.py  –  Lightweight Intel RAPL power monitor

Outputs (per socket):
  • Package power (W)
  • Power per core (W)
  • Average effective clock (MHz)
  • Power per core per MHz (µW / MHz)

Display modes
  default        – append rows forever (what you already had)
  --max-lines N  – keep at most N data rows, then clear screen & redraw header
  --fullscreen   – rewrite the same rows in-place (no vertical growth)
  --json (-j)    – emit one JSON object per sample (machine-readable)

Examples
  sudo python3 rapl_power.py
  sudo python3 rapl_power.py 0.5 --max-lines 20
  sudo python3 rapl_power.py --fullscreen
  sudo python3 rapl_power.py -j | jq

Requires read access to
  /sys/class/powercap/intel-rapl*/energy_uj
"""

import argparse
import glob
import json
import os
import re
import sys
import time
from collections import defaultdict
from typing import Dict, List

ENERGY_PATH_GLOB = "/sys/class/powercap/intel-rapl/intel-rapl:*"
CPU_TOPOLOGY_GLOB = (
    "/sys/devices/system/cpu/cpu[0-9]*/topology/physical_package_id"
)

_cpu_re = re.compile(r"cpu(\d+)")


# --------------------------------------------------------------------------- #
# Helper functions                                                            #
# --------------------------------------------------------------------------- #
def cpu_id_from_path(path: str) -> int:
    m = _cpu_re.search(path)
    if not m:
        raise ValueError(f"Cannot parse CPU id from {path}")
    return int(m.group(1))


def list_packages() -> List[str]:
    pkgs = []
    for zone in glob.glob(ENERGY_PATH_GLOB):
        try:
            with open(os.path.join(zone, "name")) as f:
                if f.read().startswith("package"):
                    pkgs.append(zone)
        except FileNotFoundError:
            continue
    return pkgs


def cores_by_socket() -> Dict[int, List[int]]:
    mapping: Dict[int, List[int]] = defaultdict(list)
    for topo_path in glob.glob(CPU_TOPOLOGY_GLOB):
        cpu_id = cpu_id_from_path(topo_path)
        with open(topo_path) as f:
            socket_id = int(f.read().strip())
        mapping[socket_id].append(cpu_id)
    return mapping


def read_energy_uj(fd: int) -> int:
    os.lseek(fd, 0, os.SEEK_SET)
    return int(os.read(fd, 32).decode().strip())


def read_max_range_uj(zone: str) -> int:
    with open(os.path.join(zone, "max_energy_range_uj")) as f:
        return int(f.read().strip())


def read_freq_khz(cpu: int) -> int:
    paths = [
        f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/scaling_cur_freq",
        f"/sys/devices/system/cpu/cpu{cpu}/cpufreq/cpuinfo_cur_freq",
    ]
    for p in paths:
        try:
            with open(p) as f:
                return int(float(f.read().strip()))
        except FileNotFoundError:
            continue
    return 0  # governor disabled / cpufreq not present


# --------------------------------------------------------------------------- #
# Terminal helpers                                                            #
# --------------------------------------------------------------------------- #
CSI = "\033["  # Control-Sequence Introducer (ANSI)

def clear_screen() -> None:
    """Clear screen & move cursor to 1;1."""
    sys.stdout.write(CSI + "2J" + CSI + "H")

def cursor_up(lines: int) -> None:
    """Move cursor up *lines* rows."""
    if lines > 0:
        sys.stdout.write(CSI + f"{lines}A")


# --------------------------------------------------------------------------- #
# Main sampling loop                                                          #
# --------------------------------------------------------------------------- #
def sample(interval: float,
           json_mode: bool,
           max_lines: int | None,
           fullscreen: bool) -> None:

    if json_mode and (max_lines or fullscreen):
        raise SystemExit("JSON mode is incompatible with --max-lines / --fullscreen")

    pkgs = list_packages()
    if not pkgs:
        raise RuntimeError("No RAPL package zones found – is this an Intel CPU?")

    fds = {pkg: os.open(os.path.join(pkg, "energy_uj"), os.O_RDONLY) for pkg in pkgs}
    ranges = {pkg: read_max_range_uj(pkg) for pkg in pkgs}
    last_energy = {pkg: read_energy_uj(fd) for pkg, fd in fds.items()}
    last_time_ns = time.monotonic_ns()

    sockets = cores_by_socket()

    header = (
        f"{'Socket':>6} | {'Pkg W':>10} | {'W/core':>10} | "
        f"{'Avg MHz':>10} | {'µW/MHz':>12}"
    )

    if not json_mode:
        print(header)
        print("-" * len(header))
        printed_data_rows = 0

    while True:
        time.sleep(interval)
        now_ns = time.monotonic_ns()
        dt = (now_ns - last_time_ns) / 1e9
        last_time_ns = now_ns

        measurements = {}

        for pkg in pkgs:
            new_energy = read_energy_uj(fds[pkg])
            old_energy = last_energy[pkg]
            rng = ranges[pkg]
            if new_energy < old_energy:
                new_energy += rng
            diff_j = (new_energy - old_energy) / 1e6
            last_energy[pkg] = new_energy
            power_w = diff_j / dt

            socket_id = int(pkg.split(":")[1].split("/")[0])
            core_list = sockets.get(socket_id, [])
            ncores = len(core_list) or 1

            freqs_mhz = [
                read_freq_khz(c) / 1000
                for c in core_list
                if read_freq_khz(c)
            ]
            avg_mhz = sum(freqs_mhz) / len(freqs_mhz) if freqs_mhz else 0

            w_per_core = power_w / ncores
            uw_per_mhz = (w_per_core * 1e6) / avg_mhz if avg_mhz else 0

            if json_mode:
                measurements[str(socket_id)] = {
                    "pkg_w": round(power_w, 3),
                    "w_per_core": round(w_per_core, 4),
                    "avg_mhz": round(avg_mhz),
                    "uw_per_mhz": round(uw_per_mhz, 1),
                }
            else:
                line = (
                    f"{socket_id:6} | "
                    f"{power_w:8.2f} W | "
                    f"{w_per_core:8.3f} W | "
                    f"{avg_mhz:8.0f} MHz | "
                    f"{uw_per_mhz:10.1f} µW/MHz"
                )
                if fullscreen:
                    print(line)
                else:
                    print(line)
                    printed_data_rows += 1

        if json_mode:
            blob = {
                "timestamp": time.time(),
                "interval": interval,
                "sockets": measurements,
            }
            print(json.dumps(blob))

        elif fullscreen:
            # Move cursor back up (#pkgs) rows to overwrite on next loop
            cursor_up(len(pkgs))

        elif max_lines and printed_data_rows >= max_lines:
            # Reset the “page”
            clear_screen()
            print(header)
            print("-" * len(header))
            printed_data_rows = 0

        sys.stdout.flush()


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Lightweight RAPL power monitor (per socket/core/MHz)."
    )
    parser.add_argument(
        "interval",
        nargs="?",
        default=1.0,
        type=float,
        help="sampling interval in seconds (default: 1.0)",
    )
    parser.add_argument(
        "-j", "--json",
        action="store_true",
        help="output each sample as a JSON object (disables table modes)",
    )
    parser.add_argument(
        "--max-lines",
        type=int,
        metavar="N",
        help="print at most N data rows, then clear screen & redraw header "
             "(table mode only)",
    )
    parser.add_argument(
        "--fullscreen",
        action="store_true",
        help="rewrite the same screenful in place (no vertical growth)",
    )
    args = parser.parse_args()

    try:
        sample(
            interval=args.interval,
            json_mode=args.json,
            max_lines=args.max_lines,
            fullscreen=args.fullscreen,
        )
    except KeyboardInterrupt:
        pass
