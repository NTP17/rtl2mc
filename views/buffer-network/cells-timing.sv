// Generated. Abstract scale: 1 ns = 1 game tick; binary legal histories only.
// Timing models are simulation-only. Synthesis links the Liberty cell symbols.
`timescale 1ns/1ps
`default_nettype none
module RNETBUF2(input wire A, output wire Y);
  buf (Y, A);
  reg timing_notifier=0;
  always @(timing_notifier) if ($realtime > 0)
    $fatal(1, "RNET_TIMING_WIDTH: annotated cell pulse-width violation");
  specify
`ifdef RNET_SDF_ONLY
    specparam TPD=0, WMIN=0;
`else
    specparam TPD=2, WMIN=3;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, WMIN, 0, timing_notifier);
    $width(negedge A, WMIN, 0, timing_notifier);
  endspecify
endmodule

module RNETBUF4(input wire A, output wire Y);
  buf (Y, A);
  reg timing_notifier=0;
  always @(timing_notifier) if ($realtime > 0)
    $fatal(1, "RNET_TIMING_WIDTH: annotated cell pulse-width violation");
  specify
`ifdef RNET_SDF_ONLY
    specparam TPD=0, WMIN=0;
`else
    specparam TPD=4, WMIN=5;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, WMIN, 0, timing_notifier);
    $width(negedge A, WMIN, 0, timing_notifier);
  endspecify
endmodule

module RNETBUF6(input wire A, output wire Y);
  buf (Y, A);
  reg timing_notifier=0;
  always @(timing_notifier) if ($realtime > 0)
    $fatal(1, "RNET_TIMING_WIDTH: annotated cell pulse-width violation");
  specify
`ifdef RNET_SDF_ONLY
    specparam TPD=0, WMIN=0;
`else
    specparam TPD=6, WMIN=7;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, WMIN, 0, timing_notifier);
    $width(negedge A, WMIN, 0, timing_notifier);
  endspecify
endmodule

module RNETBUF8(input wire A, output wire Y);
  buf (Y, A);
  reg timing_notifier=0;
  always @(timing_notifier) if ($realtime > 0)
    $fatal(1, "RNET_TIMING_WIDTH: annotated cell pulse-width violation");
  specify
`ifdef RNET_SDF_ONLY
    specparam TPD=0, WMIN=0;
`else
    specparam TPD=8, WMIN=9;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, WMIN, 0, timing_notifier);
    $width(negedge A, WMIN, 0, timing_notifier);
  endspecify
endmodule

module RNETCMP2(input wire A, output wire Y);
  buf (Y, A);
  reg timing_notifier=0;
  always @(timing_notifier) if ($realtime > 0)
    $fatal(1, "RNET_TIMING_WIDTH: annotated cell pulse-width violation");
  specify
`ifdef RNET_SDF_ONLY
    specparam TPD=0, WMIN=0;
`else
    specparam TPD=2, WMIN=3;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, WMIN, 0, timing_notifier);
    $width(negedge A, WMIN, 0, timing_notifier);
  endspecify
endmodule

`default_nettype wire
