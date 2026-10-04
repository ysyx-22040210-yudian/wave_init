`timescale 1ns/1ps
module existing_replay;
  deep_top original();
  `include "snapshot.svh"
  initial begin
    #6;
    if (existing_replay.original.soc.g_tile[1].tile.link.data !== 8'bz01x1010) $fatal(1,"original drive before force");
    apply_snapshot();
    #0.001;
    if (existing_replay.original.soc.g_tile[1].tile.link.data !== 8'b10xz0101 || existing_replay.original.soc.g_tile[1].tile.link.req !== 1'b1 || existing_replay.original.soc.g_tile[1].tile.link.pad !== 1'bz)
      $fatal(1,"deep input snapshot not applied");
    check_snapshot();
    release_snapshot();
    #2;
    if (existing_replay.original.soc.g_tile[1].tile.link.data !== 8'h5a || existing_replay.original.soc.g_tile[1].tile.link.req !== 1'b1 || existing_replay.original.soc.g_tile[1].tile.link.pad !== 1'b1)
      $fatal(1,"release did not restore later original drives");
    $display("DEEP_FORCE_RELEASE_PASS");
    $finish;
  end
endmodule
