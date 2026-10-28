`timescale 1ns/1ps
// thermal_board.v -- everything on the DE10-Standard that is not a host-bus master: PLL, reset, keys, LEDs, HEX, the design
// (thermal_sys) and the VGA / GPIO pads. thermal_top.v adds a JTAG-to-Avalon master, thermal_soc_top.v the HPS.
//
// Switches (SW):  0 NUC on    1 learning on   2 bad-pixel replace on   3 box overlay   4 sensor non-uniformity on
//                 6:5 noise preset (0 mild, 1 typical, 2 severe)   8:7 view (0 corrected, 1 raw, 2 split raw|corrected)
//                 9 iron palette.   (Ignored once a bus master sets CSR CTRL.csr_use.)
// Keys:  KEY0 reset   KEY1 clear NUC coefficients (re-learn from scratch)   KEY2 reset detector/frame state
//        KEY3 cycle the HEX page:  0 frame counter | 1 {boxes, K min} | 2 K max | 3 K max - K min (zero jitter -> 000000)
// LEDs:  0 CLOCK_50 heartbeat  1 clk25 heartbeat  2 PLL locked  3 design out of reset  4 ready  5 motion  6 bad pixels seen
//        7 box list overflow (sticky)  8 retimer overrun (sticky)
//        9 NUC learning runs (SW1 on and the LEARN_N window, 256 frames ~ 4 s after KEY1 / reset, still open)
// Host bus (Avalon-MM slave side, byte addresses, map in host_if.v): driven by the wrapper's master(s), so a laptop can read/write
// the CSRs, read captured frames and (FEED builds) write scene frames without a VGA monitor.
// GPIO header (GPIO_0 pins 1, 2): GPIO[0] toggles at the first input tick of each frame, GPIO[1] when the box list is
// published - measure the latency with a scope or logic analyser (roadmap 6.5).
module thermal_board #(
    parameter ROM_FILE = "rom_bg.hex",
    parameter [15:0] BUILD = 16'h0001,
    parameter FEED = 0
) (
    input  wire        CLOCK_50,
    input  wire [3:0]  KEY,
    input  wire [9:0]  SW,
    output wire [9:0]  LEDR,
    output wire [6:0]  HEX0, HEX1, HEX2, HEX3, HEX4, HEX5,
    output wire        VGA_CLK,
    output wire        VGA_HS,
    output wire        VGA_VS,
    output wire [7:0]  VGA_R,
    output wire [7:0]  VGA_G,
    output wire [7:0]  VGA_B,
    output wire        VGA_BLANK_N,
    output wire        VGA_SYNC_N,
    output wire [1:0]  GPIO,
    // host bus
    output wire        clk25,
    output wire        rst_n,
    input  wire [18:0] h_addr,
    input  wire        h_read, h_write,
    input  wire [31:0] h_wdata,
    output wire [31:0] h_rdata,
    output wire        h_rvalid
);
    // ---------------- clocks and reset (PLL lock gates the reset: checklist 2.6)
    wire pll_locked;
    pll25 u_pll (.refclk(CLOCK_50), .rst(1'b0), .outclk_0(clk25), .locked(pll_locked));
    reset_sync #(.STAGES(3)) u_rst (.clk(clk25), .rst_n_in(KEY[0] & pll_locked), .rst_n_out(rst_n));

    // ---------------- buttons
    wire k_coef, k_frame, k_page;
    key_pulse u_k1 (.clk(clk25), .rst_n(rst_n), .key_n(KEY[1]), .pulse(k_coef));
    key_pulse u_k2 (.clk(clk25), .rst_n(rst_n), .key_n(KEY[2]), .pulse(k_frame));
    key_pulse u_k3 (.clk(clk25), .rst_n(rst_n), .key_n(KEY[3]), .pulse(k_page));
    reg [1:0] page;
    always @(posedge clk25 or negedge rst_n) begin
        if (!rst_n) page <= 2'd0; else if (k_page) page <= page + 2'd1;
    end

    // ---------------- system
    wire st_ready, st_motion, st_bad, st_ovf, st_retime, st_gain, st_learn, pin_in, pin_flag;
    wire [31:0] st_frames, st_latf_min, st_latf_max;
    wire [7:0] st_nobj;
    thermal_sys #(.ROM_FILE(ROM_FILE), .BUILD(BUILD), .FEED(FEED)) u_sys (
        .clk(clk25), .rst_n(rst_n),
        .sw_nuc_en(SW[0]), .sw_learn_en(SW[1]), .sw_bp_en(SW[2]), .sw_overlay(SW[3]), .sw_noise_en(SW[4]),
        .sw_preset(SW[6:5]), .sw_view(SW[8:7]), .sw_iron(SW[9]),
        .key_coef_reset(k_coef), .key_frame_reset(k_frame),
        .av_address(h_addr), .av_read(h_read), .av_write(h_write), .av_writedata(h_wdata),
        .av_readdata(h_rdata), .av_readdatavalid(h_rvalid),
        .vga_hs_n(VGA_HS), .vga_vs_n(VGA_VS), .vga_de(VGA_BLANK_N), .vga_r(VGA_R), .vga_g(VGA_G), .vga_b(VGA_B),
        .st_ready(st_ready), .st_motion(st_motion), .st_bad_seen(st_bad), .st_ovf(st_ovf), .st_retime_err(st_retime),
        .st_gain(st_gain), .st_learn(st_learn), .st_frames(st_frames), .st_latf_min(st_latf_min), .st_latf_max(st_latf_max), .st_nobj(st_nobj),
        .pin_in_mark(pin_in), .pin_flag_mark(pin_flag));

    assign VGA_CLK    = clk25;
    assign VGA_SYNC_N = 1'b0;
    assign GPIO       = {pin_flag, pin_in};

    // ---------------- heartbeats, LEDs, HEX
    reg [25:0] hb50 = 26'd0;
    always @(posedge CLOCK_50) hb50 <= hb50 + 26'd1;
    reg [24:0] hb25;
    always @(posedge clk25 or negedge rst_n) begin
        if (!rst_n) hb25 <= 25'd0; else hb25 <= hb25 + 25'd1;
    end
    assign LEDR = {st_learn, st_retime, st_ovf, st_bad, st_motion, st_ready, rst_n, pll_locked, hb25[24], hb50[25]};

    wire [31:0] lat_jit = st_latf_max - st_latf_min;
    reg [23:0] hexv;
    always @(*) begin
        case (page)
            2'd0: hexv = st_frames[23:0];
            2'd1: hexv = {st_nobj, st_latf_min[15:0]};
            2'd2: hexv = {8'h00, st_latf_max[15:0]};
            default: hexv = lat_jit[23:0];
        endcase
    end
    hex7seg h0 (.d(hexv[3:0]),   .seg_n(HEX0));
    hex7seg h1 (.d(hexv[7:4]),   .seg_n(HEX1));
    hex7seg h2 (.d(hexv[11:8]),  .seg_n(HEX2));
    hex7seg h3 (.d(hexv[15:12]), .seg_n(HEX3));
    hex7seg h4 (.d(hexv[19:16]), .seg_n(HEX4));
    hex7seg h5 (.d(hexv[23:20]), .seg_n(HEX5));
endmodule
