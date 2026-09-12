module shift2(
    input logic clk, reset, enable, serial_in,
    output logic [1:0] q
);
    always_ff @(posedge clk) begin
        if (reset) q <= 2'b00;
        else if (enable) q <= {q[0], serial_in};
    end
endmodule
