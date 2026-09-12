// Generated. Abstract scale: 1 ns = 1 game tick; binary legal histories only.
// Timing models are simulation-only. Synthesis links the Liberty cell symbols.
`timescale 1ns/1ps
`default_nettype none
module RNETBUF2(input wire A, output wire Y);
  reg delayed;
  initial begin #0.001; delayed <= #2 A; end
  always @(A) delayed <= #2 A;
  assign Y = delayed;
endmodule

module RNETBUF4(input wire A, output wire Y);
  reg delayed;
  initial begin #0.001; delayed <= #4 A; end
  always @(A) delayed <= #4 A;
  assign Y = delayed;
endmodule

module RNETBUF6(input wire A, output wire Y);
  reg delayed;
  initial begin #0.001; delayed <= #6 A; end
  always @(A) delayed <= #6 A;
  assign Y = delayed;
endmodule

module RNETBUF8(input wire A, output wire Y);
  reg delayed;
  initial begin #0.001; delayed <= #8 A; end
  always @(A) delayed <= #8 A;
  assign Y = delayed;
endmodule

module RNETCMP2(input wire A, output wire Y);
  reg delayed;
  initial begin #0.001; delayed <= #2 A; end
  always @(A) delayed <= #2 A;
  assign Y = delayed;
endmodule

`default_nettype wire
