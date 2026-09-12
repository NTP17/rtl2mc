`timescale 1ns/1ps
`default_nettype none
// Instantiate at the EXTERNAL network input. Internal cells settle in stages.
module rnet_input_guard #(parameter integer MIN_DWELL=9, INITIAL_SETTLE=44) (input wire A);
  realtime last_change = 0.0;
  initial begin
    #0.001;
    if (A !== 1'b0 && A !== 1'b1)
      $fatal(1, "RNET_PROTOCOL: initial input must be binary");
  end
  always @(A) if ($realtime > 0.0) begin
    if (A !== 1'b0 && A !== 1'b1)
      $fatal(1, "RNET_PROTOCOL: X/Z input outside admitted network envelope");
    if ($realtime < INITIAL_SETTLE)
      $fatal(1, "RNET_PROTOCOL: initial settling interval incomplete");
    if ($realtime != $floor($realtime))
      $fatal(1, "RNET_PROTOCOL: edges require integer game ticks");
    if ($realtime-last_change < MIN_DWELL)
      $fatal(1, "RNET_PROTOCOL: high/low dwell too short");
    last_change = $realtime;
  end
endmodule
`default_nettype wire
