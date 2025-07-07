#!/usr/bin/env python3
"""
rapl_power.py  –  Lightweight Intel RAPL power monitor

Outputs (per socket)
  • Package power (W)
  • Power per core (W)
  • Average effective clock (MHz)
  • Power per core per MHz (µW / MHz)

Usage examples
  sudo python3 rapl_power.py           # plain table, 1 s interval
  sudo python3 rapl_power.py 0.5 -j    # JSON every 0.5 s
  sudo python3 rapl_power.py -j | jq   # pretty-print with jq

Requires read access to
  /sys/class/powercap/intel-rapl*/energy_uj
"""

import argparse
import glob
import json
import os
import re
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
# Main sampling loop                                                          #
# --------------------------------------------------------------------------- #
def sample(interval: float, json_mode: bool) -> None:
    pkgs = list_packages()
    if not pkgs:
        raise RuntimeError("No RAPL package zones found – is this an Intel CPU?")

    fds = {pkg: os.open(os.path.join(pkg, "energy_uj"), os.O_RDONLY) for pkg in pkgs}
    ranges = {pkg: read_max_range_uj(pkg) for pkg in pkgs}
    last_energy = {pkg: read_energy_uj(fd) for pkg, fd in fds.items()}
    last_time_ns = time.monotonic_ns()

    sockets = cores_by_socket()

    if not json_mode:
        hdr = (
            f"{'Socket':>6} | {'Pkg W':>10} | {'W/core':>10} | "
            f"{'Avg MHz':>10} | {'µW/MHz':>12}"
        )
        print(hdr)
        print("-" * len(hdr))

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
                print(
                    f"{socket_id:6} | "
                    f"{power_w:8.2f} W | "
                    f"{w_per_core:8.3f} W | "
                    f"{avg_mhz:8.0f} MHz | "
                    f"{uw_per_mhz:10.1f} µW/MHz"
                )

        if json_mode:
            blob = {
                "timestamp": time.time(),
                "interval": interval,
                "sockets": measurements,
            }
            print(json.dumps(blob))
        else:
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
    parser.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="output each sample as a JSON object instead of a table",
    )
    args = parser.parse_args()

    try:
        sample(args.interval, args.json)
    except KeyboardInterrupt:
        pass
