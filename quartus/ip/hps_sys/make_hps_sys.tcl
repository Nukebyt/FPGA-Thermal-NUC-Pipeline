# Platform Designer system "hps_sys" (roadmap 3b): the proven DE10-Standard HPS (hps_0, DDR3, SD, Ethernet, UART ...) with its
# lightweight HPS-to-FPGA bridge AND a JTAG-to-Avalon master both driving one exported Avalon master (the host bus of
# rtl/host_if.v). Superset of quartus/ip/jtag_host: the JTAG viewer keeps working, and the ARM (Linux, /dev/mem at
# 0xFF200000) reaches the same CSRs, capture buffer and scene feed buffer.
#
# Starting point: ref_soc_system.qsys = the Weibull-CFAR project's soc_system.qsys (matlab/de10_ghrd), a Terasic-GHRD-derived
# system whose HPS configuration is proven on this board (Linux boots from its SD card with the preloader built from it).
# The hps_0 instance is taken over unchanged so the preloader/U-Boot already on that card still match the HPS configuration
# (DDR3 timing, pin muxing, bridge enables). Everything else in the reference (PIOs, CFAR bridge, JTAG masters) is removed.
# Regenerate with scripts/gen_hps_sys.sh; do not edit the .qsys by hand.
package require -exact qsys 16.1
load_system ref_soc_system.qsys

foreach i {ILC button_pio cfar_bridge_0 dipsw_pio f2sdram_only_master fpga_only_master hps_only_master jtag_uart led_pio sysid_qsys} {
    remove_instance $i
}
set_instance_parameter_value clk_0 clockFrequency 25000000

# JTAG master next to the HPS lightweight master; Platform Designer arbitrates both onto the bridge
add_instance jtag_master altera_jtag_avalon_master
add_connection clk_0.clk jtag_master.clk
add_connection clk_0.clk_reset jtag_master.clk_reset
add_connection jtag_master.master mm_bridge_0.s0
set_connection_parameter_value jtag_master.master/mm_bridge_0.s0 baseAddress 0x0000

# bridge: 19-bit byte address (CSRs 0x00000, capture buffer 0x20000, scene feed buffer 0x40000), master side exported
set_instance_parameter_value mm_bridge_0 USE_AUTO_ADDRESS_WIDTH 0
set_instance_parameter_value mm_bridge_0 ADDRESS_WIDTH 19
add_interface host avalon master
set_interface_property host EXPORT_OF mm_bridge_0.m0

puts "INSTANCES: [get_instances]"
foreach c [get_connections] { puts "CONN $c" }
save_system hps_sys.qsys
