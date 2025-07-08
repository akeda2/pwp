#!/usr/bin/env python3
"""
rapl_power.py  –  Lightweight Intel RAPL power monitor

Outputs (per socket):
  • Package power (W)
  • Power per PHYSICAL core   (default)   or per logical thread (use -l)
  • Average effective clock (MHz)
  • Power per core per MHz (µW / MHz)

Display modes
  default        – append rows forever
  --max-lines N  – keep at most N data rows, then clear screen & redraw header
  --fullscreen   – rewrite the same rows in-place (no vertical growth)
  --json (-j)    – emit one JSON object per sample (machine-readable)

Normalisation
  default            – divide by physical cores (best when SMT is on)
  --logical / -l     – divide by logical threads instead

Examples
  sudo python3 rapl_power.py
  sudo python3 rapl_power.py -l 0.5 --max-lines 30
  sudo python3 rapl_power.py --fullscreen
  sudo python3 rapl_power.py --logical --json | jq

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
CPU_TOPOLOGY_GLOB = "/sys/devices/system/cpu/cpu[0-9]*"

_cpu_re = re.compile(r"cpu(\d+)")
CSI = "\033["  # ANSI control-sequence introducer


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


def threads_and_physical_cores_by_socket() -> tuple[
    Dict[int, List[int]], Dict[int, set[int]]
]:
    """
    Return two mappings:
      • socket → list of logical CPU ids
      • socket → set of physical core ids
    """
    threads: Dict[int, List[int]] = defaultdict(list)
    phys: Dict[int, set[int]] = defaultdict(set)

    for cpu_dir in glob.glob(CPU_TOPOLOGY_GLOB):
        cpu = cpu_id_from_path(cpu_dir)

        topo_dir = os.path.join(cpu_dir, "topology")
        try:
            with open(os.path.join(topo_dir, "physical_package_id")) as f:
                socket = int(f.read().strip())
            with open(os.path.join(topo_dir, "core_id")) as f:
                core_id = int(f.read().strip())
        except FileNotFoundError:
            continue  # topology not available

        threads[socket].append(cpu)
        phys[socket].add(core_id)

    return threads, phys


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
    return 0  # cpufreq not available


# --------------------------------------------------------------------------- #
# Terminal helpers                                                            #
# --------------------------------------------------------------------------- #
def clear_screen() -> None:
    sys.stdout.write(CSI + "2J" + CSI + "H")


def cursor_up(lines: int) -> None:
    if lines > 0:
        sys.stdout.write(CSI + f"{lines}A")


# --------------------------------------------------------------------------- #
# Main sampling loop                                                          #
# --------------------------------------------------------------------------- #
def sample(
    interval: float,
    json_mode: bool,
    logical: bool,
    max_lines: int | None,
    fullscreen: bool,
) -> None:
    if json_mode and (max_lines or fullscreen):
        raise SystemExit("JSON mode is incompatible with --max-lines / --fullscreen")

    pkgs = list_packages()
    if not pkgs:
        raise RuntimeError("No RAPL package zones found – is this an Intel CPU?")

    fds = {pkg: os.open(os.path.join(pkg, "energy_uj"), os.O_RDONLY) for pkg in pkgs}
    ranges = {pkg: read_max_range_uj(pkg) for pkg in pkgs}
    last_energy = {pkg: read_energy_uj(fd) for pkg, fd in fds.items()}
    last_time_ns = time.monotonic_ns()

    threads_map, phys_map = threads_and_physical_cores_by_socket()

    # SMT hint when user chooses logical mode
    hyper = any(len(threads_map[s]) > len(phys_map[s]) for s in threads_map)
    if hyper and logical and not json_mode:
        print(
            "[hint] SMT detected – using logical-thread normalisation "
            "(power divided by logical threads).\n"
        )

    core_label = "l-core" if logical else "p-core"
    header = (
        f"{'Socket':>6} | {'Pkg W':>7} | "
        f"{'W/' + core_label:>8} | {'Avg MHz':>8} | {'µW/MHz':>13}"
    )

    if not json_mode:
        if fullscreen:
            clear_screen()
        print(header)
        print("-" * len(header))
        printed_rows = 0

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
            if new_energy < old_energy:  # wrap-around
                new_energy += rng
            diff_j = (new_energy - old_energy) / 1e6
            last_energy[pkg] = new_energy
            power_w = diff_j / dt

            socket = int(pkg.split(":")[1].split("/")[0])
            logical_list = threads_map.get(socket, [])
            phys_set = phys_map.get(socket, set())

            ncores = len(logical_list) if logical else len(phys_set)
            ncores = ncores or 1  # avoid div-zero

            freqs_mhz = [
                read_freq_khz(c) / 1000
                for c in logical_list
                if read_freq_khz(c)
            ]
            avg_mhz = sum(freqs_mhz) / len(freqs_mhz) if freqs_mhz else 0

            w_per_core = power_w / ncores
            uw_per_mhz = (w_per_core * 1e6) / avg_mhz if avg_mhz else 0

            if json_mode:
                measurements[str(socket)] = {
                    "pkg_w": round(power_w, 3),
                    "w_per_core": round(w_per_core, 4),
                    "avg_mhz": round(avg_mhz),
                    "uw_per_mhz": round(uw_per_mhz, 1),
                }
            else:
                line = (
                    f"{socket:6} | {power_w:4.2f} W |  {w_per_core:4.3f} W | "
                    f"{avg_mhz:4.0f} MHz | {uw_per_mhz:6.1f} µW/MHz"
                )
                print(line)
                printed_rows += 1

        if json_mode:
            blob = {
                "timestamp": time.time(),
                "interval": interval,
                "core_mode": "logical" if logical else "physical",
                "sockets": measurements,
            }
            print(json.dumps(blob))

        elif fullscreen:
            cursor_up(len(pkgs))

        elif max_lines and printed_rows >= max_lines:
            clear_screen()
            print(header)
            print("-" * len(header))
            printed_rows = 0

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
        "-l", "--logical",
        action="store_true",
        help="divide power by logical threads instead of physical cores",
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
        default=20,
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
            logical=args.logical,
            max_lines=args.max_lines,
            fullscreen=args.fullscreen,
        )
    except KeyboardInterrupt:
        pass
