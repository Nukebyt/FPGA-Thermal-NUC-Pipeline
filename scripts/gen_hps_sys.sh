#!/usr/bin/env bash
# Regenerate the Platform Designer system quartus/ip/hps_sys (HPS + JTAG master -> exported host bus).
# Output: quartus/ip/hps_sys/hps_sys/synthesis/hps_sys.qip (used by quartus/thermal_soc/thermal_soc.qsf).
# qsys-generate reports errors in the HPS DDR3 sequencer step on this machine; scripts/fix_hps_sys.py applies
# quartus/ip/hps_sys/ddr3_overlay (see its README) and verifies that nothing else is wrong.
set -uo pipefail
export PATH="/c/intelFPGA_lite/21.1/quartus/sopc_builder/bin:/c/intelFPGA_lite/21.1/quartus/bin64:$PATH"
cd "$(dirname "$0")/../quartus/ip/hps_sys"
rm -rf hps_sys
qsys-script --script=make_hps_sys.tcl > qsys_script.log 2>&1 || { echo "qsys-script failed"; exit 1; }
qsys-generate hps_sys.qsys --synthesis=VERILOG --output-directory=. --family="Cyclone V" --part=5CSXFC6D6F31C6 > qsys_generate.log 2>&1
cd ../../..
python scripts/fix_hps_sys.py && echo "hps_sys generated"
