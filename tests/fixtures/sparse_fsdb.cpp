// Deliberately sparse writer fixture: verifies that sampling never uses a future
// value, and that width mismatch is distinct from a legitimate X value.
#include <cstddef>
#include <cstring>
#include "npi.h"
#include "npi_fsdbw.h"

static bool put(npiFsdbwSigObj* s, const char* bits) {
    npiFsdbValue v;
    v.format = npiFsdbBinStrVal;
    v.value.str = bits;
    return s && s->add_value(v);
}

int main(int argc, char** argv) {
    if (argc < 2) return 1;
    int n = 1;
    char* init_args[] = {argv[0], 0};
    char** init_argv = init_args;
    if (!npi_init(n, init_argv)) return 2;
    bool mismatch = argc > 2 && std::strcmp(argv[2], "mismatch") == 0;
    npiFsdbwFileObj* f = npi_fsdbw_create(argv[1], "1ps", 0);
    if (!f) return 3;
    f->begin_hierarchy_creation();
    f->create_scope(npiFsdbScopeSvModule, "timing_top", "timing_top");
    f->create_scope(npiFsdbScopeSvModule, "dut", "timing_dut");
    npiFsdbwSigObj* data = f->create_sig(npiFsdbwSdtSvLogic, 7, 0, "data", npiFsdbDirInput);
    npiFsdbwSigObj* absent = f->create_sig(npiFsdbwSdtSvLogic, mismatch ? 4 : 3, 0, "absent", npiFsdbDirInput);
    npiFsdbwSigObj* pad = f->create_sig(npiFsdbwSdtSvLogic, "pad", npiFsdbDirInout);
    f->upscope(); f->upscope(); f->end_hierarchy_creation();
    if (!put(absent, mismatch ? "01001" : "1001") || !put(pad, "z")) return 4;
    f->incr_time(15);
    if (!put(data, "10100101")) return 5;
    f->incr_time(55);
    if (!put(data, "01011010")) return 6;
    npi_fsdbw_close(f);
    npi_end();
    return 0;
}
