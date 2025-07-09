#!/usr/bin/env python3
"""
rapl_power.py  –  Read Intel RAPL energy counters and print:
  • Package power (W)
  • Power per core (W)
  • Power per core per MHz (µW / MHz)

Run as root or give yourself read permissions on
    /sys/class/powercap/intel-rapl*/energy_uj
"""

import argparse
import glob
import os
import re
import time
from collections import defaultdict
from typing import Dict, List

ENERGY_PATH_GLOB = "/sys/class/powercap/intel-rapl/intel-rapl:*"
CPU_TOPOLOGY_GLOB = "/sys/devices/system/cpu/cpu[0-9]*/topology/physical_package_id"

# --------------------------------------------------------------------------- #
# Helper functions                                                            #
# --------------------------------------------------------------------------- #
_cpu_re = re.compile(r"cpu(\d+)")

def cpu_id_from_path(path: str) -> int:
    """Return the integer CPU id embedded in …/cpuN/…"""
    m = _cpu_re.search(path)
    if not m:
        raise ValueError(f"Cannot parse CPU id from {path}")
    return int(m.group(1))


def list_packages() -> List[str]:
    """Return paths to package-level RAPL zones (name starts with 'package-')."""
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
    """Map socket → list of logical CPU ids."""
    mapping: Dict[int, List[int]] = defaultdict(list)
    for topo_path in glob.glob(CPU_TOPOLOGY_GLOB):
        cpu_id = cpu_id_from_path(topo_path)
        with open(topo_path) as f:
            socket_id = int(f.read().strip())
        mapping[socket_id].append(cpu_id)
    return mapping


def read_energy_uj(fd: int) -> int:
    """Read current energy in µJ from an already-open fd."""
    os.lseek(fd, 0, os.SEEK_SET)
    return int(os.read(fd, 32).decode().strip())


def read_max_range_uj(zone: str) -> int:
    """Maximum counter value before wrap-around."""
    with open(os.path.join(zone, "max_energy_range_uj")) as f:
        return int(f.read().strip())


def read_freq_khz(cpu: int) -> int:
    """Current frequency of a logical CPU, in kHz."""
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
    return 0  # governor disabled or cpufreq not compiled; treat as 0


# --------------------------------------------------------------------------- #
# Main sampling loop                                                          #
# --------------------------------------------------------------------------- #
def sample(interval: float) -> None:
    pkgs = list_packages()
    if not pkgs:
        raise RuntimeError("No RAPL package zones found – is this an Intel CPU?")

    # Open fds once
    fds = {pkg: os.open(os.path.join(pkg, "energy_uj"), os.O_RDONLY) for pkg in pkgs}
    ranges = {pkg: read_max_range_uj(pkg) for pkg in pkgs}
    last_energy = {pkg: read_energy_uj(fd) for pkg, fd in fds.items()}
    last_time_ns = time.monotonic_ns()

    sockets = cores_by_socket()

    # Header
    hdr = f"{'Socket':>6} | {'Pkg W':>8} | {'W/core':>8} | {'µW/MHz':>8}"
    print(hdr)
    print("-" * len(hdr))

    while True:
        time.sleep(interval)
        now_ns = time.monotonic_ns()
        dt = (now_ns - last_time_ns) / 1e9  # seconds
        last_time_ns = now_ns

        for pkg in pkgs:
            new_energy = read_energy_uj(fds[pkg])
            old_energy = last_energy[pkg]
            rng = ranges[pkg]
            if new_energy < old_energy:           # wrap-around
                new_energy += rng
            diff_j = (new_energy - old_energy) / 1e6  # µJ → J
            last_energy[pkg] = new_energy
            power_w = diff_j / dt

            socket_id = int(pkg.split(":")[1].split("/")[0])
            core_list = sockets.get(socket_id, [])
            ncores = len(core_list) or 1  # avoid div-by-zero

            freqs_mhz = [
                read_freq_khz(c) / 1000
                for c in core_list
                if read_freq_khz(c)
            ]
            avg_mhz = sum(freqs_mhz) / len(freqs_mhz) if freqs_mhz else 0

            w_per_core = power_w / ncores
            uw_per_mhz = (w_per_core * 1e6) / avg_mhz if avg_mhz else 0

            print(f"{socket_id:6} | {power_w:8.2f} | {w_per_core:8.3f} | {uw_per_mhz:8.1f}")
        print()


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
    args = parser.parse_args()
    try:
        sample(args.interval)
    except KeyboardInterrupt:
        pass
