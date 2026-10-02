proc g {h p} {if {$h eq "" || $h eq "0"} {return ""}; if {[catch {npi_get_str -property $p -object $h} v]} {return ""}; return $v}
proc rel {h p} {if {$h eq "" || $h eq "0"} {return ""}; if {[catch {npi_handle -type $p -refHandle $h} v]} {return ""}; return $v}
proc lsrel {h p} {
    set r {}; if {[catch {npi_iterate -type $p -refHandle $h} it] || $it eq "" || $it eq "0"} {return $r}
    while {[set x [npi_scan -iterator $it]] ne "" && $x ne "0"} {lappend r $x}; return $r
}
proc show {h depth} {
    if {$h eq "" || $h eq "0" || $depth > 5} {return}
    set lead [string repeat {  } $depth]
    set line "$lead$h"
    foreach p {npiType npiName npiFullName npiDefName npiDirection} {append line " $p=[g $h $p]"}
    foreach p {npiSize npiPacked npiSigned npiArrayType} {catch {append line " $p=[npi_get -property $p -object $h]"}}
    puts $line
    if {$depth==5} {return}
    foreach r {npiLowConn npiActual npiExpr npiTypespec npiElemTypespec npiBaseTypespec npiParent} {
        set x [rel $h $r]; if {$x ne "" && $x ne "0" && $r ne "npiParent"} {puts "$lead$r:"; show $x [expr {$depth+1}]}
    }
    foreach r {npiRange npiMember npiOperand npiMpPort npiArrayMember} {
        foreach x [lsrel $h $r] {puts "$lead$r:"; show $x [expr {$depth+1}]}
    }
}
if {[catch {
    debImport -elab $env(PROBE_KDB)
    foreach path [split $env(PROBE_NAMES) ,] {
        puts "PATH $path"
        show [npi_handle_by_name -name $path -scope ""] 0
    }
} e]} {puts "ERROR $e"}
debExit
