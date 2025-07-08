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
```Socket |   Pkg W | W/p-core |  Avg MHz |        µW/MHz               
------------------------------------------------------               
     0 | 0.67 W |  0.333 W | 1686 MHz |  197.7 µW/MHz                
     0 | 2.26 W |  1.128 W | 1673 MHz |  673.8 µW/MHz                
     0 | 0.98 W |  0.489 W | 1025 MHz |  477.5 µW/MHz                
     0 | 0.55 W |  0.275 W |  400 MHz |  686.6 µW/MHz                
     0 | 1.29 W |  0.647 W | 2324 MHz |  278.5 µW/MHz                
     0 | 1.61 W |  0.806 W | 2316 MHz |  348.3 µW/MHz                
     0 | 1.66 W |  0.831 W | 2314 MHz |  359.3 µW/MHz                
     0 | 2.20 W |  1.100 W | 2947 MHz |  373.2 µW/MHz                
     0 | 1.77 W |  0.884 W | 2306 MHz |  383.3 µW/MHz                
     0 | 1.76 W |  0.879 W | 2962 MHz |  296.7 µW/MHz
```
