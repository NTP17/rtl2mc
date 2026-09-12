`timescale 1ns/1ps
// Qualification control: no procedural input guard; only annotated WIDTH can reject this.
module network_tb;
  reg A=0;
  wire Y;
  RNETBUF8 dut(.A(A),.Y(Y));
  initial $sdf_annotate("eda/commercial/width_probe.sdf", network_tb);
  initial begin
    #44; A=1; #8; A=0;
    #20; $fatal(1,"WIDTH_NOT_ENFORCED: commercial timing-check qualification failed");
  end
endmodule
