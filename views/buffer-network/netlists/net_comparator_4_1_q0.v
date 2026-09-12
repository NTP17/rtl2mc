// Generated physical instances. Keep names/types/connectivity for SDF and placement.
// Q bits observe diode outputs without adding physical loads.
`default_nettype none
module conn_net_comparator_4_1_q0(input wire A, output wire [2:0] Q);
  (* keep = 1, dont_touch = 1 *) RNETCMP2 n0 (.A(A), .Y(Q[0]));
  (* keep = 1, dont_touch = 1 *) RNETBUF8 n1 (.A(Q[0]), .Y(Q[1]));
  (* keep = 1, dont_touch = 1 *) RNETBUF2 n2 (.A(Q[1]), .Y(Q[2]));
endmodule
`default_nettype wire
