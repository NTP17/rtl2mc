// Four independent cells. This is not a connected physical circuit.
module buffer_bank(input wire [3:0] A, output wire [3:0] Y);
  RSBUF2 u2 (.A(A[0]), .Y(Y[0]));
  RSBUF4 u4 (.A(A[1]), .Y(Y[1]));
  RSBUF6 u6 (.A(A[2]), .Y(Y[2]));
  RSBUF8 u8 (.A(A[3]), .Y(Y[3]));
endmodule
