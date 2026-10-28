#!/usr/bin/env bash
# Quartus synthesis probe of one module (checklist 1.9: probe every new module with quartus_map, seconds-to-minutes,
# before committing to a full build).  Usage: scripts/probe_map.sh <top_entity> <rtl file> [<rtl file> ...]
# Creates quartus/probe_<top>/ (gitignored build products), prints wall time, resources and the warnings.
set -euo pipefail
export PATH="/c/intelFPGA_lite/21.1/quartus/bin64:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TOP="$1"; shift
D="$ROOT/quartus/probe_$TOP"
mkdir -p "$D/logs" "$D/output_files"
cd "$D"
printf 'QUARTUS_VERSION = "21.1"\nPROJECT_REVISION = "probe"\n' > probe.qpf
{
  echo 'set_global_assignment -name FAMILY "Cyclone V"'
  echo 'set_global_assignment -name DEVICE 5CSXFC6D6F31C6'
  echo "set_global_assignment -name TOP_LEVEL_ENTITY $TOP"
  echo 'set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files'
  echo 'set_global_assignment -name NUM_PARALLEL_PROCESSORS 2'
  for f in "$@"; do echo "set_global_assignment -name VERILOG_FILE ../../$f"; done
} > probe.qsf
start=$(date +%s)
quartus_map probe > logs/map.log 2>&1 || { tail -20 logs/map.log; exit 1; }
end=$(date +%s)
echo "== $TOP: quartus_map $((end-start)) s"
grep -E "Total (registers|block memory bits|DSP Blocks|pins)|Estimated|Logic utilization" output_files/probe.map.summary || true
grep -E "^Warning" logs/map.log | grep -v "18236\|Number of processors" | head -8 || true
