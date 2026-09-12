// Generated; 1 simulation ns = 1 game tick. See docs/repeater-cells.md.
`timescale 1ns/1ps
`default_nettype none
module RSBUF2 (input wire A, output wire Y);
  buf (Y, A);
endmodule

module RSBUF4 (input wire A, output wire Y);
  buf (Y, A);
endmodule

module RSBUF6 (input wire A, output wire Y);
  buf (Y, A);
endmodule

module RSBUF8 (input wire A, output wire Y);
  buf (Y, A);
endmodule

`default_nettype wire
