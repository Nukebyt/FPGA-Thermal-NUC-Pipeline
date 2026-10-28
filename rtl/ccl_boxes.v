`timescale 1ns/1ps
// ccl_boxes.v -- single-pass streaming connected-component bounding boxes, 4-connectivity, fixed resources.
// Bit-exact twin of pipeline_int.ccl_boxes() (that function is the specification of label allocation, merge,
// delayed slot reuse and result order).
//
// Resources: NL = 16 label slots (ccl_slot), a label line buffer (RAM, 512 x 5), MAXOBJ = 16 result slots.
// Behaviour when a limit is exceeded: NEVER stalls. Slots exhausted -> that pixel is dropped and `ovf` is set;
// result list full -> the object is still counted in n_obj and `ovf` is set.
//
// Event timing assumptions (documented in docs/design.md):
//   * pixel events (ivalid) are >= 2 clocks apart (tick spacing);
//   * after the last pixel of a line the next pixel event is >= 40 clocks away (the end-of-line scan takes 17);
//   * after the last pixel of a frame the next frame's first pixel is >= 80 clocks away (flush + publish = 36).
//   The lockstep VGA design has >= 900 clocks of row gap and >= 40,000 clocks of frame gap.
//
// Fixed latency: fdone is exactly LAT_EOF = 36 clocks after the clock in which the last pixel of the frame
// (cr = H-1, cc = W-1) is presented on ivalid, independent of the picture content.
//
// Box record (53 bits): {area[16:0], ymax[8:0], xmax[8:0], ymin[8:0], xmin[8:0]}.
module ccl_boxes #(
    parameter W = 320,
    parameter H = 240
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire        ivalid,
    input  wire        imask,
    input  wire [8:0]  icr,
    input  wire [8:0]  icc,
    input  wire [15:0] min_area,
    output reg         fdone,
    output reg  [7:0]  pub_n,                 // objects with area >= min_area (saturating at 255)
    output reg  [4:0]  pub_cnt,               // number of valid records in pub_boxes (<= 16)
    output reg         pub_ovf,
    output reg  [16*53-1:0] pub_boxes
);
    localparam NL = 16;
    localparam LAT_EOF = 36;

    // ---------------------------------------------------------------- E0: label line buffer read
    wire [4:0] nraw;
    reg  [4:0] lab_wdata;
    reg        lab_we;
    reg  [8:0] lab_waddr;
    ram_sdp #(.DW(5), .AW(9), .DEPTH(512)) labram (
        .clk(clk), .we(lab_we), .waddr(lab_waddr), .wdata(lab_wdata), .raddr(icc), .rdata(nraw));

    reg        ev_q, mask_q;
    reg [8:0]  cc_q, cr_q;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin ev_q <= 1'b0; mask_q <= 1'b0; cc_q <= 9'd0; cr_q <= 9'd0; end
        else begin ev_q <= ivalid; mask_q <= imask; cc_q <= icc; cr_q <= icr; end
    end

    // ---------------------------------------------------------------- slot array
    wire [NL-1:0]   used_v, touched_v;
    wire [NL*2-1:0] blk_v;
    wire [NL*4-1:0] alias_v;
    wire [NL*9-1:0] xmin_v, ymin_v, xmax_v, ymax_v;
    wire [NL*17-1:0] area_v;

    reg  [NL-1:0] alloc_oh, ext_oh, mlo_oh, mhi_oh, fin_oh;
    reg           age_p, clr_p;
    reg           alias_set;
    reg  [3:0]    alias_from, alias_to;
    reg  [8:0]    hi_xmin, hi_ymin, hi_xmax, hi_ymax;
    reg  [16:0]   hi_area;

    genvar gk;
    generate
        for (gk = 0; gk < NL; gk = gk + 1) begin : g_slot
            ccl_slot #(.ID(gk)) u (
                .clk(clk), .rst_n(rst_n),
                .alloc(alloc_oh[gk]), .ext(ext_oh[gk]), .mrg_lo(mlo_oh[gk]), .mrg_hi(mhi_oh[gk]),
                .fin(fin_oh[gk]), .age(age_p), .clr(clr_p),
                .alias_set(alias_set), .alias_from(alias_from), .alias_to(alias_to),
                .px(cc_q), .py(cr_q),
                .hi_xmin(hi_xmin), .hi_ymin(hi_ymin), .hi_xmax(hi_xmax), .hi_ymax(hi_ymax), .hi_area(hi_area),
                .used(used_v[gk]), .touched(touched_v[gk]), .blk(blk_v[gk*2 +: 2]), .link(alias_v[gk*4 +: 4]),
                .xmin(xmin_v[gk*9 +: 9]), .ymin(ymin_v[gk*9 +: 9]), .xmax(xmax_v[gk*9 +: 9]), .ymax(ymax_v[gk*9 +: 9]),
                .area(area_v[gk*17 +: 17]));
        end
    endgenerate

    // ---------------------------------------------------------------- E1: decision (combinational)
    reg        left_v;
    reg [3:0]  left_idx;
    wire       n_valid = mask_q && (cr_q != 9'd0) && nraw[4];
    wire [3:0] n_idx   = alias_v[nraw[3:0]*4 +: 4];
    wire       w_valid = mask_q && (cc_q != 9'd0) && left_v;
    wire [3:0] w_idx   = alias_v[left_idx*4 +: 4];

    reg        any_free;
    reg [3:0]  alloc_idx;
    integer    ki;
    always @(*) begin
        any_free = 1'b0; alloc_idx = 4'd0;
        for (ki = NL - 1; ki >= 0; ki = ki - 1) begin
            if (!used_v[ki] && blk_v[ki*2 +: 2] == 2'd0) begin
                any_free = 1'b1; alloc_idx = ki[3:0];
            end
        end
    end

    wire both_no  = mask_q & ~n_valid & ~w_valid;
    wire do_alloc = ev_q & both_no & any_free;
    wire ovf_alloc = ev_q & both_no & ~any_free;
    wire do_merge = ev_q & mask_q & n_valid & w_valid & (n_idx != w_idx);
    wire do_ext   = ev_q & mask_q & (n_valid | w_valid) & ~do_merge;
    wire [3:0] lo_idx = (n_idx < w_idx) ? n_idx : w_idx;
    wire [3:0] hi_idx = (n_idx < w_idx) ? w_idx : n_idx;
    wire [3:0] ext_idx = n_valid ? n_idx : w_idx;
    wire       cur_v   = do_alloc | do_merge | do_ext;
    wire [3:0] cur_idx = do_alloc ? alloc_idx : do_merge ? lo_idx : ext_idx;

    // scan FSM state (declared here: used by the command mux below)
    localparam S_IDLE = 3'd0, S_EOL = 3'd1, S_AGE = 3'd2, S_FLUSH = 3'd3, S_PUB = 3'd4;
    reg [2:0] st;
    reg [4:0] ks;                    // scan index 0..15
    reg       eof_f;
    wire      scan_active = (st == S_EOL) || (st == S_FLUSH);
    wire      scan_sel = (st == S_EOL) ? (used_v[ks[3:0]] & ~touched_v[ks[3:0]]) : (used_v[ks[3:0]]);

    // results
    reg [16*53-1:0] res_flat;
    reg [4:0]  res_cnt;
    reg [7:0]  n_obj;
    reg        ovf;
    wire [52:0] scan_box = {area_v[ks[3:0]*17 +: 17], ymax_v[ks[3:0]*9 +: 9], xmax_v[ks[3:0]*9 +: 9],
                            ymin_v[ks[3:0]*9 +: 9], xmin_v[ks[3:0]*9 +: 9]};
    wire        scan_big = (area_v[ks[3:0]*17 +: 17] >= {1'b0, min_area});

    integer km;
    always @(*) begin
        alloc_oh = {NL{1'b0}}; ext_oh = {NL{1'b0}}; mlo_oh = {NL{1'b0}}; mhi_oh = {NL{1'b0}}; fin_oh = {NL{1'b0}};
        for (km = 0; km < NL; km = km + 1) begin
            alloc_oh[km] = do_alloc && (alloc_idx == km);
            ext_oh[km]   = do_ext   && (ext_idx == km);
            mlo_oh[km]   = do_merge && (lo_idx == km);
            mhi_oh[km]   = do_merge && (hi_idx == km);
            fin_oh[km]   = scan_active && scan_sel && (ks[3:0] == km);
        end
        alias_set  = do_merge;
        alias_from = hi_idx;
        alias_to   = lo_idx;
        hi_xmin = xmin_v[hi_idx*9 +: 9];
        hi_ymin = ymin_v[hi_idx*9 +: 9];
        hi_xmax = xmax_v[hi_idx*9 +: 9];
        hi_ymax = ymax_v[hi_idx*9 +: 9];
        hi_area = area_v[hi_idx*17 +: 17];
        age_p = (st == S_AGE);
        clr_p = (st == S_PUB);
    end

    // label line buffer write + left register (end of E1)
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            lab_we <= 1'b0; lab_waddr <= 9'd0; lab_wdata <= 5'd0; left_v <= 1'b0; left_idx <= 4'd0;
        end else begin
            lab_we <= ev_q; lab_waddr <= cc_q; lab_wdata <= {cur_v, cur_idx};
            if (ev_q) begin left_v <= cur_v; left_idx <= cur_idx; end
        end
    end

    integer rk;
    // ---------------------------------------------------------------- scan / publish FSM
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            st <= S_IDLE; ks <= 5'd0; eof_f <= 1'b0; res_flat <= {16*53{1'b0}}; res_cnt <= 5'd0; n_obj <= 8'd0;
            ovf <= 1'b0; fdone <= 1'b0; pub_n <= 8'd0; pub_cnt <= 5'd0; pub_ovf <= 1'b0; pub_boxes <= {16*53{1'b0}};
        end else begin
            fdone <= 1'b0;
            if (ovf_alloc) ovf <= 1'b1;
            case (st)
                S_IDLE: begin
                    if (ev_q && (cc_q == W - 1)) begin
                        st <= S_EOL; ks <= 5'd0; eof_f <= (cr_q == H - 1);
                    end
                end
                S_EOL, S_FLUSH: begin
                    if (scan_sel && scan_big) begin
                        n_obj <= (n_obj == 8'd255) ? 8'd255 : n_obj + 8'd1;
                        if (res_cnt < 5'd16) begin
                            // 16 fixed slots with one enable each (a variable-position part-select write into the
                            // 848-bit vector synthesises as a huge shifter: build 4, bug log 21)
                            for (rk = 0; rk < 16; rk = rk + 1)
                                if (res_cnt[3:0] == rk) res_flat[rk*53 +: 53] <= scan_box;
                            res_cnt <= res_cnt + 5'd1;
                        end else ovf <= 1'b1;
                    end
                    if (ks == 5'd15) begin
                        ks <= 5'd0;
                        st <= (st == S_EOL) ? S_AGE : S_PUB;
                    end else ks <= ks + 5'd1;
                end
                S_AGE: begin
                    st <= eof_f ? S_FLUSH : S_IDLE;
                    ks <= 5'd0;
                end
                S_PUB: begin
                    pub_boxes <= res_flat; pub_n <= n_obj; pub_cnt <= res_cnt; pub_ovf <= ovf;
                    fdone <= 1'b1;
                    res_cnt <= 5'd0; n_obj <= 8'd0; ovf <= 1'b0; eof_f <= 1'b0;
                    st <= S_IDLE;
                end
                default: st <= S_IDLE;
            endcase
        end
    end
endmodule
