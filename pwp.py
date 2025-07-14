#!/usr/bin/env -S python3 -u
"""
pwp  –  Lightweight Intel RAPL power monitor

Outputs (per socket):
  • Package power (W)
  • Power per PHYSICAL core   (default)   or per logical thread (use -l)
  • Average effective clock (MHz)
  • Power per core per MHz (µW / MHz)

Display modes
  default             – append rows forever
  -m / --max-lines N  – keep at most N data rows, then clear screen & redraw header
  -M, --no-max        - continuously print without clearing screen
  -f / --fullscreen   – rewrite the same rows in-place (no vertical growth)
  --json (-j)         – emit one JSON object per sample (machine-readable)

Normalisation
  default             – divide by physical cores (best when SMT is on)
  --logical / -l      – divide by logical threads instead

Examples
  sudo python3 pwp
  sudo python3 pwp -l 0.5 --max-lines 30
  sudo python3 pwp --fullscreen
  sudo python3 pwp --logical --json | jq

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

# ------- fixed column widths (incl. units) ---------------------------------
COL_SOCKET   = 6
COL_PKG      = 9   # "9999.99 W"
COL_CORE     = 9   # "  12.345 W"
COL_AVG_MHZ  = 9   # "  4200 MHz"
COL_UW_MHZ   = 14   # " 1234.5 µW/MHz"
COL_KW_HOUR  = 12  # "  0.123 kWh/d"
COL_COST_DAY = 8   # "  1.12 /d"

_cpu_re = re.compile(r"cpu(\d+)")
CSI = "\033["  # ANSI control-sequence introducer


# --------------------------------------------------------------------------- #
# Helper functions                                                            #
# --------------------------------------------------------------------------- #
def cell(num_str: str, unit: str, width: int) -> str:
    """Return '<num> <unit>' right-justified to *width*."""
    return f"{num_str} {unit}".rjust(width)

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
    return pkgs[::-1]


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

def calculate_kwh_per_day(power_w: float) -> float:
    return power_w * 24 / 1000 

# --------------------------------------------------------------------------- #
# Terminal helpers                                                            #
# --------------------------------------------------------------------------- #
def clear_screen() -> None:
    sys.stdout.write(CSI + "2J" + CSI + "H")


def cursor_up(lines: int) -> None:
    if lines > 0:
        sys.stdout.write(CSI + f"{lines}A")

def s_print(text, interval: float=1, delay: float=0.006):
    # Prints text one character at a time, with a delay between each character
    
    if interval > 4:
        delay_interval = 4
        interval_rest = interval - delay_interval
    else:
        delay_interval = interval
    delay = delay_interval/79

    for char in text:
        print(char, end='', flush=True)
        time.sleep(delay)
    print()
    if interval > 4:
        time.sleep(interval_rest)
# --------------------------------------------------------------------------- #
# Main sampling loop                                                          #
# --------------------------------------------------------------------------- #
def sample(
    interval: float,
    json_mode: bool,
    logical: bool,
    max_lines: int | None,
    fullscreen: bool,
    no_roll: bool,
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
    """header = (
        f"{'Socket':>6} | {'Pkg W':>7} | "
        f"{'W/' + core_label:>8} | {'Avg MHz':>8} | {'µW/MHz':>13}"
    )"""
    header = (
        f"{'Socket':>{COL_SOCKET}} |"
        f"{'Pkg W':>{COL_PKG}} |"
        f"{'W/' + core_label:>{COL_CORE}} |"
        f"{'Avg MHz':>{COL_AVG_MHZ}} |"
        f"{'µW/MHz':>{COL_UW_MHZ}} |"
        f"{'kWh/d':>{COL_KW_HOUR}} |"
        f"{'Cost/d':>{COL_COST_DAY}}"
    )

    if not json_mode:
        if fullscreen:
            clear_screen()
        print(header)
        print("=" * len(header))
        printed_rows = 0

    first = True
    while True:
        if no_roll or json_mode or first:
            time.sleep(interval)
            first = False
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

            kwh_per_day = calculate_kwh_per_day(power_w)
            cost_per_day = kwh_per_day * args.cost

            if json_mode:
                measurements[str(socket)] = {
                    "pkg_w": round(power_w, 3),
                    "w_per_core": round(w_per_core, 4),
                    "avg_mhz": round(avg_mhz),
                    "uw_per_mhz": round(uw_per_mhz, 1),
                    "kwh_per_day": round(kwh_per_day, 3),
                    "cost_per_day": round(cost_per_day, 3),
                }
            else:
                """line = (
                    f"{socket:6} | {power_w:4.2f} W |  {w_per_core:4.3f} W | "
                    f"{avg_mhz:4.0f} MHz | {uw_per_mhz:6.1f} µW/MHz"
                )"""
                line = (
                    f"{socket:>{COL_SOCKET}} |"
                    f"{cell(f'{power_w:5.2f}', 'W',           COL_PKG)} |"
                    f"{cell(f'{w_per_core:5.3f}',  'W',       COL_CORE)} |"
                    f"{cell(f'{avg_mhz:4.0f}',   'MHz',       COL_AVG_MHZ)} |"
                    f"{cell(f'{uw_per_mhz:7.1f}',  'µW/MHz',  COL_UW_MHZ)} |"
                    f"{cell(f'{kwh_per_day:5.3f}', 'kWh/d',   COL_KW_HOUR)} |"
                    f"{cell(f'{cost_per_day:5.2f}', '/d',   COL_COST_DAY)}"
                )
                if not no_roll:
                    pkg_interval = interval
                    #print(pkgs)
                    #print(pkg)
                    if len(pkgs) > 1:
                        #print(pkgs)
                        pkg_interval /= len(pkgs)
                        #print(pkg_interval)
                    s_print(line, pkg_interval)
                else:
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
            print("=" * len(header))
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
    maxlines = parser.add_mutually_exclusive_group()
    maxlines.add_argument(
        "-m", "--max-lines",
        type=int,
        metavar="N",
        default=20,
        help="print at most N lines, (default: 20) "
             "(table mode only)",
    )
    maxlines.add_argument(
        "-M", "--no-max",
        action="store_true",
        help="Continuously print without clearing screen",
    )
    maxlines.add_argument(
        "-j", "--json",
        action="store_true",
        help="output each sample as a JSON object (disables table modes)",
    )
    parser.add_argument(
        "-f", "--fullscreen",
        action="store_true",
        help="rewrite new data in place (no vertical growth)",
    )
    parser.add_argument(
        "-N", "--no-roll",
        action="store_true",
        help="Do not roll output",
    )
    parser.add_argument(
        "-c", "--cost",
        type=float,
        metavar="COST_PER_KWH",
        default=1.5,
        help="Cost per kWh in your currency (default: 1.5)",
    )
    args = parser.parse_args()
    if args.no_max or args.json:
        args.max_lines = False
    if args.fullscreen:
        args.no_roll = True

    try:
        sample(
            interval=args.interval,
            json_mode=args.json,
            logical=args.logical,
            max_lines=args.max_lines,
            fullscreen=args.fullscreen,
            no_roll=args.no_roll,
        )
    except KeyboardInterrupt:
        pass
