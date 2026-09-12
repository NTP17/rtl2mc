// Generated. Abstract scale: 1 ns = 1 game tick; binary legal histories only.
// Timing models are simulation-only. Synthesis links the Liberty cell symbols.
`timescale 1ns/1ps
`default_nettype none
module RNETBUF2(input wire A, output wire Y);
  buf (Y, A);
endmodule

module RNETBUF4(input wire A, output wire Y);
  buf (Y, A);
endmodule

module RNETBUF6(input wire A, output wire Y);
  buf (Y, A);
endmodule

module RNETBUF8(input wire A, output wire Y);
  buf (Y, A);
endmodule

module RNETCMP2(input wire A, output wire Y);
  buf (Y, A);
endmodule

`default_nettype wire
