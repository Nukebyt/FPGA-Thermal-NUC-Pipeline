#!/usr/bin/env bash
# Regenerate the Platform Designer system quartus/ip/jtag_host (JTAG-to-Avalon master + MM bridge, exported master).
# Output: quartus/ip/jtag_host/jtag_host/synthesis/jtag_host.qip (added to quartus/thermal/thermal.qsf).
set -euo pipefail
export PATH="/c/intelFPGA_lite/21.1/quartus/sopc_builder/bin:/c/intelFPGA_lite/21.1/quartus/bin64:$PATH"
cd "$(dirname "$0")/../quartus/ip/jtag_host"
qsys-script --script=make_jtag_host.tcl > qsys_script.log 2>&1
qsys-generate jtag_host.qsys --synthesis=VERILOG --output-directory=. --family="Cyclone V" --part=5CSXFC6D6F31C6 > qsys_generate.log 2>&1
grep -q "qsys-generate succeeded" qsys_generate.log && echo "jtag_host generated"
