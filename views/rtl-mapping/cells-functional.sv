`timescale 1ns/1ps
// One simulation ns represents one completed Minecraft game tick.
// Startup state is unconstrained. Apply the documented clocked reset protocol.
`default_nettype none
module RMAP_NOR2(input A, B, output Y);
  assign Y = ~(A | B);
endmodule

module RMAP_INV(input A, output Y);
  assign Y = ~A;
endmodule

module RMAP_DFF(input D, CLK, output Q);
  reg state;
  always @(posedge CLK) state <= D;
  assign Q = state;
endmodule

module RMAP_BUF2(input A, output Y);
  assign Y = A;
endmodule

module RMAP_BUF4(input A, output Y);
  assign Y = A;
endmodule

module RMAP_BUF6(input A, output Y);
  assign Y = A;
endmodule

module RMAP_BUF8(input A, output Y);
  assign Y = A;
endmodule

`default_nettype wire
