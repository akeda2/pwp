# pwp
Read and print rapl values
## Usage
```
usage: pwp [-h] [-l] [-j] [-m N] [-f] [-N] [interval]

Lightweight RAPL power monitor (per socket/core/MHz).

positional arguments:
  interval           sampling interval in seconds (default: 1.0)

options:
  -h, --help         show this help message and exit
  -l, --logical      divide power by logical threads instead of physical cores
  -j, --json         output each sample as a JSON object (disables table modes)
  -m, --max-lines N  print at most N lines, (default: 20) (table mode only)
  -f, --fullscreen   rewrite new data in place (no vertical growth)
  -N, --no-roll      Do not roll output
```
## Output
```
Socket |    Pkg W | W/p-core |   Avg MHz |        µW/MHz
========================================================
     0 |  16.29 W |  4.072 W |  3238 MHz | 1257.7 µW/MHz
     0 |  14.29 W |  3.572 W |  3260 MHz | 1095.9 µW/MHz
     0 |  16.65 W |  4.163 W |  2455 MHz | 1695.6 µW/MHz
     0 |  13.75 W |  3.437 W |  2706 MHz | 1270.4 µW/MHz
     0 |  16.34 W |  4.085 W |  3238 MHz | 1261.9 µW/MHz
     0 |  10.84 W |  2.709 W |  1775 MHz | 1526.0 µW/MHz
```
