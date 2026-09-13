// SPDX-License-Identifier: Apache-2.0
module adder(input logic a, b, cin, output logic sum, cout);
    logic partial_sum, carry_ab, carry_cin;

    half_adder first_half(.a(a), .b(b), .sum(partial_sum), .carry(carry_ab));
    half_adder second_half(.a(partial_sum), .b(cin), .sum(sum), .carry(carry_cin));
    assign cout = carry_ab | carry_cin;
endmodule
