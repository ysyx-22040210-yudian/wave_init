# Read-only design/FSDB access. Invoked by wave_init.py in a private run directory.
namespace eval wi {
    variable output
    variable file
    variable tick
    variable min_tick 0
    variable dump_off {}
    variable sampled [dict create]
    variable interfaces [dict create]
    variable interface_bindings {}
    variable alias_bindings [dict create]
    variable binding_cache [dict create]
    variable expression_aliases [dict create]
    variable defer_rows 0
    variable pending_rows {}
    variable count 0
    variable trace_file ""
    variable api_failures [dict create]
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
proc wi::trace {level event args} {
    variable trace_file
    if {$trace_file eq ""} {return}
    set now [clock milliseconds]
    set stamp "[clock format [expr {$now/1000}] -gmt 1 -format {%Y-%m-%dT%H:%M:%S}].[format %03d [expr {$now%1000}]]Z"
    set fields [list utc [j $stamp] level [j $level] event [j $event]]
    foreach {key value} $args {lappend fields $key [j $value]}
    puts $trace_file [obj {*}$fields]
    flush $trace_file
}
proc wi::api_failure {operation h property why} {
    variable api_failures
    set key [list $operation $h $property]
    if {[dict exists $api_failures $key] || [dict size $api_failures]>=100} {return}
    dict set api_failures $key 1
    trace DEBUG api.unavailable operation $operation handle $h property $property detail $why
}
proc wi::valid {h} {expr {$h ne "" && $h ne "0"}}
proc wi::s {h p} {
    if {![valid $h]} {return ""}
    if {[catch {npi_get_str -property $p -object $h} v]} {api_failure npi_get_str $h $p $v; return ""}
    return $v
}
proc wi::n {h p {default 0}} {
    if {![valid $h]} {return $default}
    if {[catch {npi_get -property $p -object $h} v]} {api_failure npi_get $h $p $v; return $default}
    if {![string is entier -strict $v]} {return $default}
    return $v
}
proc wi::r {h kind} {
    if {![valid $h]} {return ""}
    if {[catch {npi_handle -type $kind -refHandle $h} v]} {api_failure npi_handle $h $kind $v; return ""}
    return $v
}
proc wi::children {h kind} {
    set xs {}
    if {[catch {npi_iterate -type $kind -refHandle $h} it]} {api_failure npi_iterate $h $kind $it; return $xs}
    if {![valid $it]} {return $xs}
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
    }
    # Some older NPI builds expose the integer property but not its spelling.
    switch -- [n $h npiDirection -1] {
        1 {return input}
        2 {return output}
        3 {return inout}
        6 {return ref}
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
    if {[catch {
        if {[s $p npiPortType] in {npiInterfacePort npiModportPort}} {
            set ts [r $low npiTypespec]
            if {![valid $ts]} {set ts [r [byname "[s [r $p npiScope] npiFullName].[s $p npiName]"] npiTypespec]}
            if {![valid $ts]} {error "interface type unavailable"}
            set rs {}
            if {[s $ts npiType] eq "npiArrayTypespec"} {set rs [ranges $ts]}
            # Interfaces have no packed bit width. Their formal array ranges
            # come directly from the declaration, without resolving elements
            # through a definition-level proxy with flattened names.
            set sh [shape_json [dict create width -1 signed 0 packed {} unpacked $rs \
                hdl_type npiRefObj type npiInterfaceTypespec typedef "" unpacked_struct 0]]
        } else {set sh [shape_json [shape $low]]}
    } why]} {set sh null} else {set why ""}
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
        trace DEBUG fsdb.composite handle $sig composite_type $ct depth $depth
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
        set seek [npi_fsdb_goto_time -vct $vct -time $tick]
        set seek_tick ""; set first_tick ""; set scanned 0
        dict set result read_method time_seek
        if {$seek} {set seek_tick [npi_fsdb_vct_time -vct $vct]}
        if {$seek && $seek_tick <= $tick} {
            set changed [npi_fsdb_vct_time -vct $vct]
            set value [string tolower [npi_fsdb_vct_value -vct $vct -format npiFsdbBinStrVal]]
            if {[regexp {^[01xz]+$} $value]} {
                dict set result status ok; dict set result value $value; dict set result change_tick $changed
            }
        } else {
            # A failed seek (or a seek into a later FSDB session) alone does not
            # prove that this signal has no initial value. Initialize from its
            # first record and retain the last record <= tick, including delta
            # changes at the same timestamp. Never substitute a future value.
            dict set result status no_initial_value
            dict set result read_method first_scan
            if {[npi_fsdb_goto_first -vct $vct]} {
                set first_tick [npi_fsdb_vct_time -vct $vct]
                set previous ""
                while {1} {
                    set changed [npi_fsdb_vct_time -vct $vct]
                    if {$previous ne "" && $changed < $previous} {error "nonmonotonic FSDB value changes"}
                    if {$changed > $tick} {break}
                    incr scanned; set previous $changed
                    set value [string tolower [npi_fsdb_vct_value -vct $vct -format npiFsdbBinStrVal]]
                    dict set result change_tick $changed
                    dict set result status unsupported_type; dict set result value ""
                    if {[regexp {^[01xz]+$} $value]} {
                        dict set result status ok; dict set result value $value
                    }
                    if {$scanned % 10000 == 0} {
                        trace DEBUG fsdb.scan_progress handle $sig requested_tick $tick change_tick $changed records $scanned
                    }
                    if {![npi_fsdb_goto_next -vct $vct]} {break}
                }
            }
            trace DEBUG fsdb.seek_recovery handle $sig requested_tick $tick seek_result $seek \
                seek_tick $seek_tick first_tick $first_tick scanned_records $scanned status [dict get $result status]
        }
        dict set result first_tick $first_tick
    } why]
    npi_fsdb_release_vct -vct $vct
    if {$code} {error $why}
    trace DEBUG fsdb.vct handle $sig requested_tick $tick status [dict get $result status] \
        change_tick [dict get $result change_tick] value_bits [string length [dict get $result value]] \
        read_method [dict get $result read_method] first_tick [dict get $result first_tick]
    return $result
}
proc wi::sample {path width} {
    variable file; variable tick; variable min_tick; variable sampled; variable dump_off
    set key [list $path $width]
    if {[dict exists $sampled $key]} {
        trace DEBUG fsdb.cache path $path width $width status [dict get $sampled $key status]
        return [dict get $sampled $key]
    }
    trace DEBUG fsdb.lookup path $path expected_width $width requested_tick $tick
    set ret [dict create status not_dumped value "" path $path change_tick ""]
    set sig [npi_fsdb_sig_by_name -file $file -name $path -scope ""]
    if {![valid $sig]} {
        trace DEBUG fsdb.absent path $path
        dict set sampled $key $ret; return $ret
    }
    set actual_width [npi_fsdb_sig_property -type npiFsdbSigRangeSize -sig $sig]
    set has_members [npi_fsdb_sig_property -type npiFsdbSigHasMember -sig $sig]
    trace DEBUG fsdb.found path $path handle $sig expected_width $width actual_width $actual_width has_members $has_members
    if {![string is entier -strict $actual_width] || (!$has_members && $actual_width != $width)} {
        dict set ret status width_mismatch
        dict set ret detail "expected $width bits, FSDB declared $actual_width bits"
        trace WARNING fsdb.width_mismatch path $path expected_width $width actual_width $actual_width
        dict set sampled $key $ret; return $ret
    }
    foreach pair $dump_off {
        lassign $pair start end
        if {$tick >= $start && $tick < $end} {
            dict set ret status dump_off
            trace WARNING fsdb.dump_off path $path requested_tick $tick start_tick $start end_tick $end
            dict set sampled $key $ret; return $ret
        }
    }
    if {[catch {
        set ret [read_bits $sig]
        if {[dict get $ret status] eq "no_initial_value"} {
            set first ""; if {[dict exists $ret first_tick]} {set first [dict get $ret first_tick]}
            dict set ret detail "no recorded signal value at or before tick $tick (signal first tick: $first; FSDB reported first tick: $min_tick)"
            trace WARNING fsdb.no_initial_value path $path requested_tick $tick signal_first_tick $first file_first_tick $min_tick
        }
        if {[dict get $ret status] eq "ok" && [string length [dict get $ret value]] != $width} {
            dict set ret detail "expected $width bits, FSDB returned [string length [dict get $ret value]] bits"
            dict set ret status width_mismatch
            dict set ret value ""
        }
    } why]} {dict set ret status read_error; dict set ret detail $why}
    dict set ret path $path
    if {[catch {npi_fsdb_sig_property_str -type npiFsdbSigFullName -sig $sig} full] == 0 && $full ne ""} {
        dict set ret path $full
    }
    # Keep only the compact sampled string, never all signals' VC histories.
    npi_fsdb_unload_vc -file $file
    dict set sampled $key $ret
    trace DEBUG fsdb.sampled path $path waveform_path [dict get $ret path] status [dict get $ret status] \
        change_tick [dict get $ret change_tick] value_bits [string length [dict get $ret value]]
    return $ret
}
proc wi::expr_paths {e} {
    switch -- [dict get $e kind] {
        signal {return [list [dict get $e path]]}
        select {return [expr_paths [dict get $e parent]]}
        concat {
            set xs {}; foreach sub [dict get $e operands] {lappend xs {*}[expr_paths $sub]}
            return [lsort -unique $xs]
        }
        default {return {}}
    }
}
proc wi::sample_candidates {e paths} {
    set unique {}; foreach path $paths {if {$path ni $unique} {lappend unique $path}}
    trace DEBUG fsdb.candidates design_paths [expr_paths $e] width [dict get $e width] paths $unique
    set result [dict create status not_dumped value "" change_tick ""]
    set selected ""; set missing_initial ""; set attempts {}
    foreach path $unique {
        set result [sample $path [dict get $e width]]
        set first ""; set method ""; set detail ""
        if {[dict exists $result first_tick]} {set first [dict get $result first_tick]}
        if {[dict exists $result read_method]} {set method [dict get $result read_method]}
        if {[dict exists $result detail]} {set detail [dict get $result detail]}
        lappend attempts [obj path [j $path] status [j [dict get $result status]] first_tick [j $first] \
            change_tick [j [dict get $result change_tick]] read_method [j $method] detail [j $detail]]
        # Proven aliases can have different dump start times. Continue after
        # no_initial_value, but keep it if no alias provides an earlier value.
        # Width errors and dump-off remain authoritative.
        if {[dict get $result status] eq "no_initial_value"} {
            if {$missing_initial eq ""} {set missing_initial $result}
        } elseif {[dict get $result status] ne "not_dumped"} {
            set selected [dict get $result path]
            break
        }
    }
    if {[dict get $result status] in {not_dumped no_initial_value} && $missing_initial ne ""} {
        set result $missing_initial; set selected [dict get $result path]
    }
    dict set result reads [list [obj design_paths [strings [expr_paths $e]] \
        waveform_path [j $selected] candidates [strings $unique] attempts [arr $attempts]]]
    if {[dict get $result status] eq "not_dumped"} {
        dict set result detail "FSDB signal not found; tried exact NPI-bound paths: [join $unique {, }]"
    }
    trace DEBUG fsdb.selected waveform_path $selected status [dict get $result status] attempts [arr $attempts]
    return $result
}
proc wi::evaluate {e} {
    variable expression_aliases
    set aliases {}
    set key [expr_json $e]
    if {[dict exists $expression_aliases $key]} {set aliases [dict get $expression_aliases $key]}
    switch -- [dict get $e kind] {
        signal {return [sample_candidates $e [concat [list [dict get $e path]] $aliases]]}
        constant {return [dict create status ok value [dict get $e value] change_tick "" reads {}]}
        select {
            set result [evaluate [dict get $e parent]]
            if {[dict get $result status] in {not_dumped no_initial_value} && [llength $aliases]} {
                set alias [sample_candidates $e $aliases]
                if {[dict get $alias status] ne "not_dumped"} {return $alias}
                if {[dict get $result status] eq "not_dumped"} {return $alias}
                dict lappend result reads {*}[dict get $alias reads]
            }
            if {[dict get $result status] eq "ok"} {
                set value ""; foreach i [dict get $e offsets] {append value [string index [dict get $result value] $i]}
                dict set result value $value
            }
            return $result
        }
        concat {
            set value ""; set time ""; set reads {}
            foreach sub [dict get $e operands] {
                set r [evaluate $sub]
                if {[dict get $r status] in {not_dumped no_initial_value} && [llength $aliases]} {
                    set alias [sample_candidates $e $aliases]
                    if {[dict get $alias status] ne "not_dumped"} {return $alias}
                    if {[dict get $r status] eq "not_dumped"} {return $alias}
                    dict lappend r reads {*}[dict get $alias reads]
                }
                if {[dict get $r status] ne "ok"} {return $r}
                lappend reads {*}[dict get $r reads]
                append value [dict get $r value]
                set st [dict get $r change_tick]
                if {$st ne "" && ($time eq "" || $st>$time)} {set time $st}
            }
            return [dict create status ok value $value change_tick $time reads $reads]
        }
    }
}

proc wi::row {h logical port dir modport interface_path {origin port} {problem ""}} {
    variable defer_rows; variable pending_rows
    if {$defer_rows} {
        lappend pending_rows [list $h $logical $port $dir $modport $interface_path $origin $problem]
        return
    }
    variable count; incr count
    set shp null; set ex null; set value null; set status unsupported_type; set change ""; set detail $problem; set reads {}
    if {$problem eq "" && [catch {
        set hp [actual $h]
        set shp [shape_json [shape $hp]]
        set expr [expression $hp]
        set ex [expr_json $expr]
        set result [evaluate $expr]
        set reads [dict get $result reads]
        set status [dict get $result status]
        if {$status eq "ok"} {set value [j [dict get $result value]]}
        set change [dict get $result change_tick]
        if {[dict exists $result detail]} {set detail [dict get $result detail]}
    } failure]} {set status unsupported_type; set detail $failure}
    set level DEBUG
    if {$status ne "ok" || $dir in {unknown ref}} {set level WARNING}
    trace $level signal.result logical_path $logical direction $dir direction_source $origin modport $modport \
        interface_path $interface_path status $status expression $ex waveform_reads [arr $reads] \
        change_tick $change value_preview [string range $value 0 65] detail $detail
    emit [obj kind [j signal] logical_path [j $logical] port [j $port] direction [j $dir] \
        direction_source [j $origin] modport [j $modport] interface_path [j $interface_path] \
        shape $shp expression $ex waveform_reads [arr $reads] status [j $status] value_bin $value change_tick [j $change] detail [j $detail]]
}

# Register only aliases whose complete expression is proven by the KDB.
# Blind prefix replacement is unsafe: modport .a(b) can give the same short
# name a different meaning. Preparing every row also covers shared ports and
# interface constructor inputs whose values exist only under a formal port.
proc wi::prepare_aliases {} {
    variable pending_rows; variable expression_aliases; variable interface_bindings
    variable alias_bindings
    foreach binding [dict keys $alias_bindings] {
        lassign $binding logical itf mp
        if {$mp ne ""} {
            set view [interface_view $itf $mp]
            set members [children $view npiMpPort]
            if {![llength $members]} {set members [children $view npiIODecl]}
            foreach m $members {
                catch {alias_leaf [r $m npiExpr] "$logical.[s $m npiName]"}
            }
        } else {
            foreach category {npiNet npiArrayNet npiVariables} {
                foreach m [children $itf $category] {catch {alias_leaf $m "$logical.[s $m npiName]"}}
            }
        }
    }
    foreach job $pending_rows {
        lassign $job h logical port dir mp ip origin problem
        if {$ip eq "" || $problem ne ""} {continue}
        if {[catch {set key [expr_json [expression [actual $h]]]}]} {continue}
        set candidates [list $logical]
        foreach binding $interface_bindings {
            lassign $binding formal instance view
            if {$instance eq $ip && $view eq $mp && $mp ne "" && [string first "$formal." $logical] == 0} {
                lappend candidates "$ip.$mp[string range $logical [string length $formal] end]"
            }
        }
        foreach path $candidates {
            if {![dict exists $expression_aliases $key] || $path ni [dict get $expression_aliases $key]} {
                dict lappend expression_aliases $key $path
            }
        }
    }
}
proc wi::alias_leaf {h logical {depth 0}} {
    variable expression_aliases
    if {$depth>32} {error "alias array nesting exceeds 32"}
    set h [actual $h]; set ts [r $h npiTypespec]
    if {[s $ts npiType] eq "npiArrayTypespec"} {
        if {[n $ts npiArrayType]!=1} {return}
        foreach idx [indices [lindex [ranges $ts] 0]] {
            set child [npi_handle_by_index -object $h -index $idx]
            if {![valid $child]} {set child [byname "[s $h npiFullName]\[$idx\]"]}
            alias_leaf $child "$logical\[$idx\]" [expr {$depth+1}]
        }
    } elseif {[s $ts npiType] in {npiStructTypespec npiUnionTypespec} && ![n $ts npiPacked]} {
        foreach m [children $ts npiTypespecMember] {
            set name [s $m npiName]
            alias_leaf [byname "[s $h npiFullName].$name"] "$logical.$name" [expr {$depth+1}]
        }
    } else {
        set key [expr_json [expression $h]]
        if {![dict exists $expression_aliases $key] || $logical ni [dict get $expression_aliases $key]} {
            dict lappend expression_aliases $key $logical
        }
    }
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

# Verdi 2018 can return definition-level proxy objects for forwarded interfaces
# inside generate blocks. Their full names omit generate indices. Follow each
# actual high connection in its lexical instance scope instead of using those
# proxy names as design or waveform paths.
proc wi::interface_view {itf mp} {
    foreach view [children $itf npiModport] {
        if {[s $view npiName] eq $mp} {return $view}
    }
    error "modport $mp unavailable on [s $itf npiFullName]"
}
proc wi::declared_modport {p} {
    # The port's definition describes the FORMAL declaration (a.slv xxx),
    # independently of the actual interface bound through npiLowConn.
    # Never infer a role from a name such as slv/mst, or from the signal names.
    set definition [s $p npiDefName]
    if {[regexp {\.([^\.[:space:]]+)$} $definition -> name]} {
        trace DEBUG modport.declaration port [s $p npiName] definition $definition modport $name source npiDefName
        return $name
    }
    return ""
}
proc wi::modport_direction {member view} {
    set dir [direction $member]
    if {$dir ne "unknown"} {return $dir}
    # npiIODecl is supported by older Language Model versions as well.
    set name [s $member npiName]
    foreach category {npiIODecl npiMpPort} {
        foreach declaration [children $view $category] {
            if {[s $declaration npiName] ne $name} {continue}
            set dir [direction $declaration]
            if {$dir ne "unknown"} {
                trace DEBUG modport.direction_fallback member $name direction $dir category $category
                return $dir
            }
        }
    }
    return unknown
}
proc wi::typed_modport {p low declaration items} {
    # If npiDefName on the port omits the suffix, interface typespec/ref
    # metadata can still name it. Accept it only for a formally typed modport
    # port and only when the actual interface declares that exact view.
    if {[s $p npiPortType] ne "npiModportPort"} {return ""}
    set names {}
    foreach h [list $low $declaration [r $low npiTypespec] [r $declaration npiTypespec]] {
        set properties {npiDefName}
        if {[s $h npiType] eq "npiInterfaceTypespec"} {lappend properties npiName}
        foreach property $properties {
            set name [s $h $property]
            if {[regexp {\.([^\.[:space:]]+)$} $name -> suffix]} {set name $suffix}
            if {$name eq "" || $name in $names} {continue}
            lappend names $name
        }
    }
    set matches {}
    foreach name $names {
        set matched 1
        foreach itf $items {if {[catch {interface_view $itf $name}]} {set matched 0; break}}
        if {$matched} {lappend matches $name}
    }
    if {[llength $matches]>1} {error "ambiguous formal modport metadata: $matches"}
    if {[llength $matches]==1} {
        trace DEBUG modport.declaration port [s $p npiName] modport [lindex $matches 0] source formal_typespec
        return [lindex $matches 0]
    }
    return ""
}
proc wi::interface_error {kind} {
    error "unresolved interface binding ($kind): KDB interface/modport information is missing or unsupported. For separate-file builds, analyze the interface files AND DUT files with vlogan -sverilog -kdb, then elaborate again with vcs -kdb; using -kdb only for vcs is insufficient."
}
proc wi::connection_object {h} {
    set h [actual $h]; set mp ""
    if {[s $h npiType] eq "npiModport"} {set mp [s $h npiName]; set h [actual [r $h npiScope]]}
    set kind [s $h npiType]
    if {$kind eq "npiInterface"} {
        set items [list $h]; set idxs {}
    } elseif {$kind eq "npiInterfaceArray"} {
        set rs [ranges $h]
        if {[llength $rs]!=1} {error "interface array range unavailable or multidimensional"}
        set idxs [indices [lindex $rs 0]]; set items {}
        foreach idx $idxs {
            set child [npi_handle_by_index -object $h -index $idx]
            if {[s $child npiType] ne "npiInterface"} {error "actual interface array element unavailable"}
            lappend items $child
        }
    } else {interface_error $kind}
    return [dict create items $items indices $idxs view $mp aliases {}]
}
proc wi::connection_high {high context visited} {
    set name [s $high npiName]; set mp ""
    trace DEBUG binding.high name $name type [s $high npiType] full_name [s $high npiFullName] \
        context [s $context npiFullName] forwarding_depth [llength $visited]
    if {![catch {set act [actual $high]}] && [s $act npiType] eq "npiModport"} {
        set mp [s $act npiName]
        set suffix ".$mp"
        if {[string range $name end-[expr {[string length $suffix]-1}] end] eq $suffix} {
            set name [string range $name 0 end-[string length $suffix]]
        }
    }
    # A port is resolved in the nearest declaring scope, including generate
    # scopes. This is lexical lookup of the NPI high-connection expression;
    # there is no global search by signal name or generate-index removal.
    set base $name; set selected ""
    if {[regexp {^([^\.\[\]]+)\[(-?[0-9]+)\]$} $name -> base selected]} {}
    set scopes {}
    while {[valid $context] && $context ni $scopes} {
        lappend scopes $context
        trace DEBUG binding.lexical_scope name $name scope [s $context npiFullName]
        foreach p [children $context npiPort] {
            if {[s $p npiName] ne $base || [s $p npiPortType] ni {npiInterfacePort npiModportPort}} {continue}
            set result [connection_port $p $visited]
            if {$selected ne ""} {
                set pos [lsearch -exact [dict get $result indices] $selected]
                if {$pos<0} {error "interface port array index out of range: $name"}
                dict set result items [list [lindex [dict get $result items] $pos]]
                dict set result indices {}
            }
            if {$mp ne ""} {dict set result view $mp}
            return $result
        }
        set found ""
        catch {set found [npi_handle_by_name -name $name -scope $context]}
        if {[valid $found]} {
            set result [connection_object $found]
            if {$mp ne ""} {dict set result view $mp}
            return $result
        }
        set context [r $context npiScope]
    }
    # Already elaborated direct references can include escaped or absolute
    # names that require no lexical traversal.
    return [connection_object $high]
}
proc wi::connection_port {p {visited {}}} {
    variable binding_cache
    set owner [r $p npiScope]; set logical "[s $owner npiFullName].[s $p npiName]"
    if {$logical in $visited || [llength $visited]>256} {error "cyclic or excessive interface forwarding at $logical"}
    if {[dict exists $binding_cache $logical]} {trace DEBUG binding.cache logical_path $logical; return [dict get $binding_cache $logical]}
    lappend visited $logical
    set low [r $p npiLowConn]
    # The named declaration supplies ranges/modport metadata when low-conn
    # itself is npiNIY; it is never trusted for its flattened instance path.
    set declaration [byname $logical]
    set ts [r $low npiTypespec]
    if {![valid $ts]} {set ts [r $declaration npiTypespec]}
    set mp [declared_modport $p]
    set mp_source [expr {$mp ne "" ? "formal_npiDefName" : ""}]
    if {$mp eq ""} {
        foreach ref [list $low $declaration] {
            if {![catch {set act [actual $ref]}] && [s $act npiType] eq "npiModport"} {
                set mp [s $act npiName]; set mp_source formal_npiActual; break
            }
        }
    }
    set high [r $p npiHighConn]
    trace DEBUG binding.port logical_path $logical port_type [s $p npiPortType] \
        low_type [s $low npiType] low_name [s $low npiFullName] \
        declaration_type [s $declaration npiType] formal_definition [s $p npiDefName] formal_modport $mp modport_source $mp_source \
        high_type [s $high npiType] high_name [s $high npiName] forwarding_depth [llength $visited]
    if {![valid $high]} {interface_error "unconnected port $logical"}
    set result [connection_high $high [r $owner npiScope] $visited]
    if {$mp eq ""} {
        set mp [typed_modport $p $low $declaration [dict get $result items]]
        if {$mp ne ""} {set mp_source formal_typespec}
    }
    if {$mp eq ""} {set mp [dict get $result view]; set mp_source actual_connection}
    set idxs {}
    if {[s $ts npiType] eq "npiArrayTypespec"} {
        set rs [ranges $ts]
        if {[llength $rs]!=1} {error "formal interface array range unavailable: $logical"}
        set idxs [indices [lindex $rs 0]]
    }
    set items [dict get $result items]
    set count [expr {[llength $idxs] ? [llength $idxs] : 1}]
    if {$count != [llength $items]} {error "interface array size mismatch at $logical"}
    dict set result indices $idxs
    dict set result view $mp
    dict set result modport_source $mp_source
    set i 0
    foreach itf $items {
        if {$mp ne ""} {interface_view $itf $mp}
        set alias $logical
        if {[llength $idxs]} {append alias "\[[lindex $idxs $i]\]"}
        dict lappend result aliases [list $alias $itf $mp]
        incr i
    }
    dict set binding_cache $logical $result
    set names {}; foreach itf $items {lappend names [s $itf npiFullName]}
    trace DEBUG binding.resolved logical_path $logical interfaces $names modport $mp indices $idxs aliases [dict get $result aliases]
    return $result
}
proc wi::connected_interface {p logical port} {
    variable alias_bindings
    set result [connection_port $p]
    foreach binding [dict get $result aliases] {dict set alias_bindings $binding 1}
    set idxs [dict get $result indices]; set mp [dict get $result view]; set i 0
    foreach itf [dict get $result items] {
        set name $logical
        if {[llength $idxs]} {append name "\[[lindex $idxs $i]\]"}
        interface_instance $itf $name $port $mp [dict get $result modport_source]
        incr i
    }
}

proc wi::interface_instance {itf logical port mp {mp_source ""}} {
    set act ""
    if {$mp ne ""} {set act [interface_view $itf $mp]}
    interface_metadata $itf
    set ip [s $itf npiFullName]
    trace INFO interface.bound logical_path $logical interface_path $ip modport $mp \
        modport_source $mp_source definition [s $itf npiDefName]
    variable interface_bindings
    lappend interface_bindings [list $logical $ip $mp]
    emit [obj kind [j binding] port [j $port] logical_path [j $logical] interface_path [j $ip] \
        modport [j $mp] modport_source [j $mp_source]]
    if {$mp ne ""} {
        set members [children $act npiMpPort]
        if {![llength $members]} {set members [children $act npiIODecl]}
        if {![llength $members]} {error "modport members unavailable"}
        foreach m $members {
            set dir [modport_direction $m $act]
            trace DEBUG modport.member logical_path "$logical.[s $m npiName]" direction $dir \
                modport $mp expr_type [s [r $m npiExpr] npiType] action [expr {$dir eq "output" ? "skip_output" : "sample"}]
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
    variable file; variable tick; variable min_tick; variable dump_off
    variable defer_rows; variable pending_rows
    global env
    trace INFO backend.start run_id $env(WI_RUN_ID) tcl_version [info patchlevel] \
        fsdb $env(WI_FSDB) kdb $env(WI_KDB) scope $env(WI_SCOPE)
    trace INFO fsdb.open path $env(WI_FSDB)
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
    set min_tick $lo
    trace INFO time.resolved timescale $scale mode $env(WI_TIME_MODE) numerator $env(WI_TIME_NUM) \
        denominator $env(WI_TIME_DEN) tick $tick min_tick $lo max_tick $hi
    if {$tick < 0 || $tick > $hi || $tick>18446744073709551615} {error "time $tick outside supported range 0..$hi ticks (first FSDB record: $lo)"}
    if {$tick < $lo} {
        trace WARNING time.before_first_record tick $tick first_tick $lo \
            detail "query accepted; signals without an earlier recorded value return no_initial_value"
    }
    set dumpstr [npi_fsdb_file_property_str -file $file -type npiFsdbFileDumpOffRange]
    foreach {whole start end} [regexp -all -inline {\(\s*([0-9]+)\s+([0-9]+)\s*\)} $dumpstr] {lappend dump_off [list $start $end]}
    trace DEBUG fsdb.dump_ranges ranges $dump_off
    trace INFO kdb.import path $env(WI_KDB)
    debImport -elab $env(WI_KDB)
    trace INFO kdb.imported path $env(WI_KDB)
    set scope [byname $env(WI_SCOPE)]
    trace INFO scope.resolved requested $env(WI_SCOPE) type [s $scope npiType] \
        full_name [s $scope npiFullName] definition [s $scope npiDefName] source_file [s $scope npiDefFile]
    if {[s $scope npiType] ne "npiModule"} {error "scope is not a module instance: $env(WI_SCOPE)"}
    emit [obj kind [j metadata] scope [j [s $scope npiFullName]] definition [j [s $scope npiDefName]] \
        parameters [params $scope] timescale [j $scale] tick [j $tick] min_tick [j $lo] max_tick [j $hi] \
        dump_off_ranges [ranges_json $dump_off] source_file [j [s $scope npiDefFile]]]
    set defer_rows 1
    set ports [children $scope npiPort]
    trace INFO ports.enumerated count [llength $ports]
    foreach port $ports {
        set name [s $port npiName]; set low [r $port npiLowConn]
        trace DEBUG port.inspect name $name type [s $port npiPortType] direction [direction $port] \
            low_type [s $low npiType] low_name [s $low npiFullName]
        emit [obj kind [j port] description [port_description $port]]
        set logical "$env(WI_SCOPE).$name"
        if {[s $port npiPortType] in {npiInterfacePort npiModportPort}} {
            if {[catch {connected_interface $port $logical $name} why options]} {
                trace WARNING interface.unresolved logical_path $logical detail $why stack [dict get $options -errorinfo]
                row $low $logical $name unknown "" "" unresolved_binding $why
            }
        } else {
            set dir [direction $port]
            if {$dir ne "output"} {expand $low $logical $name $dir "" "" port}
        }
    }
    prepare_aliases
    trace INFO signals.prepared count [llength $pending_rows] aliases [dict size $wi::expression_aliases]
    set defer_rows 0
    foreach job $pending_rows {row {*}$job}
    npi_fsdb_close -file $file
    emit [obj kind [j done] count $wi::count]
    trace INFO backend.finished records $wi::count unique_samples [dict size $wi::sampled]
}

if {[info exists env(WI_LIBRARY_ONLY)]} {return}
if {[info exists env(WI_TRACE)]} {
    set wi::trace_file [open $env(WI_TRACE) w]
    fconfigure $wi::trace_file -encoding utf-8 -translation lf
}
if {![info exists env(WI_RUN_ID)]} {set env(WI_RUN_ID) "standalone"}
set wi::output [open $env(WI_RESULT) w]
fconfigure $wi::output -encoding utf-8 -translation lf
if {[catch {wi::main} error options]} {
    wi::trace ERROR backend.fatal detail $error stack [dict get $options -errorinfo]
    wi::emit [wi::obj kind [wi::j fatal] message [wi::j $error] detail [wi::j [dict get $options -errorinfo]]]
    if {[info exists wi::file] && [wi::valid $wi::file]} {catch {npi_fsdb_close -file $wi::file}}
}
close $wi::output
if {$wi::trace_file ne ""} {close $wi::trace_file}
debExit
