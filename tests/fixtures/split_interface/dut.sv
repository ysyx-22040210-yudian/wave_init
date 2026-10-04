`timescale 1ns/1ps
module split_slave(input logic rst_n, split_bus.slv bus, output wire seen);
  assign seen = rst_n & bus.req;
  assign bus.ack = ~bus.req;
endmodule

module split_legacy(rst_n, bus, seen);
  input logic rst_n;
  split_bus.slv bus;
  output wire seen;
  assign seen = rst_n & bus.req;
endmodule

module split_generic(interface bus, output wire seen);
  assign seen = bus.clk;
endmodule

module split_remap(split_bus.remap bus, output wire [9:0] seen);
  assign seen = {bus.req, bus.ack, bus.nibble, bus.mix};
endmodule

module split_array(split_bus.slv buses[1:0], output wire seen);
  assign seen = buses[0].req ^ buses[1].req;
endmodule

module split_shared(split_bus.slv bus_a, split_bus.slv bus_b, output wire seen);
  assign seen = bus_a.req ^ bus_b.req;
endmodule
