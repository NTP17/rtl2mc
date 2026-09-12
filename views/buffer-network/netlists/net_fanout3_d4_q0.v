// Generated physical instances. Keep names/types/connectivity for SDF and placement.
// Q bits observe diode outputs without adding physical loads.
`default_nettype none
module conn_net_fanout3_d4_q0(input wire A, output wire [4:0] Q);
  (* keep = 1, dont_touch = 1 *) RNETBUF2 n0 (.A(A), .Y(Q[0]));
  (* keep = 1, dont_touch = 1 *) RNETBUF8 n1 (.A(Q[0]), .Y(Q[1]));
  (* keep = 1, dont_touch = 1 *) RNETBUF8 n2 (.A(Q[1]), .Y(Q[2]));
  (* keep = 1, dont_touch = 1 *) RNETBUF4 n3 (.A(Q[1]), .Y(Q[3]));
  (* keep = 1, dont_touch = 1 *) RNETBUF6 n4 (.A(Q[1]), .Y(Q[4]));
endmodule
`default_nettype wire
