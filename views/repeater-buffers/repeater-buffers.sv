// Generated; 1 simulation ns = 1 game tick. See docs/repeater-cells.md.
`timescale 1ns/1ps
`default_nettype none
// Enable specify paths (Icarus: -gspecify).
// RS_SDF_ONLY sets path defaults to zero: delays must then come from SDF.
// The procedural guard is authoritative even when a simulator omits $width.
// It checks temporal inputs only; physical placement needs the native contract.
module rs_input_guard #(parameter integer MIN_DWELL = 3) (input wire A);
  realtime last_change = 0.0;
  initial begin
    #0;
    if (A !== 1'b0 && A !== 1'b1)
      $fatal(1, "RS_PROTOCOL: initial input must be binary");
  end
  always @(A) if ($realtime > 0.0) begin
    if (A !== 1'b0 && A !== 1'b1)
      $fatal(1, "RS_PROTOCOL: X/Z input outside cell envelope");
    if ($realtime < 20.0)
      $fatal(1, "RS_PROTOCOL: initial input must settle for 20 game ticks");
    if ($realtime != $floor($realtime))
      $fatal(1, "RS_PROTOCOL: input edges require integer game ticks");
    if ($realtime - last_change < MIN_DWELL)
      $fatal(1, "RS_PROTOCOL: input dwell too short");
    last_change = $realtime;
  end
endmodule

module RSBUF2 (input wire A, output wire Y);
  buf (Y, A);
  rs_input_guard #(.MIN_DWELL(3)) protocol_guard (.A(A));
  specify
`ifdef RS_SDF_ONLY
    specparam TPD = 0;
`else
    specparam TPD = 2;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, 3, 0);
    $width(negedge A, 3, 0);
  endspecify
endmodule

module RSBUF4 (input wire A, output wire Y);
  buf (Y, A);
  rs_input_guard #(.MIN_DWELL(5)) protocol_guard (.A(A));
  specify
`ifdef RS_SDF_ONLY
    specparam TPD = 0;
`else
    specparam TPD = 4;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, 5, 0);
    $width(negedge A, 5, 0);
  endspecify
endmodule

module RSBUF6 (input wire A, output wire Y);
  buf (Y, A);
  rs_input_guard #(.MIN_DWELL(7)) protocol_guard (.A(A));
  specify
`ifdef RS_SDF_ONLY
    specparam TPD = 0;
`else
    specparam TPD = 6;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, 7, 0);
    $width(negedge A, 7, 0);
  endspecify
endmodule

module RSBUF8 (input wire A, output wire Y);
  buf (Y, A);
  rs_input_guard #(.MIN_DWELL(9)) protocol_guard (.A(A));
  specify
`ifdef RS_SDF_ONLY
    specparam TPD = 0;
`else
    specparam TPD = 8;
`endif
    (A => Y) = (TPD, TPD);
    $width(posedge A, 9, 0);
    $width(negedge A, 9, 0);
  endspecify
endmodule

`default_nettype wire
