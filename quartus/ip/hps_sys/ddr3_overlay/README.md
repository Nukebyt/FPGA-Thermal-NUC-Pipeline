# DDR3 overlay for quartus/ip/hps_sys

`qsys-generate` of an HPS system fails on this machine in the DDR3 sequencer step (`uniphy_mcc.exe` / the Nios II `make all`
crashes, the same failure that the Weibull-CFAR project documents as its bug #21) and then silently leaves out the memory-controller
sources, the two sequencer ROMs and three sequencer headers. Their content depends only on the HPS DDR3 configuration, and `hps_0`
is taken over unchanged from the proven `soc_system.qsys` of that project, so the files it generated for that configuration
(`matlab/de10_ghrd/soc_system/synthesis/submodules`) are copied here verbatim:

* `altera_mem_if_{dll,oct,hard_memory_controller_top}_cyclonev.sv`, `hps_AC_ROM.hex`, `hps_inst_ROM.hex`
* `sequencer/sequencer_auto.pre.h`, `sequencer_auto_ac_init.pre.c`, `sequencer_auto_inst_init.pre.c`
* `hps_sys_mm_interconnect_0_avalon_st_adapter_error_adapter_0.sv`: the interconnect's Avalon-ST error adapter, another module the failed run never
  generated (same 34-bit / 1-bit-error parameters as the reference's copy; module name translated)
* `qip_lines.txt`: the `.qip` lines that reference them (system name translated to `hps_sys`)

`scripts/gen_hps_sys.sh` applies the overlay after `qsys-generate` (copy the files, append the missing `.qip` lines).
