`timescale 1ns/1ps
// One simulation ns represents one completed Minecraft game tick.
// Startup state is unconstrained. Apply the documented clocked reset protocol.
`default_nettype none
module RMAP_NOR2(input A, B, output Y);
  assign Y = ~(A | B);
  specify
`ifdef RMAP_SDF_ONLY
    specparam T = 0;
`else
    specparam T = 8;
`endif
    (A => Y) = (T, T);
    (B => Y) = (T, T);
  endspecify
endmodule

module RMAP_INV(input A, output Y);
  assign Y = ~A;
  specify
`ifdef RMAP_SDF_ONLY
    specparam T = 0;
`else
    specparam T = 8;
`endif
    (A => Y) = (T, T);
  endspecify
endmodule

module RMAP_DFF(input D, CLK, output Q);
  reg state;
  always @(posedge CLK) state <= D;
  assign Q = state;
  reg notifier = 0;
  always @(notifier) state <= 1'bx;
  specify
`ifdef RMAP_SDF_ONLY
    specparam T = 0;
`else
    specparam T = 14;
`endif
`ifdef RMAP_SDF_ONLY
    specparam TS = 0, TH = 0, TW = 0;
`else
    specparam TS = 11, TH = 3, TW = 17;
`endif
    (posedge CLK => (Q +: D)) = (T, T);
    $setuphold(posedge CLK, D, TS, TH, notifier);
    $width(posedge CLK, TW, 0, notifier);
    $width(negedge CLK, TW, 0, notifier);
  endspecify
endmodule

module RMAP_BUF2(input A, output Y);
  assign Y = A;
  specify
`ifdef RMAP_SDF_ONLY
    specparam T = 0;
`else
    specparam T = 2;
`endif
    (A => Y) = (T, T);
  endspecify
endmodule

module RMAP_BUF4(input A, output Y);
  assign Y = A;
  specify
`ifdef RMAP_SDF_ONLY
    specparam T = 0;
`else
    specparam T = 4;
`endif
    (A => Y) = (T, T);
  endspecify
endmodule

module RMAP_BUF6(input A, output Y);
  assign Y = A;
  specify
`ifdef RMAP_SDF_ONLY
    specparam T = 0;
`else
    specparam T = 6;
`endif
    (A => Y) = (T, T);
  endspecify
endmodule

module RMAP_BUF8(input A, output Y);
  assign Y = A;
  specify
`ifdef RMAP_SDF_ONLY
    specparam T = 0;
`else
    specparam T = 8;
`endif
    (A => Y) = (T, T);
  endspecify
endmodule

`default_nettype wire
