`timescale 1ns/1ps
// thermal_sys.v -- the whole design on the 25 MHz pixel clock, without pads or PLL (so a testbench can drive it directly).
//
//   vga_timing -> tick_gen -> sensor_emu -> thermal_core -> disp_path -> VGA
//                                              |
//                                              |           \-> frame_cap (one frame on request)
//                              host bus -> host_if -> csr_regs (switches or host)
//                                              \-> scene_buf -> sensor_emu   (FEED = 1: real clips written by the host)
//
// Control source: the board switches until a bus master sets CTRL.csr_use; numeric parameters always come from the CSRs
// (their reset values are the validated defaults).
// Documented assumptions: tick spacing is exactly 2 clocks (tick_gen), >= 40,000 clocks between frames.
module thermal_sys #(
    parameter W  = 320,
    parameter H  = 240,
    parameter AW = 17,
    parameter ROM_FILE = "rom_bg.hex",
    parameter [15:0] BUILD = 16'h0001,
    parameter FEED = 0                      // 1: the emulator's scene comes from the host-written frame store (no ROM)
) (
    input  wire        clk,
    input  wire        rst_n,
    // switch-mode controls
    input  wire        sw_nuc_en, sw_learn_en, sw_bp_en, sw_overlay, sw_noise_en, sw_iron,
    input  wire [1:0]  sw_preset, sw_view,
    input  wire        key_coef_reset, key_frame_reset,        // 1-clock pulses (debounced by the top)
    // host bus (Avalon-MM slave, byte addresses; map in host_if.v): JTAG master now, HPS bridge later
    input  wire [18:0] av_address,
    input  wire        av_read, av_write,
    input  wire [31:0] av_writedata,
    output wire [31:0] av_readdata,
    output wire        av_readdatavalid,
    // VGA
    output wire        vga_hs_n, vga_vs_n, vga_de,
    output wire [7:0]  vga_r, vga_g, vga_b,
    // status for LEDs / HEX / scope
    output wire        st_ready, st_motion, st_bad_seen, st_ovf, st_retime_err, st_gain, st_learn,
    output wire [31:0] st_frames, st_latf_min, st_latf_max,
    output wire [7:0]  st_nobj,
    output wire        pin_in_mark,                            // toggles at the first input tick of each frame
    output wire        pin_flag_mark                           // toggles when the box list is published
);
    // ---------------------------------------------------------------- video timing + tick grid
    wire        hs_n, vs_n, de, sof, vblank;
    wire [10:0] vx, vy;
    vga_timing u_vt (.clk(clk), .rst_n(rst_n), .hs_n(hs_n), .vs_n(vs_n), .de(de), .sof(sof), .vblank(vblank), .x(vx), .y(vy));

    wire tick, first, eof;
    tick_gen #(.W(W), .H(H), .EXTRA(8)) u_tg (.clk(clk), .rst_n(rst_n), .x(vx), .y(vy), .tick(tick), .first(first), .eof(eof));

    // ---------------------------------------------------------------- controls
    wire c_nuc, c_learn, c_bp, c_ovl, c_noise, c_use, c_iron;
    wire [1:0] c_preset, c_view;
    wire [13:0] c_bpt, c_tmask, c_tlo;
    wire [9:0] c_emin, c_emax;
    wire [7:0] c_warm;
    wire [15:0] c_thr, c_area, c_learn_n;
    wire [3:0] c_tsh;
    wire c_tauto, c_coef_rst, c_frame_rst, c_obj;

    wire nuc_en     = c_use ? c_nuc   : sw_nuc_en;
    wire learn_en   = c_use ? c_learn : sw_learn_en;
    wire bp_en      = c_use ? c_bp    : sw_bp_en;
    wire overlay_en = c_use ? c_ovl   : sw_overlay;
    wire noise_en   = c_use ? c_noise : sw_noise_en;
    wire iron       = c_use ? c_iron  : sw_iron;
    wire [1:0] preset = c_use ? c_preset : sw_preset;
    wire [1:0] view   = c_use ? c_view   : sw_view;
    wire coef_reset  = c_coef_rst  | key_coef_reset;
    wire frame_reset = c_frame_rst | key_frame_reset;

    // ---------------------------------------------------------------- sensor emulator
    wire        e_tick, e_first;
    wire [13:0] e_x;
    wire [14:0] e_clean;
    wire        e_gtm;
    wire [AW-1:0] sc_addr;
    wire [7:0]    sc_q;
    wire          sc_row_done;
    wire [31:0]   feed_rows;
    wire          fw_we;
    wire [14:0]   fw_addr;
    wire [31:0]   fw_data;
    sensor_emu #(.W(W), .H(H), .AW(AW), .INIT_FILE(ROM_FILE), .FEED(FEED)) u_emu (
        .clk(clk), .rst_n(rst_n), .tick(tick), .first(first), .preset(preset), .noise_en(noise_en), .obj_en(c_obj),
        .scene_addr(sc_addr), .scene_q(sc_q), .row_done(sc_row_done),
        .otick(e_tick), .ofirst(e_first), .x_out(e_x), .clean_out(e_clean), .gt_motion(e_gtm));
    generate
        if (FEED != 0) begin : g_scene
            scene_buf #(.NW((W * H + 3) / 4)) u_scene (
                .clk(clk), .rst_n(rst_n), .saddr(sc_addr[16:0]), .sq(sc_q), .row_done(sc_row_done), .rows_read(feed_rows),
                .hw_we(fw_we), .hw_addr(fw_addr), .hw_data(fw_data));
        end else begin : g_noscene
            assign sc_q = 8'd0;
            assign feed_rows = 32'd0;
        end
    endgenerate

    // ---------------------------------------------------------------- core
    wire        ready, y_tick, y_first, y_valid, y_bad, m_valid, m_bit, box_done, box_ovf, nuc_fdone, det_fdone, det_valid, retime_err, gain_act, learn_act;
    wire [8:0]  y_cr, y_cc, m_cr, m_cc;
    wire [13:0] y_val, x_val;
    wire [7:0]  box_n, det_n;
    wire [4:0]  box_cnt;
    wire [16*53-1:0] box_rec;
    wire [39:0] nuc_sum;
    wire [11:0] nuc_lim;
    wire [31:0] det_act;
    thermal_core #(.W(W), .H(H), .AW(AW)) u_core (
        .clk(clk), .rst_n(rst_n), .tick(e_tick), .first(e_first), .x_in(e_x),
        .nuc_en(nuc_en), .learn_en(learn_en), .bp_en(bp_en), .bp_t(c_bpt), .emin(c_emin), .emax(c_emax),
        .t_mask(c_tmask), .det_warm(c_warm), .act_thr(c_thr), .min_area(c_area),
        .learn_n(c_learn_n), .coef_reset(coef_reset), .frame_reset(frame_reset), .ready(ready),
        .y_tick(y_tick), .y_first(y_first), .y_valid(y_valid), .y_cr(y_cr), .y_cc(y_cc), .y_val(y_val), .x_val(x_val), .y_bad(y_bad),
        .m_valid(m_valid), .m_cr(m_cr), .m_cc(m_cc), .m_bit(m_bit),
        .box_done(box_done), .box_n(box_n), .box_cnt(box_cnt), .box_ovf(box_ovf), .box_rec(box_rec),
        .nuc_fdone(nuc_fdone), .nuc_sum_abs_e(nuc_sum), .nuc_lim(nuc_lim),
        .det_fdone(det_fdone), .det_act_sum(det_act), .det_n_after(det_n), .det_valid(det_valid),
        .retime_err(retime_err), .gain_active(gain_act), .learning(learn_act));

    // bad-pixel count per frame
    reg [31:0] bad_cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) bad_cnt <= 32'd0;
        else if (y_first && y_tick) bad_cnt <= 32'd0;
        else if (y_valid && y_bad) bad_cnt <= bad_cnt + 32'd1;
    end

    // ---------------------------------------------------------------- host bus, frame capture
    wire        bus_wr, bus_rd;
    wire [7:0]  bus_addr;
    wire [31:0] bus_wdata, bus_rdata, fb_rdata, cap_fid;
    wire [14:0] fb_raddr;
    wire        cap_arm, cap_src, cap_busy, cap_done;
    wire        cap_v, cap_first;
    wire [7:0]  cap_c8, cap_r8;
    host_if #(.FAW(15)) u_host (
        .clk(clk), .rst_n(rst_n), .av_address(av_address), .av_read(av_read), .av_write(av_write),
        .av_writedata(av_writedata), .av_readdata(av_readdata), .av_readdatavalid(av_readdatavalid),
        .csr_wr(bus_wr), .csr_rd(bus_rd), .csr_addr(bus_addr), .csr_wdata(bus_wdata), .csr_rdata(bus_rdata),
        .fb_raddr(fb_raddr), .fb_rdata(fb_rdata), .fw_we(fw_we), .fw_addr(fw_addr), .fw_data(fw_data));
    frame_cap #(.W(W), .H(H), .AW(15)) u_cap (
        .clk(clk), .rst_n(rst_n), .pv(cap_v), .pfirst(cap_first), .pc8(cap_c8), .pr8(cap_r8),
        .arm(cap_arm), .src(cap_src), .busy(cap_busy), .done(cap_done), .cap_fid(cap_fid),
        .raddr(fb_raddr), .rdata(fb_rdata));

    // ---------------------------------------------------------------- CSRs and latency events
    wire ev_first = tick & first;
    wire ev_eof   = tick & eof;
    wire ev_y00   = y_valid && (y_cr == 9'd0) && (y_cc == 9'd0);
    csr_regs #(.BUILD(BUILD), .FEED(FEED)) u_csr (
        .clk(clk), .rst_n(rst_n), .wr(bus_wr), .rd(bus_rd), .addr(bus_addr), .wdata(bus_wdata), .rdata(bus_rdata),
        .nuc_en(c_nuc), .learn_en(c_learn), .bp_en(c_bp), .overlay_en(c_ovl), .noise_en(c_noise), .csr_use(c_use), .iron(c_iron),
        .preset(c_preset), .view(c_view), .bp_t(c_bpt), .emin(c_emin), .emax(c_emax), .t_mask(c_tmask), .det_warm(c_warm),
        .act_thr(c_thr), .min_area(c_area), .tone_lo(c_tlo), .tone_sh(c_tsh), .tone_auto(c_tauto), .obj_en(c_obj), .feed_rows(feed_rows), .learn_n(c_learn_n),
        .cap_arm(cap_arm), .cap_src(cap_src), .cap_busy(cap_busy), .cap_done(cap_done), .cap_fid(cap_fid),
        .coef_reset(c_coef_rst), .frame_reset(c_frame_rst),
        .ready(ready), .retime_err(retime_err), .box_ovf_now(box_ovf), .bad_seen_now(bad_cnt != 32'd0), .det_valid(det_valid),
        .gain_active(gain_act), .learning(learn_act), .box_done(box_done), .box_n(box_n), .box_cnt(box_cnt), .box_rec(box_rec),
        .det_fdone(det_fdone), .det_act_sum(det_act), .det_n_after(det_n),
        .nuc_fdone(nuc_fdone), .nuc_sum_abs_e(nuc_sum), .nuc_lim(nuc_lim), .bad_count(bad_cnt),
        .ev_first_in(ev_first), .ev_eof_in(ev_eof), .ev_y00(ev_y00),
        .o_frames(st_frames), .o_lat_pix(), .o_lat_flag(), .o_latf_min(st_latf_min), .o_latf_max(st_latf_max),
        .o_latp_min(), .o_latp_max());

    // ---------------------------------------------------------------- display
    disp_path #(.W(W), .H(H)) u_disp (
        .clk(clk), .rst_n(rst_n),
        .y_first(y_first & y_tick), .y_valid(y_valid), .y_cr(y_cr), .y_cc(y_cc), .y_val(y_val), .x_val(x_val),
        .vx(vx), .vy(vy), .vde(de), .vhs_n(hs_n), .vvs_n(vs_n),
        .view(view), .iron(iron), .overlay_en(overlay_en), .tone_auto(c_tauto), .tone_lo(c_tlo), .tone_sh(c_tsh),
        .box_cnt(box_cnt), .box_rec(box_rec),
        .vga_r(vga_r), .vga_g(vga_g), .vga_b(vga_b), .vga_hs_n(vga_hs_n), .vga_vs_n(vga_vs_n), .vga_de(vga_de),
        .cap_v(cap_v), .cap_first(cap_first), .cap_c8(cap_c8), .cap_r8(cap_r8));

    // ---------------------------------------------------------------- status
    assign st_ready = ready;
    assign st_motion = (box_n != 8'd0);
    assign st_bad_seen = (bad_cnt != 32'd0);
    assign st_ovf = box_ovf;
    assign st_retime_err = retime_err;
    assign st_gain = gain_act;
    assign st_learn = learn_act;
    assign st_nobj = box_n;

    // scope markers (roadmap 6.5): toggle at the first input tick and at box publication
    reg m_in, m_flag;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin m_in <= 1'b0; m_flag <= 1'b0; end
        else begin
            if (ev_first) m_in <= ~m_in;
            if (box_done) m_flag <= ~m_flag;
        end
    end
    assign pin_in_mark = m_in;
    assign pin_flag_mark = m_flag;
endmodule
