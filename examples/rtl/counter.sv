module counter(input logic clk, reset, enable, output logic [1:0] q);
    always_ff @(posedge clk) begin
        if (reset) q <= 2'b00;
        else if (enable) q <= q + 2'b01;
    end
endmodule
