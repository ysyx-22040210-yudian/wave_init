`timescale 1ns/1ps
// Compile with the original RTL/package filelist.
// Continuous assignments hold the sampled values throughout simulation.
// Source: snapshot_top.dut @ 7ns (7000 ticks of 1ps).
// Internal sequential state and individual inout drivers are not reconstructed.
module wave_init_tb;
  wire  wi_bus_clk;
  snap_if #(.W(32'sb00000000000000000000000000001000)) bus (.clk(wi_bus_clk));
  wire  clk;
  wire  rst_n;
  wire signed [7:0] scalar;
  wire [0:7] ascending;
  wire [1:0][3:0] packed_data;
  wire [15:0] packet;
  wire [7:0] matrix[1:0][2:1];
  wire [129:0] wide;
  wire  pad;
  wire [7:0] result;
  snap_slave #(.W(32'sb00000000000000000000000000001000)) dut (
    .clk(clk),
    .rst_n(rst_n),
    .scalar(scalar),
    .ascending(ascending),
    .packed_data(packed_data),
    .packet(packet),
    .matrix(matrix),
    .wide(wide),
    .pad(pad),
    .bus(bus),
    .result(result)
  );

  // Constant FSDB snapshot drivers (input/inout; output ports are not driven).
  // snapshot_top.dut.ascending (input)
  assign ascending = 8'b10100110;
  // snapshot_top.dut.bus.pad (inout)
  assign bus.pad = 1'bz;
  // snapshot_top.dut.bus.req (input)
  assign bus.req = 1'b1;
  // snapshot_top.dut.bus.wdata (input)
  assign bus.wdata = 8'b10100101;
  // snapshot_top.dut.clk (input)
  assign clk = 1'b1;
  // snapshot_top.dut.matrix[0][1] (input)
  assign matrix[0][1] = 8'b00000001;
  // snapshot_top.dut.matrix[0][2] (input)
  assign matrix[0][2] = 8'b00000010;
  // snapshot_top.dut.matrix[1][1] (input)
  assign matrix[1][1] = 8'b00010001;
  // snapshot_top.dut.matrix[1][2] (input)
  assign matrix[1][2] = 8'b00010010;
  // snapshot_top.dut.packed_data (input)
  assign packed_data = 8'b10111001;
  // snapshot_top.dut.packet (input)
  assign packet = 16'b1100000100100011;
  // snapshot_top.dut.pad (inout)
  assign pad = 1'bz;
  // snapshot_top.dut.rst_n (input)
  assign rst_n = 1'b1;
  // snapshot_top.dut.scalar (input)
  assign scalar = 8'b10010110;
  // snapshot_top.dut.bus.clk (input)
  assign wi_bus_clk = 1'b1;
  // snapshot_top.dut.wide (input)
  assign wide = 130'bxz00000001001000110100010101100111100010011010101111001101111011111111111011011100101110101001100001110110010101000011001000010000;

task automatic check_snapshot();
  if (bus.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 0");
  if (bus.pad !== 1'bz) $fatal(1, "snapshot mismatch at generated item 1");
  if (bus.req !== 1'b1) $fatal(1, "snapshot mismatch at generated item 2");
  if (bus.wdata !== 8'b10100101) $fatal(1, "snapshot mismatch at generated item 3");
  if (dut.ascending !== 8'b10100110) $fatal(1, "snapshot mismatch at generated item 4");
  if (dut.clk !== 1'b1) $fatal(1, "snapshot mismatch at generated item 5");
  if (dut.matrix[0][1] !== 8'b00000001) $fatal(1, "snapshot mismatch at generated item 6");
  if (dut.matrix[0][2] !== 8'b00000010) $fatal(1, "snapshot mismatch at generated item 7");
  if (dut.matrix[1][1] !== 8'b00010001) $fatal(1, "snapshot mismatch at generated item 8");
  if (dut.matrix[1][2] !== 8'b00010010) $fatal(1, "snapshot mismatch at generated item 9");
  if (dut.packed_data !== 8'b10111001) $fatal(1, "snapshot mismatch at generated item 10");
  if (dut.packet !== 16'b1100000100100011) $fatal(1, "snapshot mismatch at generated item 11");
  if (dut.pad !== 1'bz) $fatal(1, "snapshot mismatch at generated item 12");
  if (dut.rst_n !== 1'b1) $fatal(1, "snapshot mismatch at generated item 13");
  if (dut.scalar !== 8'b10010110) $fatal(1, "snapshot mismatch at generated item 14");
  if (dut.wide !== 130'bxz00000001001000110100010101100111100010011010101111001101111011111111111011011100101110101001100001110110010101000011001000010000) $fatal(1, "snapshot mismatch at generated item 15");
endtask

initial begin
  #0.001;
  check_snapshot();
  $display("WAVE_INIT_SNAPSHOT_PASS");
  #0.001;
  $finish;
end
endmodule
