# Read-only design/FSDB access. Invoked by wave_init.py in a private run directory.
namespace eval wi {
    variable output
    variable file
    variable tick
    variable dump_off {}
    variable sampled [dict create]
    variable interfaces [dict create]
    variable count 0
}

proc wi::j {s} {
    set out {"}
    foreach c [split $s ""] {
        scan $c %c n
        if {$n == 34} {append out {\"}} elseif {$n == 92} {append out {\\}} \
        elseif {$n < 32} {append out [format {\u%04x} $n]} else {append out $c}
    }
    append out {"}
    return $out
}
proc wi::obj {args} {
    set a {}; foreach {k v} $args {lappend a "[j $k]:$v"}
    return "\{[join $a ,]\}"
}
proc wi::arr {xs} {return "\[[join $xs ,]\]"}
proc wi::strings {xs} {set a {}; foreach x $xs {lappend a [j $x]}; return [arr $a]}
proc wi::emit {json} {variable output; puts $output $json; flush $output}
proc wi::valid {h} {expr {$h ne "" && $h ne "0"}}
proc wi::s {h p} {
    if {![valid $h]} {return ""}
    if {[catch {npi_get_str -property $p -object $h} v]} {return ""}
    return $v
}
proc wi::n {h p {default 0}} {
    if {![valid $h] || [catch {npi_get -property $p -object $h} v] || ![string is entier -strict $v]} {return $default}
    return $v
}
proc wi::r {h kind} {
    if {![valid $h]} {return ""}
    if {[catch {npi_handle -type $kind -refHandle $h} v]} {return ""}
    return $v
}
proc wi::children {h kind} {
    set xs {}
    if {[catch {npi_iterate -type $kind -refHandle $h} it] || ![valid $it]} {return $xs}
    while {[valid [set x [npi_scan -iterator $it]]]} {lappend xs $x}
    return $xs
}
proc wi::byname {name} {return [npi_handle_by_name -name $name -scope ""]}
proc wi::constant {h} {
    if {![valid $h]} {error "constant expression unavailable"}
    set value [npi_get_value -format npiDecStrVal -object $h]
    if {![regexp {^-?[0-9]+$} $value]} {error "unresolved constant expression: $value"}
    return $value
}
proc wi::ranges {type} {
    set result {}
    foreach range [children $type npiRange] {
        lappend result [list [constant [r $range npiLeftRange]] [constant [r $range npiRightRange]]]
    }
    return $result
}
proc wi::ranges_json {rs} {set a {}; foreach range $rs {lappend a [arr $range]}; return [arr $a]}
proc wi::indices {range} {
    lassign $range l rr; set step [expr {$l <= $rr ? 1 : -1}]; set xs {}
    for {set i $l} {($step>0 && $i<=$rr) || ($step<0 && $i>=$rr)} {incr i $step} {lappend xs $i}
    return $xs
}
proc wi::actual {h} {
    set visited {}
    while {[s $h npiType] eq "npiRefObj"} {
        if {$h in $visited} {error "cyclic NPI reference"}
        lappend visited $h
        set next [r $h npiActual]
        if {![valid $next]} {error "unbound reference [s $h npiFullName]"}
        set h $next
    }
    if {[s $h npiType] eq "npiMpPort"} {return [r $h npiExpr]}
    return $h
}
proc wi::direction {h} {
    switch -- [s $h npiDirection] {
        npiInput {return input}
        npiOutput {return output}
        npiInout {return inout}
        npiRef {return ref}
        default {return unknown}
    }
}

# A shape uses elaborated ranges; npiSize on an unpacked array is an element
# count, so width must be taken from its packed leaf, not from its root.
proc wi::shape {h} {
    set type [r $h npiTypespec]; set unpacked {}; set leaf $h
    set visits {}
    while {[s $type npiType] eq "npiArrayTypespec"} {
        if {$type in $visits} {error "cyclic array type"}
        lappend visits $type
        if {[n $type npiArrayType -1] != 1} {error "dynamic/associative/queue array is unsupported"}
        set rs [ranges $type]
        if {![llength $rs]} {error "array range unavailable"}
        lappend unpacked [lindex $rs 0]
        set idx [lindex [lindex $rs 0] 0]
        set next [npi_handle_by_index -object $leaf -index $idx]
        if {![valid $next]} {set next [byname "[s $leaf npiFullName]\[$idx\]"]}
        if {![valid $next]} {error "array element unavailable"}
        set leaf $next
        set type [r $leaf npiTypespec]
    }
    set kind [s $type npiType]
    set width [n $leaf npiSize -1]
    set packed [ranges $type]
    set qualified ""
    if {[s $type npiName] ne "" && [s [r $type npiScope] npiType] eq "npiPackage"} {
        set qualified "[s [r $type npiScope] npiName]::[s $type npiName]"
    }
    set is_unpacked_struct [expr {$kind in {npiStructTypespec npiUnionTypespec} && ![n $type npiPacked]}]
    return [dict create width $width signed [n $type npiSigned] packed $packed unpacked $unpacked hdl_type [s $h npiType] \
        type $kind typedef $qualified unpacked_struct $is_unpacked_struct]
}
proc wi::shape_json {shape} {
    return [obj width [dict get $shape width] signed [dict get $shape signed] \
        packed_ranges [ranges_json [dict get $shape packed]] unpacked_ranges [ranges_json [dict get $shape unpacked]] \
        type [j [dict get $shape type]] hdl_type [j [dict get $shape hdl_type]] typedef [j [dict get $shape typedef]] \
        unpacked_struct [dict get $shape unpacked_struct]]
}

proc wi::params {scope} {
    set xs {}
    foreach p [children $scope npiParameter] {
        if {[n $p npiLocalParam]} {continue}
        set name [s $p npiName]
        if {[catch {
            set pt [s [r $p npiTypespec] npiType]
            if {$pt in {npiStringTypespec npiRealTypespec npiShortRealTypespec npiArrayTypespec}} {error "non-integral parameter"}
            set bits [string tolower [npi_get_value -format npiBinStrVal -object $p]]
            if {![regexp {^[01xz]+$} $bits]} {error "non-integral parameter"}
            set value "[string length $bits]'[expr {[n $p npiSigned] ? {sb} : {b}}]$bits"
        } why]} {set value ""}
        lappend xs [obj name [j $name] value [j $value]]
    }
    foreach p [children $scope npiTypeParameter] {
        lappend xs [obj name [j [s $p npiName]] value [j ""]]
    }
    return [arr $xs]
}

proc wi::port_description {p} {
    set low [r $p npiLowConn]
    set sh null; set why ""
    if {[catch {set sh [shape_json [shape $low]]} why]} {set sh null} else {set why ""}
    return [obj name [j [s $p npiName]] direction [j [direction $p]] \
        port_type [j [s $p npiPortType]] shape $sh shape_error [j $why]]
}
proc wi::interface_metadata {h} {
    variable interfaces
    set name [s $h npiFullName]
    if {$name eq ""} {error "interface instance path unavailable"}
    if {[dict exists $interfaces $name]} {return}
    dict set interfaces $name 1
    set ps {}
    foreach p [children $h npiPort] {
        lappend ps [port_description $p]
        if {[direction $p] in {input inout}} {
            expand [r $p npiLowConn] "$name.[s $p npiName]" [s $p npiName] [direction $p] "" $name interface_constructor
        }
    }
    set array [r $h npiInstanceArray]; set ar {}; set ap ""
    if {[valid $array]} {set ar [ranges $array]; set ap [s $array npiFullName]}
    emit [obj kind [j interface] path [j $name] definition [j [s $h npiDefName]] \
        parameters [params $h] ports [arr $ps] array_path [j $ap] array_ranges [ranges_json $ar]]
}

# Return an expression tree of actual design objects. No source-text direction
# guessing and no arithmetic evaluation by Tcl eval is used.
proc wi::expression {h {depth 0}} {
    if {$depth>64} {error "expression nesting exceeds 64"}
    set h [actual $h]
    set kind [s $h npiType]
    if {$kind in {npiConstant npiParameter npiParameterBit}} {
        set b [string tolower [npi_get_value -format npiBinStrVal -object $h]]
        if {![regexp {^[01xz]+$} $b]} {error "nonintegral constant"}
        return [dict create kind constant width [string length $b] value $b]
    }
    if {$kind eq "npiOperation"} {
        set op [s $h npiOpType]
        if {$op ne "npiConcatOp"} {error "unsupported modport expression operation $op"}
        set operands {}; set width 0
        foreach x [children $h npiOperand] {
            set ex [expression $x [expr {$depth+1}]]
            incr width [dict get $ex width]; lappend operands $ex
        }
        return [dict create kind concat width $width operands $operands]
    }
    if {$kind in {npiPartSelect npiNetBit npiRegBit npiVarSelect npiNetSelect}} {
        set parent [r $h npiParent]
        if {[valid $parent]} {
            set ex [expression $parent [expr {$depth+1}]]
            set l [r $h npiLeftRange]; set rr [r $h npiRightRange]
            if {[valid $l] && [valid $rr]} {
                set left [constant $l]; set right [constant $rr]
            } else {
                set left [constant [r $h npiIndex]]; set right $left
            }
            set shp [shape $parent]
            set ranges [dict get $shp packed]
            if {![llength $ranges]} {set ranges [list [list [expr {[dict get $ex width]-1}] 0]]}
            lassign [lindex $ranges 0] pl pr
            set stride [expr {[dict get $ex width] / (abs($pl-$pr)+1)}]
            set offsets {}; set size 0
            foreach idx [indices [list $left $right]] {
                if {$idx < min($pl,$pr) || $idx > max($pl,$pr)} {error "selection out of range"}
                set start [expr {abs($idx-$pl)*$stride}]
                for {set i 0} {$i<$stride} {incr i} {lappend offsets [expr {$start+$i}]; incr size}
            }
            set suffix [expr {$left==$right ? "\[$left\]" : "\[$left:$right\]"}]
            return [dict create kind select width $size parent $ex offsets $offsets suffix $suffix]
        }
    }
    set path [s $h npiFullName]
    set width [n $h npiSize -1]
    set type [s [r $h npiTypespec] npiType]
    if {$path eq "" || $width<1 || $type in {npiRealTypespec npiShortRealTypespec npiStringTypespec npiClassTypespec npiVirtualInterfaceTypespec}} {
        error "unsupported data object $kind ($path, $type)"
    }
    return [dict create kind signal width $width path $path]
}
proc wi::expr_json {e} {
    set kind [dict get $e kind]
    set args [list kind [j $kind] width [dict get $e width]]
    switch -- $kind {
        signal {lappend args path [j [dict get $e path]]}
        constant {lappend args value [j [dict get $e value]]}
        concat {set xs {}; foreach x [dict get $e operands] {lappend xs [expr_json $x]}; lappend args operands [arr $xs]}
        select {lappend args parent [expr_json [dict get $e parent]] offsets [arr [dict get $e offsets]] suffix [j [dict get $e suffix]]}
    }
    return [obj {*}$args]
}

proc wi::read_bits {sig {depth 0}} {
    variable tick
    if {$depth>32} {error "FSDB composite nesting exceeds 32"}
    if {[npi_fsdb_sig_property -type npiFsdbSigHasMember -sig $sig]} {
        set ct [npi_fsdb_sig_property -type npiFsdbSigCompositeType -sig $sig]
        set it [npi_fsdb_iter_member -sig $sig]
        set value ""; set changed ""; set count 0
        while {[valid [set member [npi_fsdb_iter_sig_next -iter $it]]]} {
            set r [read_bits $member [expr {$depth+1}]]
            if {[dict get $r status] ne "ok"} {catch {npi_fsdb_iter_sig_stop -iter $it}; return $r}
            incr count
            append value [dict get $r value]
            set t [dict get $r change_tick]
            if {$t ne "" && ($changed eq "" || $t>$changed)} {set changed $t}
            # npiFsdbSigCtUnion == 2. Union fields overlap, unlike struct/array
            # fields: concatenating all of them would double the packed width.
            if {$ct == 2} {catch {npi_fsdb_iter_sig_stop -iter $it}; break}
        }
        if {$count} {return [dict create status ok value $value change_tick $changed]}
    }
    set vct [npi_fsdb_create_vct -sig $sig]
    set result [dict create status unsupported_type value "" change_tick ""]
    if {![valid $vct]} {return $result}
    set code [catch {
        if {![npi_fsdb_goto_time -vct $vct -time $tick]} {
            dict set result status no_initial_value
        } else {
            set changed [npi_fsdb_vct_time -vct $vct]
            if {$changed > $tick} {
                dict set result status no_initial_value
            } else {
                set value [string tolower [npi_fsdb_vct_value -vct $vct -format npiFsdbBinStrVal]]
                if {[regexp {^[01xz]+$} $value]} {
                    dict set result status ok; dict set result value $value; dict set result change_tick $changed
                }
            }
        }
    } why]
    npi_fsdb_release_vct -vct $vct
    if {$code} {error $why}
    return $result
}
proc wi::sample {path width} {
    variable file; variable tick; variable sampled; variable dump_off
    set key [list $path $width]
    if {[dict exists $sampled $key]} {return [dict get $sampled $key]}
    set ret [dict create status not_dumped value "" path $path change_tick ""]
    set sig [npi_fsdb_sig_by_name -file $file -name $path -scope ""]
    if {![valid $sig]} {dict set sampled $key $ret; return $ret}
    set actual_width [npi_fsdb_sig_property -type npiFsdbSigRangeSize -sig $sig]
    set has_members [npi_fsdb_sig_property -type npiFsdbSigHasMember -sig $sig]
    if {![string is entier -strict $actual_width] || (!$has_members && $actual_width != $width)} {
        dict set ret status width_mismatch
        dict set sampled $key $ret; return $ret
    }
    foreach pair $dump_off {
        lassign $pair start end
        if {$tick >= $start && $tick < $end} {
            dict set ret status dump_off
            dict set sampled $key $ret; return $ret
        }
    }
    if {[catch {
        set ret [read_bits $sig]
        if {[dict get $ret status] eq "ok" && [string length [dict get $ret value]] != $width} {
            dict set ret detail "expected $width bits, FSDB returned [string length [dict get $ret value]] bits"
            dict set ret status width_mismatch
            dict set ret value ""
        }
    } why]} {dict set ret status read_error; dict set ret detail $why}
    # Keep only the compact sampled string, never all signals' VC histories.
    npi_fsdb_unload_vc -file $file
    dict set sampled $key $ret
    return $ret
}
proc wi::evaluate {e} {
    switch -- [dict get $e kind] {
        signal {return [sample [dict get $e path] [dict get $e width]]}
        constant {return [dict create status ok value [dict get $e value] change_tick ""]}
        select {
            set result [evaluate [dict get $e parent]]
            if {[dict get $result status] eq "ok"} {
                set value ""; foreach i [dict get $e offsets] {append value [string index [dict get $result value] $i]}
                dict set result value $value
            }
            return $result
        }
        concat {
            set value ""; set time ""
            foreach sub [dict get $e operands] {
                set r [evaluate $sub]
                if {[dict get $r status] ne "ok"} {return $r}
                append value [dict get $r value]
                set st [dict get $r change_tick]
                if {$st ne "" && ($time eq "" || $st>$time)} {set time $st}
            }
            return [dict create status ok value $value change_tick $time]
        }
    }
}

proc wi::row {h logical port dir modport interface_path {origin port} {problem ""}} {
    variable count; incr count
    set shp null; set ex null; set value null; set status unsupported_type; set change ""; set detail $problem
    if {$problem eq "" && [catch {
        set hp [actual $h]
        set shp [shape_json [shape $hp]]
        set expr [expression $hp]
        set ex [expr_json $expr]
        set result [evaluate $expr]
        set status [dict get $result status]
        if {$status eq "ok"} {set value [j [dict get $result value]]}
        set change [dict get $result change_tick]
        if {[dict exists $result detail]} {set detail [dict get $result detail]}
    } failure]} {set status unsupported_type; set detail $failure}
    emit [obj kind [j signal] logical_path [j $logical] port [j $port] direction [j $dir] \
        direction_source [j $origin] modport [j $modport] interface_path [j $interface_path] \
        shape $shp expression $ex status [j $status] value_bin $value change_tick [j $change] detail [j $detail]]
}
proc wi::expand {h logical port dir mp ip origin {depth 0}} {
    if {$depth>32} {row $h $logical $port $dir $mp $ip $origin "array nesting exceeds 32"; return}
    if {[catch {set h [actual $h]} why]} {row $h $logical $port $dir $mp $ip $origin $why; return}
    set ts [r $h npiTypespec]
    if {[s $ts npiType] eq "npiArrayTypespec"} {
        if {[catch {set rs [ranges $ts]; if {![llength $rs] || [n $ts npiArrayType]!=1} {error "not a fixed array"}} why]} {
            row $h $logical $port $dir $mp $ip $origin $why; return
        }
        foreach idx [indices [lindex $rs 0]] {
            set child [npi_handle_by_index -object $h -index $idx]
            if {![valid $child]} {set child [byname "[s $h npiFullName]\[$idx\]"]}
            expand $child "$logical\[$idx\]" $port $dir $mp $ip $origin [expr {$depth+1}]
        }
    } elseif {[s $ts npiType] in {npiStructTypespec npiUnionTypespec} && ![n $ts npiPacked]} {
        set members [children $ts npiTypespecMember]
        if {![llength $members]} {row $h $logical $port $dir $mp $ip $origin "struct members unavailable"; return}
        foreach m $members {
            set mn [s $m npiName]
            expand [byname "[s $h npiFullName].$mn"] "$logical.$mn" $port $dir $mp $ip $origin [expr {$depth+1}]
        }
    } else {row $h $logical $port $dir $mp $ip $origin}
}

proc wi::interface_port {low logical port {depth 0} {instance ""}} {
    if {$depth>32} {error "interface array nesting exceeds 32"}
    set ts [r $low npiTypespec]
    if {[s $ts npiType] eq "npiArrayTypespec"} {
        set array $instance
        if {![valid $array]} {
            set array [actual $low]
            if {[s $array npiType] eq "npiModport"} {set array [r $array npiScope]}
        }
        if {[s $array npiType] ne "npiInterfaceArray"} {error "interface array binding unavailable"}
        set formal_indices [indices [lindex [ranges $ts] 0]]
        set actual_indices [indices [lindex [ranges $array] 0]]
        if {[llength $formal_indices] != [llength $actual_indices]} {error "interface array size mismatch"}
        foreach idx $formal_indices actual_index $actual_indices {
            set name "[s $low npiFullName]\[$idx\]"
            set child [byname $name]
            if {![valid $child]} {error "interface array element unavailable: $name"}
            set child_instance [npi_handle_by_index -object $array -index $actual_index]
            if {![valid $child_instance]} {error "actual interface element unavailable"}
            interface_port $child "$logical\[$idx\]" $port [expr {$depth+1}] $child_instance
        }
        return
    }
    set act [actual $low]; set kind [s $act npiType]; set mp ""
    if {$kind eq "npiModport"} {set mp [s $act npiName]; set itf [r $act npiScope]} \
    elseif {$kind eq "npiInterface"} {set itf $act} else {error "unresolved interface binding ($kind)"}
    if {[valid $instance]} {
        set itf $instance
        if {$mp ne ""} {
            set act ""
            foreach candidate [children $itf npiModport] {
                if {[s $candidate npiName] eq $mp} {set act $candidate; break}
            }
            if {![valid $act]} {error "modport $mp unavailable on array element"}
        }
    }
    interface_metadata $itf
    set ip [s $itf npiFullName]
    emit [obj kind [j binding] port [j $port] logical_path [j $logical] interface_path [j $ip] modport [j $mp]]
    if {$mp ne ""} {
        set members [children $act npiMpPort]
        if {![llength $members]} {set members [children $act npiIODecl]}
        if {![llength $members]} {error "modport members unavailable"}
        foreach m $members {
            set dir [direction $m]
            if {$dir eq "output"} {continue}
            set name [s $m npiName]
            expand [r $m npiExpr] "$logical.$name" $port $dir $mp $ip modport
        }
    } else {
        set seen {}
        foreach category {npiNet npiArrayNet npiVariables} {
            foreach m [children $itf $category] {
                set name [s $m npiFullName]
                if {$name in $seen} {continue}; lappend seen $name
                expand $m "$logical.[s $m npiName]" $port unknown "" $ip unqualified_interface
            }
        }
    }
}

proc wi::main {} {
    variable file; variable tick; variable dump_off
    global env
    set file [npi_fsdb_open -name $env(WI_FSDB)]
    if {![valid $file]} {error "cannot open FSDB"}
    set scale [npi_fsdb_file_property_str -file $file -type npiFsdbFileScaleUnit]
    set factors [dict create fs 1 ps 1000 ns 1000000 us 1000000000 ms 1000000000000 s 1000000000000000]
    if {![regexp {^([0-9]+)\s*(fs|ps|ns|us|ms|s)$} $scale -> mult unit]} {error "unsupported FSDB scale $scale"}
    set divisor $env(WI_TIME_DEN)
    if {$env(WI_TIME_MODE) eq "physical"} {set divisor [expr {$divisor*$mult*[dict get $factors $unit]}]}
    if {$env(WI_TIME_NUM) % $divisor != 0} {error "requested time is not an integral FSDB tick ($scale)"}
    set tick [expr {$env(WI_TIME_NUM)/$divisor}]
    set lo [npi_fsdb_min_time -file $file]; set hi [npi_fsdb_max_time -file $file]
    if {$tick < $lo || $tick > $hi || $tick>18446744073709551615} {error "time $tick outside FSDB range $lo..$hi ticks"}
    set dumpstr [npi_fsdb_file_property_str -file $file -type npiFsdbFileDumpOffRange]
    foreach {whole start end} [regexp -all -inline {\(\s*([0-9]+)\s+([0-9]+)\s*\)} $dumpstr] {lappend dump_off [list $start $end]}
    debImport -elab $env(WI_KDB)
    set scope [byname $env(WI_SCOPE)]
    if {[s $scope npiType] ne "npiModule"} {error "scope is not a module instance: $env(WI_SCOPE)"}
    emit [obj kind [j metadata] scope [j [s $scope npiFullName]] definition [j [s $scope npiDefName]] \
        parameters [params $scope] timescale [j $scale] tick [j $tick] min_tick [j $lo] max_tick [j $hi] \
        dump_off_ranges [ranges_json $dump_off] source_file [j [s $scope npiDefFile]]]
    foreach port [children $scope npiPort] {
        set name [s $port npiName]; set low [r $port npiLowConn]
        emit [obj kind [j port] description [port_description $port]]
        set logical "$env(WI_SCOPE).$name"
        if {[s $port npiPortType] in {npiInterfacePort npiModportPort}} {
            if {[catch {interface_port $low $logical $name} why]} {row $low $logical $name unknown "" "" unresolved_binding $why}
        } else {
            set dir [direction $port]
            if {$dir ne "output"} {expand $low $logical $name $dir "" "" port}
        }
    }
    npi_fsdb_close -file $file
    emit [obj kind [j done] count $wi::count]
}

if {[info exists env(WI_LIBRARY_ONLY)]} {return}
set wi::output [open $env(WI_RESULT) w]
fconfigure $wi::output -encoding utf-8 -translation lf
if {[catch {wi::main} error options]} {
    wi::emit [wi::obj kind [wi::j fatal] message [wi::j $error] detail [wi::j [dict get $options -errorinfo]]]
    if {[info exists wi::file] && [wi::valid $wi::file]} {catch {npi_fsdb_close -file $wi::file}}
}
close $wi::output
debExit
