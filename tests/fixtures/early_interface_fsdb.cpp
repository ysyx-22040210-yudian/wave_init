// The KDB proves that link, bus and xxx are the same interface. Different
// waveform paths deliberately start recording at 60us, 10us and 0ns.
#include <cstddef>
#include "npi.h"
#include "npi_fsdbw.h"

struct Bus {
    npiFsdbwSigObj *clk, *req, *ack, *data, *pad;
};

static Bus bus(npiFsdbwFileObj* f, const char* name) {
    f->create_scope(npiFsdbScopeSvInterface, name, "a");
    Bus b;
    b.clk = f->create_sig(npiFsdbwSdtSvLogic, "clk", npiFsdbDirInput);
    b.req = f->create_sig(npiFsdbwSdtSvLogic, "req", npiFsdbDirInput);
    b.ack = f->create_sig(npiFsdbwSdtSvLogic, "ack", npiFsdbDirOutput);
    b.data = f->create_sig(npiFsdbwSdtSvLogic, 7, 0, "data", npiFsdbDirInput);
    b.pad = f->create_sig(npiFsdbwSdtSvLogic, "pad", npiFsdbDirInout);
    f->upscope();
    return b;
}

static bool put(npiFsdbwSigObj* s, const char* bits) {
    npiFsdbValue v;
    v.format = npiFsdbBinStrVal;
    v.value.str = bits;
    return s && s->add_value(v);
}

static bool values(Bus& b, bool late) {
    return put(b.clk, "1") && put(b.req, late ? "0" : "1") &&
        put(b.ack, late ? "1" : "0") && put(b.data, late ? "z01x1010" : "10xz0101") && put(b.pad, "z");
}

int main(int argc, char** argv) {
    if (argc != 2) return 1;
    int n = 1;
    char* init_args[] = {argv[0], 0};
    char** init_argv = init_args;
    if (!npi_init(n, init_argv)) return 2;
    npiFsdbwFileObj* f = npi_fsdbw_create(argv[1], "1ns", 0);
    if (!f) return 3;
    f->begin_hierarchy_creation();
    f->create_scope(npiFsdbScopeSvModule, "direction_top", "direction_top");
    npiFsdbwSigObj* clk = f->create_sig(npiFsdbwSdtSvLogic, "clk", npiFsdbDirInput);
    Bus link = bus(f, "link");
    f->create_scope(npiFsdbScopeSvModule, "u_wrap", "direction_wrap");
    Bus middle = bus(f, "bus");
    f->create_scope(npiFsdbScopeSvModule, "dut", "direction_slave");
    Bus slave = bus(f, "xxx");
    f->upscope();
    f->create_scope(npiFsdbScopeSvModule, "master", "direction_master");
    Bus master = bus(f, "xxx");
    f->upscope();
    f->create_scope(npiFsdbScopeSvModule, "remap", "direction_remap");
    f->create_scope(npiFsdbScopeSvInterface, "xxx", "a");
    Bus remap;
    remap.clk = f->create_sig(npiFsdbwSdtSvLogic, "clk", npiFsdbDirInput);
    remap.req = f->create_sig(npiFsdbwSdtSvLogic, "req", npiFsdbDirInput);
    remap.ack = f->create_sig(npiFsdbwSdtSvLogic, "ack", npiFsdbDirInput);
    remap.pad = f->create_sig(npiFsdbwSdtSvLogic, "pad", npiFsdbDirInout);
    npiFsdbwSigObj* nibble = f->create_sig(npiFsdbwSdtSvLogic, 3, 0, "nibble", npiFsdbDirInput);
    npiFsdbwSigObj* mix = f->create_sig(npiFsdbwSdtSvLogic, 3, 0, "mix", npiFsdbDirInput);
    f->upscope(); f->upscope(); f->upscope(); f->upscope();
    f->end_hierarchy_creation();
    if (!put(clk, "1") || !values(slave, false) || !values(master, false)) return 4;
    if (!put(remap.clk, "1") || !put(remap.req, "0") || !put(remap.ack, "1") ||
        !put(remap.pad, "z") || !put(nibble, "xz01") || !put(mix, "0110")) return 8;
    f->incr_time(10000);
    if (!values(middle, false)) return 5;
    f->incr_time(50000);
    if (!values(link, true) || !values(middle, true) || !values(slave, true) || !values(master, true)) return 6;
    if (!put(remap.req, "1") || !put(remap.ack, "0") || !put(nibble, "1x10") || !put(mix, "10z0")) return 9;
    f->incr_time(5000);
    if (!put(clk, "1")) return 7;
    npi_fsdbw_close(f);
    npi_end();
    return 0;
}
