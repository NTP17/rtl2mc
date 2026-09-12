`timescale 1ns/1ps
// One simulation ns represents one completed Minecraft game tick.
// Startup state is unconstrained. Apply the documented clocked reset protocol.
`default_nettype none
module RMAP_NOR2(input A, B, output Y);
  reg state;
  initial begin #0.001; state <= #8 ~(A | B); end
  always @(A or B) state <= #8 ~(A | B);
  assign Y = state;
endmodule

module RMAP_INV(input A, output Y);
  reg state;
  initial begin #0.001; state <= #8 ~A; end
  always @(A) state <= #8 ~A;
  assign Y = state;
endmodule

module RMAP_DFF(input D, CLK, output Q);
  reg state;
  always @(posedge CLK) state <= #14 D;
  assign Q = state;
endmodule

module RMAP_BUF2(input A, output Y);
  reg state;
  initial begin #0.001; state <= #2 A; end
  always @(A) state <= #2 A;
  assign Y = state;
endmodule

module RMAP_BUF4(input A, output Y);
  reg state;
  initial begin #0.001; state <= #4 A; end
  always @(A) state <= #4 A;
  assign Y = state;
endmodule

module RMAP_BUF6(input A, output Y);
  reg state;
  initial begin #0.001; state <= #6 A; end
  always @(A) state <= #6 A;
  assign Y = state;
endmodule

module RMAP_BUF8(input A, output Y);
  reg state;
  initial begin #0.001; state <= #8 A; end
  always @(A) state <= #8 A;
  assign Y = state;
endmodule

`default_nettype wire
