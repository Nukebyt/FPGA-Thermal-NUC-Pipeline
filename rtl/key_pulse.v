`timescale 1ns/1ps
// key_pulse.v -- debounced push-button (active low) -> one clock-wide pulse on press.
// 2-flop synchroniser, then the level must be stable for 2**DEB_BITS clocks before it is accepted
// (DEB_BITS = 17 at 25 MHz is ~5.2 ms). Testbench overrides DEB_BITS (checklist 1.16: real-world counters need a parameter).
module key_pulse #(
    parameter DEB_BITS = 17
) (
    input  wire clk,
    input  wire rst_n,
    input  wire key_n,
    output reg  pulse
);
    reg s1, s2, stable;
    reg [DEB_BITS-1:0] cnt;
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            s1 <= 1'b1; s2 <= 1'b1; stable <= 1'b1; cnt <= {DEB_BITS{1'b0}}; pulse <= 1'b0;
        end else begin
            s1 <= key_n; s2 <= s1; pulse <= 1'b0;
            if (s2 == stable) cnt <= {DEB_BITS{1'b0}};
            else begin
                cnt <= cnt + 1'b1;
                if (&cnt) begin
                    stable <= s2;
                    if (!s2) pulse <= 1'b1;            // accepted a press (falling edge of the level)
                end
            end
        end
    end
endmodule
