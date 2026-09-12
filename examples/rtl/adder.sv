module adder(input logic a, b, cin, output logic sum, cout);
    assign {cout, sum} = {1'b0, a} + {1'b0, b} + {1'b0, cin};
endmodule
