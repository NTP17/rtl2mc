module mux2(input logic a, b, select_b, output logic y);
    assign y = select_b ? b : a;
endmodule
