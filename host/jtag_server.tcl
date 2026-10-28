# jtag_server.tcl -- System Console side of the JTAG viewer (host/viewer.py starts it; do not run by hand).
# Claims the JTAG-to-Avalon master of quartus/ip/jtag_host and serves line commands on stdin:
#   R <byte_addr>            -> "OK <value>"              (one 32-bit read)
#   W <byte_addr> <value>    -> "OK"                      (one 32-bit write)
#   B <byte_addr> <n>        -> "OK <v0> <v1> ... <vn-1>" (n consecutive 32-bit reads)
#   Q                        -> release the master and end the script (System Console has no `exit`)
# Errors: "ERR <message>". Values are 0x-prefixed hex. The first line printed is "READY <service path>" or
# "ERR no JTAG master found".

proc reply {s} { puts stdout $s; flush stdout }

set paths [get_service_paths master]
set m ""
foreach p $paths {
    # the JTAG-to-Avalon master of this design; skip the HPS / other masters if any
    if {[string match -nocase "*phy_*" $p] || [string match -nocase "*jtag*master*" $p]} { set m $p; break }
}
if {$m eq "" && [llength $paths] > 0} { set m [lindex $paths 0] }
set running 1
if {$m eq ""} {
    reply "ERR no JTAG master found (is the build with the viewer loaded? board on USB?)"
    set running 0
} else {
    set cm [claim_service master $m thermal_viewer ""]
    reply "READY $m"
}

while {$running && [gets stdin line] >= 0} {
    set f [split [string trim $line]]
    set op [lindex $f 0]
    if {[catch {
        switch -- $op {
            R { reply "OK [master_read_32 $cm [lindex $f 1] 1]" }
            W { master_write_32 $cm [lindex $f 1] [lindex $f 2]; reply "OK" }
            B {
                set a [lindex $f 1]; set n [lindex $f 2]; set out {}
                # chunks keep each JTAG transaction a moderate size
                while {$n > 0} {
                    set k [expr {$n > 4096 ? 4096 : $n}]
                    lappend out {*}[master_read_32 $cm $a $k]
                    set a [expr {$a + 4 * $k}]; set n [expr {$n - $k}]
                }
                reply "OK [join $out { }]"
            }
            Q { close_service master $cm; set running 0; reply "OK" }
            default { reply "ERR unknown command '$op'" }
        }
    } msg]} { reply "ERR $msg" }
}
