`timescale 1ns/1ps
// morph3.v -- one 3x3 binary morphology stage on the tick grid: OP=0 erode (AND of the 9), OP=1 dilate (OR of the 9).
// Border = edge replicate (win3x3). Latency 4 clocks (win3x3 3 + 1 output register).
// Cascade for open+close in this design: erode -> dilate -> dilate -> erode with ORG = k*(W+2), k = 1..4
// (ORG counts the flat-tick delay of every window stage in front of this one; 0 would be the NUC window itself).
module morph3 #(
    parameter OP  = 0,
    parameter W   = 320,
    parameter H   = 240,
    parameter ORG = 0
) (
    input  wire       clk,
    input  wire       rst_n,
    input  wire       tick,
    input  wire       first,
    input  wire       din,
    output reg        otick,
    output reg        ofirst,
    output reg        ovalid,
    output reg [8:0]  ocr,
    output reg [8:0]  occ,
    output reg        odata
);
    wire        w_tick, w_first, w_valid;
    wire [8:0]  w_cr, w_cc;
    wire [8:0]  w_win;
    wire [0:0]  w_side;
    win3x3 #(.DW(1), .SW(1), .W(W), .H(H), .ORG(ORG)) win (
        .clk(clk), .rst_n(rst_n), .tick(tick), .first(first), .din(din), .sin(1'b0),
        .otick(w_tick), .ofirst(w_first), .wvalid(w_valid), .cr(w_cr), .cc(w_cc), .win(w_win), .sout(w_side));

    wire red = (OP == 0) ? (&w_win) : (|w_win);

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            otick <= 1'b0; ofirst <= 1'b0; ovalid <= 1'b0; ocr <= 9'd0; occ <= 9'd0; odata <= 1'b0;
        end else begin
            otick <= w_tick; ofirst <= w_first; ovalid <= w_valid; ocr <= w_cr; occ <= w_cc; odata <= red;
        end
    end
endmodule
