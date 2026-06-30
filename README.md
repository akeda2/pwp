# pwp
Read and print rapl values
## Usage
```
usage: pwp.py [-h] [-l] [-m N | -M | -j] [-f] [-N] [-c COST_PER_KWH]
              [interval]

Lightweight RAPL power monitor (per socket/core/MHz).

positional arguments:
  interval           sampling interval in seconds (default: 1.0)

options:
  -h, --help         show this help message and exit
  -l, --logical      divide power by logical threads instead of physical cores
  -m, --max-lines N  print at most N lines, (default: 20) (table mode only)
  -M, --no-max       Continuously print without clearing screen
  -j, --json         output each sample as a JSON object (disables table modes)
  -f, --fullscreen   rewrite new data in place (no vertical growth)
  -N, --no-roll      Do not roll output
  -c, --cost COST_PER_KWH
          Cost per kWh in your currency (default: 1.5)
```
## Output
```
Socket |    Pkg W | W/p-core |   Avg MHz |        µW/MHz |        kWh/d |   Cost/d
====================================================================================
  0 |  16.29 W |  4.072 W |  3238 MHz | 1257.7 µW/MHz |  0.391 kWh/d |  0.59 /d
  0 |  14.29 W |  3.572 W |  3260 MHz | 1095.9 µW/MHz |  0.343 kWh/d |  0.51 /d
  0 |  16.65 W |  4.163 W |  2455 MHz | 1695.6 µW/MHz |  0.400 kWh/d |  0.60 /d
```
