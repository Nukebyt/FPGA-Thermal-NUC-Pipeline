`timescale 1ns/1ps
// tick_gen.v -- source-pixel tick grid, locked to the VGA timing (roadmap Architecture decision 1).
//
// The pipeline runs at the VGA pixel clock. One "tick" = one slot of the source grid: (H+1+EXTRA) rows of (W+1)
// columns, i.e. the W x H image plus a dummy column and dummy rows that flush the 3x3 window stages so that border
// replication is exact. A tick occurs on every second VGA clock of every second VGA line, so a tick is always
// >= 2 clocks after the previous one (every downstream stage relies on that minimum spacing).
//
// Timing: the grid starts LEAD_LINES VGA lines before the first active line (source row 0 at VGA line
// V_TOTAL-LEAD_LINES), so the processed row r is ready in the display ping-pong buffer before VGA line 2r.
//
//   x, y   : free-running VGA counters from vga_timing (x = h counter 0..799, y = v counter 0..524, valid in blanking)
//   tick   : 1-clock pulse per grid slot
//   first  : with tick, marks slot (0,0) of the frame
//   eof    : with tick, marks slot (H,0), the end-of-frame reference used by the latency counters
// Registered outputs; tick/first are one clock after the (x,y) they describe.
module tick_gen #(
    parameter W          = 320,
    parameter H          = 240,
    parameter EXTRA      = 8,         // dummy rows after row H (>= number of 3x3 stages after the first, + 1)
    parameter V_TOTAL    = 525,
    parameter LEAD_LINES = 4          // must be even
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [10:0] x,
    input  wire [10:0] y,
    output reg         tick,
    output reg         first,
    output reg         eof             // with tick: grid slot (H, 0) = first dummy-row slot, 2 slots after the last real pixel
);
    // y shifted LEAD_LINES ahead, wrapped at V_TOTAL
    wire [10:0] ya = (y >= V_TOTAL - LEAD_LINES) ? (y - (V_TOTAL - LEAD_LINES)) : (y + LEAD_LINES);

    wire hit_x = (x[0] == 1'b0) && (x <= 2 * W);
    wire hit_y = (ya[0] == 1'b0) && (ya <= 2 * (H + EXTRA));

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            tick  <= 1'b0;
            first <= 1'b0;
            eof   <= 1'b0;
        end else begin
            tick  <= hit_x && hit_y;
            first <= hit_x && hit_y && (x == 11'd0) && (ya == 11'd0);
            eof   <= hit_x && hit_y && (x == 11'd0) && (ya == 2 * H);
        end
    end
endmodule
