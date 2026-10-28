# thermal.sdc
create_clock -name CLOCK_50 -period 20.000 [get_ports CLOCK_50]

# Checklist 2.2/2.6: every PLL needs derive_pll_clocks, or its whole domain is silently unconstrained.
# Must come after create_clock and before derive_clock_uncertainty. scripts/check_sta.py also requires the PLL clock
# name to APPEAR in the slack tables.
derive_pll_clocks

# JTAG (USB-Blaster II, 24 MHz max; JTAG-to-Avalon master of quartus/ip/jtag_host). Its logic crosses into clk25
# through the master's own synchronisers, so the JTAG clock is asynchronous to every other clock.
create_clock -name altera_reserved_tck -period 41.667 [get_ports altera_reserved_tck]
set_clock_groups -asynchronous -group [get_clocks altera_reserved_tck]

derive_clock_uncertainty

# Human-speed / debug IO: not timing-relevant.
set_false_path -from [get_ports {KEY[*] SW[*]}]
set_false_path -to   [get_ports {LEDR[*] HEX0[*] HEX1[*] HEX2[*] HEX3[*] HEX4[*] HEX5[*] GPIO[*]}]

# VGA outputs are not constrained against the ADV7123 setup/hold (same PLL clock for data and VGA_CLK, 40 ns/cycle).
# Documented gap (docs/board_notes.md): add set_output_delay if the image shows edge artefacts.
