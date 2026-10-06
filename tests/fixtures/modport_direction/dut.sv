`timescale 1us/1ns
module direction_slave(a.slv xxx, output wire seen);
  assign xxx.ack = ~xxx.req;
  assign seen = xxx.req;
endmodule
module direction_master(a.mst xxx, output wire seen);
  assign seen = xxx.ack;
endmodule
module direction_wrap(interface bus);
  direction_slave dut(.xxx(bus), .seen());
  direction_master master(.xxx(bus), .seen());
endmodule
