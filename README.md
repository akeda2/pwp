# pwp
Read and print rapl values
## Usage
```
usage: pwp [-h] [-l] [-j] [-m N] [--fullscreen] [interval]
Lightweight RAPL power monitor (per socket/core/MHz).
positional arguments:
  interval           sampling interval in seconds (default: 1.0)                                                                          
options:                                                               -h, --help         show this help message and exit                 
  -l, --logical      divide power by logical threads instead of                           physical cores                                  
  -j, --json         output each sample as a JSON object (disables                        table modes)                                    
  -m, --max-lines N  print at most N lines, (default: 20) (table                          mode only)                                      
  --fullscreen       rewrite new data in place (no vertical growth)  
```
## Output
```
Socket |   Pkg W | W/p-core |  Avg MHz |        µW/MHz               ======================================================               
     0 | 20.86 W |  5.215 W | 3725 MHz | 1399.7 µW/MHz                    0 | 21.34 W |  5.336 W | 2750 MHz | 1940.2 µW/MHz               
     0 | 20.93 W |  5.232 W | 2263 MHz | 2312.4 µW/MHz                    0 | 21.22 W |  5.304 W | 3726 MHz | 1423.6 µW/MHz               
     0 | 20.80 W |  5.201 W | 3725 MHz | 1396.1 µW/MHz                    0 | 20.84 W |  5.209 W | 2750 MHz | 1894.3 µW/MHz               
     0 | 20.56 W |  5.140 W | 3238 MHz | 1587.5 µW/MHz                    0 | 21.24 W |  5.309 W | 3238 MHz | 1639.9 µW/MHz               
     0 | 20.92 W |  5.230 W | 2263 MHz | 2311.6 µW/MHz
```
