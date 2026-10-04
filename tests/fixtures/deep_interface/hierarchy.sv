`timescale 1ns/1ps
// The interface and leaf DUT definitions live in split_interface/bus.sv and
// split_interface/dut.sv. Every recursive hop passes actual interface ports.
module deep_chain #(parameter DEPTH=8)(
  input wire rst_n, interface upstream, interface array_bus[1:0]
);
  generate
    if (DEPTH > 0) begin : g_next
      deep_chain #(.DEPTH(DEPTH-1)) u_child(
        .rst_n(rst_n), .upstream(upstream), .array_bus(array_bus)
      );
    end else begin : g_leaf
      split_slave dut(.rst_n(rst_n), .bus(upstream), .seen());
      split_generic connected(.bus(upstream.mst), .seen());
      split_remap aliases(.bus(upstream.remap), .seen());
      split_array array_dut(.buses(array_bus), .seen());
      split_shared shared(.bus_a(upstream), .bus_b(upstream), .seen());
    end
  endgenerate
endmodule

module deep_tile #(parameter INDEX=0, DEPTH=8)(input wire clk, rst_n);
  split_bus link(clk);
  split_bus links[1:0](clk);
  logic pad_drive;
  assign link.pad = pad_drive;
  assign links[0].pad = INDEX ? 1'b1 : 1'bz;
  assign links[1].pad = INDEX ? 1'b0 : 1'b1;
  deep_chain #(.DEPTH(DEPTH)) u_chain(
    .rst_n(rst_n), .upstream(link), .array_bus(links)
  );
  initial begin
    pad_drive = INDEX ? 1'bz : 1'b0;
    link.req = INDEX ? 1 : 0;
    link.data = INDEX ? 8'b10xz0101 : 8'h36;
    links[0].req = INDEX ? 0 : 1;
    links[0].data = INDEX ? 8'h69 : 8'h12;
    links[1].req = INDEX ? 1 : 0;
    links[1].data = INDEX ? 8'ha6 : 8'he3;
    #5;
    link.req = INDEX ? 0 : 1;
    link.data = INDEX ? 8'bz01x1010 : 8'hc9;
    links[0].req = INDEX ? 1 : 0;
    links[0].data = INDEX ? 8'h93 : 8'h57;
    links[1].req = INDEX ? 0 : 1;
    links[1].data = INDEX ? 8'h4c : 8'hb8;
    #3;
    link.req = INDEX ? 1 : 0;
    link.data = INDEX ? 8'h5a : 8'ha5;
    pad_drive = INDEX ? 1'b1 : 1'b0;
  end
endmodule

module deep_soc #(parameter DEPTH=8)(input wire clk, rst_n);
  for (genvar i=0; i<2; i=i+1) begin : g_tile
    deep_tile #(.INDEX(i), .DEPTH(DEPTH)) tile(.clk(clk), .rst_n(rst_n));
  end
endmodule
