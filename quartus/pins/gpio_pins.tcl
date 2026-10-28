# Two scope/logic-analyser marker pins on the GPIO_0 header (roadmap 6.5). Source: Terasic DE10-Standard golden top
# (platform_setup.tcl): GPIO[0] = PIN_W15 (header pin 1), GPIO[1] = PIN_AK2 (header pin 2), 3.3-V LVTTL.
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to GPIO[0]
set_instance_assignment -name IO_STANDARD "3.3-V LVTTL" -to GPIO[1]
set_location_assignment PIN_W15 -to GPIO[0]
set_location_assignment PIN_AK2 -to GPIO[1]
