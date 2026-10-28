`timescale 1ns/1ps
// ccl_slot.v -- one label slot of the streaming connected-component box extractor (see ccl_boxes.v).
// Plain registers (not RAM): the table is 16 slots accessed in parallel.
//
//   alloc : take the slot for a new object whose first pixel is (px, py)
//   ext   : add pixel (px, py) to the object
//   mrg_lo: this slot absorbs the object in `hi_*` plus pixel (px, py)      (area = area + hi_area + 1)
//   mrg_hi: this slot was absorbed: becomes free after 2 line ends (blk = 2)
//   fin   : the object is finished and has been read out: slot becomes free at once
//   clr   : frame reset (everything free, blk := 0)
//   age   : end-of-line bookkeeping for all slots: touched := 0, blk := blk - 1 (floor 0)
//   alias_set/alias_from/alias_to : every slot whose link == alias_from now points at alias_to
module ccl_slot #(
    parameter ID = 0
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        alloc,
    input  wire        ext,
    input  wire        mrg_lo,
    input  wire        mrg_hi,
    input  wire        fin,
    input  wire        age,
    input  wire        clr,
    input  wire        alias_set,
    input  wire [3:0]  alias_from,
    input  wire [3:0]  alias_to,
    input  wire [8:0]  px,
    input  wire [8:0]  py,
    input  wire [8:0]  hi_xmin,
    input  wire [8:0]  hi_ymin,
    input  wire [8:0]  hi_xmax,
    input  wire [8:0]  hi_ymax,
    input  wire [16:0] hi_area,
    output reg         used,
    output reg         touched,
    output reg  [1:0]  blk,
    output reg  [3:0]  link,
    output reg  [8:0]  xmin,
    output reg  [8:0]  ymin,
    output reg  [8:0]  xmax,
    output reg  [8:0]  ymax,
    output reg  [16:0] area
);
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            used <= 1'b0; touched <= 1'b0; blk <= 2'd0; link <= ID[3:0];
            xmin <= 9'd0; ymin <= 9'd0; xmax <= 9'd0; ymax <= 9'd0; area <= 17'd0;
        end else begin
            if (alias_set && link == alias_from) link <= alias_to;
            if (age) begin
                touched <= 1'b0;
                if (blk != 2'd0) blk <= blk - 2'd1;
            end
            if (alloc) begin
                used <= 1'b1; touched <= 1'b1; link <= ID[3:0];
                xmin <= px; xmax <= px; ymin <= py; ymax <= py; area <= 17'd1;
            end else if (ext) begin
                touched <= 1'b1;
                if (px < xmin) xmin <= px;
                if (px > xmax) xmax <= px;
                ymax <= py;
                area <= area + 17'd1;
            end else if (mrg_lo) begin
                touched <= 1'b1;
                xmin <= (hi_xmin < xmin) ? ((hi_xmin < px) ? hi_xmin : px) : ((xmin < px) ? xmin : px);
                xmax <= (hi_xmax > xmax) ? ((hi_xmax > px) ? hi_xmax : px) : ((xmax > px) ? xmax : px);
                ymin <= (hi_ymin < ymin) ? hi_ymin : ymin;
                ymax <= py;                                  // the current row is the lowest row seen so far
                area <= area + hi_area + 17'd1;
            end
            if (mrg_hi) begin
                used <= 1'b0; blk <= 2'd2;
            end
            if (fin) begin
                used <= 1'b0; link <= ID[3:0];
            end
            if (clr) begin
                used <= 1'b0; touched <= 1'b0; blk <= 2'd0; link <= ID[3:0];
            end
        end
    end
endmodule
