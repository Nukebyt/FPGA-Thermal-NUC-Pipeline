# Platform Designer system "jtag_host": JTAG-to-Avalon master -> MM bridge whose master side is exported to the RTL
# (thermal_top -> thermal_sys.host_if). Regenerate with scripts/gen_jtag_host.sh; do not edit the .qsys by hand.
package require -exact qsys 16.1
create_system jtag_host
set_project_property DEVICE_FAMILY "Cyclone V"
set_project_property DEVICE 5CSXFC6D6F31C6

add_instance clk clock_source
set_instance_parameter_value clk clockFrequency 25000000
set_instance_parameter_value clk clockFrequencyKnown true
set_instance_parameter_value clk resetSynchronousEdges DEASSERT

add_instance master altera_jtag_avalon_master

add_instance bridge altera_avalon_mm_bridge
set_instance_parameter_value bridge DATA_WIDTH 32
set_instance_parameter_value bridge SYMBOL_WIDTH 8
set_instance_parameter_value bridge ADDRESS_WIDTH 19
set_instance_parameter_value bridge ADDRESS_UNITS SYMBOLS
set_instance_parameter_value bridge MAX_BURST_SIZE 1
set_instance_parameter_value bridge MAX_PENDING_RESPONSES 4
set_instance_parameter_value bridge PIPELINE_COMMAND 1
set_instance_parameter_value bridge PIPELINE_RESPONSE 1

add_connection clk.clk master.clk
add_connection clk.clk bridge.clk
add_connection clk.clk_reset master.clk_reset
add_connection clk.clk_reset bridge.reset
add_connection master.master bridge.s0
set_connection_parameter_value master.master/bridge.s0 baseAddress 0x0000

add_interface clk clock sink
set_interface_property clk EXPORT_OF clk.clk_in
add_interface reset reset sink
set_interface_property reset EXPORT_OF clk.clk_in_reset
add_interface host avalon master
set_interface_property host EXPORT_OF bridge.m0

save_system jtag_host.qsys
