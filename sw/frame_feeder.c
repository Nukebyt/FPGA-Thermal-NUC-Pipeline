/* frame_feeder.c -- ARM-side front end of the thermal design (roadmap Phase 3b). Runs on the DE10-Standard's HPS Linux.
 *
 * WHAT IT DOES
 *   The design's host bus (rtl/host_if.v) is reachable from Linux through the HPS lightweight HPS-to-FPGA bridge:
 *   physical 0xFF200000 + byte address (quartus/ip/hps_sys, bridge base 0). This program owns /dev/mem and offers:
 *     * register / buffer access over TCP (the laptop viewer host/viewer.py --net reads the CSRs, the captured frame and the box
 *       list with it: about 10x faster than JTAG, no USB-Blaster needed);
 *     * FEED: stream clips into the design. A frame (W*H bytes, raster order, 8 bit) is written into the scene frame store
 *       (rtl/scene_buf.v) "chasing" the scan, see below;
 *     * `play`: loop a raw clip stored on the board (no laptop needed), `bench`: measure the bridge, `info`.
 *   Modelled on the Weibull-CFAR project's cfar_server.c (same board, same Linux image, same /dev/mem approach).
 *
 * THE CHASE (why no frame is ever torn)
 *   The frame store holds ONE frame (no RAM for a second one) and the emulator scans it at 60 Hz. FEED_ROW (CSR word 0x25) counts
 *   the source rows the scan has finished reading, G. Let k = G / H when a feed starts. For r = 0..H-1 the writer waits until the
 *   scan has finished row r of frame k (G > k*H + r), then writes row r. So frame k shows only old rows, and because every row
 *   is rewritten before the scan comes back to it (G < (k+1)*H + r, one frame time later), frame k+1 shows only new rows. The
 *   writer may start at any phase. If the ARM is too slow for a row (G >= (k+1)*H + r - 1 when it gets to it) the frame is
 *   counted as torn (reported in the reply and in STAT) - on the real design this should stay at zero (bench tells the margin).
 *
 * PROTOCOL (TCP, default port 5002, little endian; one request -> one reply; several clients at a time are served in turn)
 *   request: u32 magic 'THRM' (bytes 'T','H','R','M'), u32 cmd, u32 a, u32 b, then the payload of the command
 *   reply:   u32 magic, i32 status, u32 n (payload bytes), u32 x, then n payload bytes
 *     PING  0           -> x = value of the ID register (0x7A11xxxx: xxxx = build), n = 0
 *     RD    1 a=byte address, b=words           -> n = 4*b: the words
 *     WR    2 a=byte address, b=value           -> -
 *     WRB   3 a=byte address, b=words, payload 4*b bytes
 *     FEED  4 b=bytes (= W*H), payload b bytes  -> x = index of the display frame in which the new content first shows
 *                                                  status 0 ok, 1 torn (written anyway), 2 scan not running, 3 bad size
 *     STAT  5           -> n = 40: u32 feeds, torn, errors, last_us, max_us, min_us, rows_read, clients, bus_reads, bus_writes
 *   Bus addresses: 0x00000 CSRs (word a at 4a), 0x20000 capture buffer (read), 0x40000 scene buffer (write), see host_if.v.
 *
 * BUILD  (the board's gcc defaults to gnu89: -std=gnu99 is required; or cross-compile, see sw/Makefile)
 *     gcc -std=gnu99 -O2 -Wall -Wextra -o frame_feeder frame_feeder.c
 *   -DMOCK builds a model of the FPGA (scan clock, buffers, a few CSRs) so the protocol and the chase can be tested on a PC:
 *   sw/test_feeder.py. The mock counts torn displayed frames independently of the writer's own check.
 * RUN (root, needs /dev/mem)      sudo ./frame_feeder serve [port]
 *                                  sudo ./frame_feeder play clip.u8 [fps] [loop]     raw 8-bit frames, W*H bytes each
 *                                  sudo ./frame_feeder bench | info
 */
#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <signal.h>
#include <poll.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>

#define W 320
#define H 240
#define WORDS_PER_ROW (W / 4)
#define FRAME_BYTES (W * H)
#define FRAME_WORDS (FRAME_BYTES / 4)

#define LW_BASE 0xFF200000UL
#define LW_SPAN 0x00080000UL          /* 19-bit host bus window */
#define A_CSR 0x00000u
#define A_CAP 0x20000u
#define A_FEED 0x40000u
#define CSR_ID 0x00u
#define CSR_CAP 0x0Eu
#define CSR_CAPS 0x23u
#define CSR_FEED_CTRL 0x24u
#define CSR_FEED_ROW 0x25u

#define MAGIC 0x4D524854u             /* 'T','H','R','M' */
enum { CMD_PING = 0, CMD_RD = 1, CMD_WR = 2, CMD_WRB = 3, CMD_FEED = 4, CMD_STAT = 5 };
enum { ST_OK = 0, ST_TORN = 1, ST_NOSCAN = 2, ST_BADSIZE = 3, ST_BADCMD = 4, ST_BADADDR = 5 };

#define ROW_NS (1000000000L / (60 * H))          /* one source row at 60 frames/s */
#define STALL_MS 300                              /* the scan counter has not moved for this long: the design is not running */

struct stats { uint32_t feeds, torn, errors, last_us, max_us, min_us, rows, clients, bus_reads, bus_writes; };
static struct stats st = { 0, 0, 0, 0, 0, 0xFFFFFFFFu, 0, 0, 0, 0 };
static volatile sig_atomic_t stop_flag = 0;

/* ------------------------------------------------------------------------------------------------- bus */
#ifdef MOCK
/* A model of the FPGA side: scan clock = wall clock, one frame store, a capture buffer showing the last complete display frame.
 * Every bus operation first advances the scan to "now", so the content a row had when the scan read it is known exactly. */
static uint32_t m_csr[256];
static uint32_t m_scene[FRAME_WORDS];
static uint32_t m_cap[FRAME_WORDS];
static uint64_t m_g0_ns;                 /* wall clock at G = 0 */
static uint64_t m_g_seen;                /* rows already processed */
static uint32_t m_row_tag[H];            /* tag (first byte) of the content each row has now */
static uint32_t m_frame_tags[H];
static uint64_t m_cap_arm_frame = (uint64_t)-1;
uint32_t mock_displayed_torn = 0, mock_displayed_frames = 0;
static FILE *m_log = NULL;
static int m_freeze = 0;                  /* MOCK_FREEZE_SCAN: the scan counter never moves (a design that is not running) */
static uint64_t m_wdelay_ns = 0;          /* MOCK_WRITE_DELAY_NS: make every feed-buffer write this slow (provokes torn frames) */

static uint64_t now_ns(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec; }

static void mock_advance(void)
{
    if (m_freeze) return;
    uint64_t g = (now_ns() - m_g0_ns) / ROW_NS;
    for (; m_g_seen < g; m_g_seen++) {
        uint32_t r = (uint32_t)(m_g_seen % H);
        m_frame_tags[r] = m_row_tag[r];                                   /* what the scan read from row r just now */
        if (r == H - 1) {                                                 /* a display frame is complete */
            int same = 1;
            for (uint32_t i = 1; i < H; i++) if (m_frame_tags[i] != m_frame_tags[0]) same = 0;
            mock_displayed_frames++;
            if (!same) mock_displayed_torn++;
            if (m_log) fprintf(m_log, "frame %llu tag %u %s\n", (unsigned long long)(m_g_seen / H), m_frame_tags[0], same ? "ok" : "TORN");
            if (m_cap_arm_frame != (uint64_t)-1 && m_g_seen / H >= m_cap_arm_frame) {      /* capture of this frame */
                memcpy(m_cap, m_scene, sizeof m_cap);
                m_csr[CSR_CAP] = (m_csr[CSR_CAP] & 1u) | (1u << 17);
                m_csr[0x0F] = (uint32_t)(m_g_seen / H);
                m_cap_arm_frame = (uint64_t)-1;
            }
        }
    }
}
static void bus_open(void)
{
    m_g0_ns = now_ns(); m_g_seen = 0;
    memset(m_csr, 0, sizeof m_csr);
    m_csr[CSR_ID] = 0x7A110006u; m_csr[CSR_CAPS] = 1; m_csr[CSR_FEED_CTRL] = 1; m_csr[1] = 0x2BFu; m_csr[0x10] = 1; m_csr[0x0D] = 256;
    const char *lg = getenv("MOCK_LOG");
    if (lg) m_log = fopen(lg, "w");
    m_freeze = getenv("MOCK_FREEZE_SCAN") != NULL;
    if (getenv("MOCK_WRITE_DELAY_NS")) m_wdelay_ns = (uint64_t)atoll(getenv("MOCK_WRITE_DELAY_NS"));
}
static uint32_t bus_rd(uint32_t a)
{
    mock_advance(); st.bus_reads++;
    if (a >= A_FEED) return 0;
    if (a >= A_CAP) return m_cap[(a - A_CAP) >> 2];
    uint32_t w = a >> 2;
    if (w == CSR_FEED_ROW) return (uint32_t)m_g_seen;
    if (w == 0x11) return (uint32_t)(m_g_seen / H);                       /* FRAMES */
    return m_csr[w & 255];
}
static void bus_wr(uint32_t a, uint32_t v)
{
    mock_advance(); st.bus_writes++;
    if (m_wdelay_ns && a >= A_FEED) { uint64_t t = now_ns(); while (now_ns() - t < m_wdelay_ns) { } mock_advance(); }
    if (a >= A_FEED) {
        uint32_t k = (a - A_FEED) >> 2;
        if (k < FRAME_WORDS) {
            m_scene[k] = v;
            if (k % WORDS_PER_ROW == 0) m_row_tag[k / WORDS_PER_ROW] = v & 0xFF;          /* first pixel of the row = the frame's tag */
        }
        return;
    }
    if (a >= A_CAP) return;
    uint32_t w = (a >> 2) & 255;
    if (w == CSR_CAP) { m_csr[w] = v & 1u; if (v & 0x100u) m_cap_arm_frame = m_g_seen / H + 2; return; }
    if (w == CSR_FEED_ROW || w == CSR_ID || w == CSR_CAPS) return;
    m_csr[w] = v;
}
static void bus_close(void) { if (m_log) fclose(m_log); }
#else
static volatile uint32_t *bus;
static void bus_open(void)
{
    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) { perror("open /dev/mem (run as root)"); exit(1); }
    void *p = mmap(NULL, LW_SPAN, PROT_READ | PROT_WRITE, MAP_SHARED, fd, LW_BASE);
    if (p == MAP_FAILED) { perror("mmap lightweight bridge"); exit(1); }
    close(fd);
    bus = (volatile uint32_t *)p;
}
static inline uint32_t bus_rd(uint32_t a) { st.bus_reads++; return bus[a >> 2]; }
static inline void bus_wr(uint32_t a, uint32_t v) { st.bus_writes++; bus[a >> 2] = v; }
static void bus_close(void) {}
#endif

/* ------------------------------------------------------------------------------------------------- helpers */
static uint64_t mono_us(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return (uint64_t)t.tv_sec * 1000000ull + (uint64_t)t.tv_nsec / 1000u; }
static void sleep_ns(long ns) { struct timespec t = { ns / 1000000000L, ns % 1000000000L }; nanosleep(&t, NULL); }

static uint32_t rows_read(void) { return bus_rd((A_CSR) + 4u * CSR_FEED_ROW); }

/* Wait until the scan has finished row `target` (G > target). Returns 0, or -1 if the counter does not move for STALL_MS. */
static int wait_scan_past(uint32_t target, uint32_t *g_out)
{
    uint32_t g = rows_read(), last = g;
    uint64_t t_move = mono_us();
    while (!(g > target)) {                          /* wrap-safe for the distances involved (< 2^31) */
        uint32_t need = target - g + 1;
        if (need > 3) sleep_ns((long)(need - 2) * ROW_NS);
        g = rows_read();
        if (g != last) { last = g; t_move = mono_us(); }
        else if (mono_us() - t_move > STALL_MS * 1000ull) return -1;
    }
    *g_out = g;
    return 0;
}

/* Write one frame (FRAME_WORDS words, raster, 4 pixels per word) behind the scan. Returns ST_*; *shown = display frame index. */
static int feed_frame(const uint32_t *frame, uint32_t *shown)
{
    uint64_t t0 = mono_us();
    uint32_t g;
    uint32_t g0 = rows_read();
    uint32_t k = g0 / H;
    int torn = 0;
    for (uint32_t r = 0; r < H; r++) {
        if (wait_scan_past(k * H + r, &g) < 0) { st.errors++; return ST_NOSCAN; }
        if (g + 1 >= (k + 1) * H + r) torn = 1;      /* the scan is (nearly) back at this row already: too slow */
        const uint32_t *src = frame + (size_t)r * WORDS_PER_ROW;
        for (uint32_t w = 0; w < WORDS_PER_ROW; w++) bus_wr(A_FEED + 4u * ((uint32_t)r * WORDS_PER_ROW + w), src[w]);
    }
    uint32_t us = (uint32_t)(mono_us() - t0);
    st.feeds++; st.last_us = us; if (us > st.max_us) st.max_us = us; if (us < st.min_us) st.min_us = us;
    if (torn) st.torn++;
    *shown = k + 1;
    return torn ? ST_TORN : ST_OK;
}

static int read_exact(int fd, void *buf, size_t n)
{
    uint8_t *p = (uint8_t *)buf; size_t got = 0;
    while (got < n) {
        ssize_t r = read(fd, p + got, n - got);
        if (r == 0) return -1;
        if (r < 0) { if (errno == EINTR) continue; return -1; }
        got += (size_t)r;
    }
    return 0;
}
static int write_exact(int fd, const void *buf, size_t n)
{
    const uint8_t *p = (const uint8_t *)buf; size_t sent = 0;
    while (sent < n) {
        ssize_t w = send(fd, p + sent, n - sent, MSG_NOSIGNAL);
        if (w <= 0) { if (w < 0 && errno == EINTR) continue; return -1; }
        sent += (size_t)w;
    }
    return 0;
}
static int reply(int fd, int32_t status, const void *payload, uint32_t n, uint32_t x)
{
    uint32_t h[4] = { MAGIC, (uint32_t)status, n, x };
    if (!n) return write_exact(fd, h, sizeof h);
    /* header + payload leave as one stream: two small sends make a client wait for a delayed ACK (40 ms per register read) */
    if (send(fd, h, sizeof h, MSG_NOSIGNAL | MSG_MORE) != (ssize_t)sizeof h) return -1;
    return write_exact(fd, payload, n);
}

static uint32_t *frame_buf;                          /* FRAME_WORDS words, 4-byte aligned, filled from the socket */
static uint32_t *blk_buf;                            /* RD / WRB staging, up to FRAME_WORDS words */

/* One request from a client. Returns 0 to keep the connection, -1 to drop it. */
static int serve_one(int fd)
{
    uint32_t h[4];
    if (read_exact(fd, h, sizeof h) < 0) return -1;
    if (h[0] != MAGIC) return -1;
    uint32_t cmd = h[1], a = h[2], b = h[3];
    switch (cmd) {
    case CMD_PING:
        return reply(fd, ST_OK, NULL, 0, bus_rd(A_CSR + 4u * CSR_ID));
    case CMD_RD:
        if ((a & 3u) || a >= LW_SPAN || b == 0 || b > FRAME_WORDS || a + 4u * b > LW_SPAN) return reply(fd, ST_BADADDR, NULL, 0, 0);
        for (uint32_t i = 0; i < b; i++) blk_buf[i] = bus_rd(a + 4u * i);
        return reply(fd, ST_OK, blk_buf, 4u * b, 0);
    case CMD_WR:
        if ((a & 3u) || a >= LW_SPAN) return reply(fd, ST_BADADDR, NULL, 0, 0);
        bus_wr(a, b);
        return reply(fd, ST_OK, NULL, 0, 0);
    case CMD_WRB:
        if ((a & 3u) || b == 0 || b > FRAME_WORDS || a + 4u * b > LW_SPAN) return -1;     /* payload would desynchronise: drop */
        if (read_exact(fd, blk_buf, 4u * b) < 0) return -1;
        for (uint32_t i = 0; i < b; i++) bus_wr(a + 4u * i, blk_buf[i]);
        return reply(fd, ST_OK, NULL, 0, 0);
    case CMD_FEED: {
        if (b != FRAME_BYTES) return -1;
        if (read_exact(fd, frame_buf, FRAME_BYTES) < 0) return -1;
        uint32_t shown = 0;
        int s = feed_frame(frame_buf, &shown);
        return reply(fd, s, NULL, 0, shown);
    }
    case CMD_STAT: {
        st.rows = rows_read();
        return reply(fd, ST_OK, &st, sizeof st, 0);
    }
    default:
        return reply(fd, ST_BADCMD, NULL, 0, 0);
    }
}

static void on_signal(int s) { (void)s; stop_flag = 1; }

static int serve(int port)
{
    int ls = socket(AF_INET, SOCK_STREAM, 0);
    int one = 1;
    setsockopt(ls, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
    struct sockaddr_in sa; memset(&sa, 0, sizeof sa);
    sa.sin_family = AF_INET; sa.sin_addr.s_addr = htonl(INADDR_ANY); sa.sin_port = htons((uint16_t)port);
    if (bind(ls, (struct sockaddr *)&sa, sizeof sa) < 0 || listen(ls, 4) < 0) { perror("bind/listen"); return 1; }
    fprintf(stderr, "frame_feeder: listening on port %d, host bus ID %08x\n", port, bus_rd(A_CSR + 4u * CSR_ID));
    struct pollfd pf[1 + 4];
    int nc = 0;
    int cfd[4];
    while (!stop_flag) {
        pf[0].fd = ls; pf[0].events = POLLIN;
        for (int i = 0; i < nc; i++) { pf[1 + i].fd = cfd[i]; pf[1 + i].events = POLLIN; }
        int n = poll(pf, (nfds_t)(1 + nc), 500);
        if (n < 0) { if (errno == EINTR) continue; break; }
        if (n == 0) continue;
        int npolled = nc;                              /* only these have a valid revents; a client accepted below waits for the next poll */
        if (pf[0].revents & POLLIN) {
            int c = accept(ls, NULL, NULL);
            if (c >= 0) {
                struct timeval tv = { 5, 0 };
                setsockopt(c, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv);
                setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
                if (nc < 4) { cfd[nc++] = c; st.clients++; } else close(c);
            }
        }
        for (int i = 0; i < npolled && i < nc; ) {
            if (pf[1 + i].revents & (POLLIN | POLLHUP | POLLERR)) {
                if (serve_one(cfd[i]) < 0) {
                    close(cfd[i]);
                    nc--; npolled--;
                    cfd[i] = cfd[nc]; pf[1 + i] = pf[1 + nc];         /* the last client moves into slot i: re-test it */
                    if (nc >= npolled) pf[1 + i].revents = 0;          /* ... unless it was accepted after the poll */
                    continue;
                }
            }
            i++;
        }
    }
    for (int i = 0; i < nc; i++) close(cfd[i]);
    close(ls);
    return 0;
}

/* play: loop a raw clip from a file */
static int play(const char *path, double fps, int loop)
{
    FILE *f = fopen(path, "rb");
    if (!f) { perror(path); return 1; }
    fseek(f, 0, SEEK_END); long sz = ftell(f); fseek(f, 0, SEEK_SET);
    long nfr = sz / FRAME_BYTES;
    if (nfr < 1) { fprintf(stderr, "%s: smaller than one %dx%d frame\n", path, W, H); return 1; }
    uint8_t *clip = (uint8_t *)malloc((size_t)nfr * FRAME_BYTES);
    if (!clip || fread(clip, 1, (size_t)nfr * FRAME_BYTES, f) != (size_t)nfr * FRAME_BYTES) { fprintf(stderr, "read error\n"); return 1; }
    fclose(f);
    bus_wr(A_CSR + 4u * CSR_FEED_CTRL, 0);           /* the clip brings its own objects */
    fprintf(stderr, "playing %ld frames of %s at %.1f fps%s\n", nfr, path, fps, loop ? " (loop)" : "");
    uint64_t t_start = mono_us();
    for (long n = 0; !stop_flag && (loop || n < nfr); n++) {
        memcpy(frame_buf, clip + (size_t)(n % nfr) * FRAME_BYTES, FRAME_BYTES);
        uint32_t shown;
        int s = feed_frame(frame_buf, &shown);
        if (s == ST_NOSCAN) { fprintf(stderr, "the scan counter does not move: is the FPGA image running?\n"); return 1; }
        uint64_t due = t_start + (uint64_t)((double)(n + 1) * 1e6 / fps);
        uint64_t now = mono_us();
        if (due > now) sleep_ns((long)(due - now) * 1000L);
        if (n % 60 == 59) fprintf(stderr, "frame %ld shown as %u, torn %u, write %u us (max %u)\n", n + 1, shown, st.torn, st.last_us, st.max_us);
    }
    free(clip);
    return 0;
}

static int bench(void)
{
    uint32_t id = bus_rd(A_CSR + 4u * CSR_ID);
    printf("ID %08x  CAPS %u  scan rows %u\n", id, bus_rd(A_CSR + 4u * CSR_CAPS), rows_read());
    uint64_t t0 = mono_us();
    for (int i = 0; i < 20000; i++) (void)bus_rd(A_CSR + 4u * CSR_ID);
    uint64_t t1 = mono_us();
    printf("read  : %.2f us per 32-bit CSR read\n", (double)(t1 - t0) / 20000.0);
    memset(frame_buf, 0x40, FRAME_BYTES);
    t0 = mono_us();
    for (uint32_t i = 0; i < FRAME_WORDS; i++) bus_wr(A_FEED + 4u * i, frame_buf[i]);
    t1 = mono_us();
    printf("write : %.2f us per 32-bit write, %.2f ms for a whole frame (a display frame is 16.7 ms; the chase needs well under)\n",
           (double)(t1 - t0) / FRAME_WORDS, (double)(t1 - t0) / 1000.0);
    t0 = mono_us();
    for (uint32_t i = 0; i < FRAME_WORDS; i++) blk_buf[i] = bus_rd(A_CAP + 4u * i);
    t1 = mono_us();
    printf("capture readout: %.2f ms for 76,800 bytes (%.1f frames/s for the viewer)\n", (double)(t1 - t0) / 1000.0, 1e6 / (double)(t1 - t0));
    uint32_t g = rows_read();
    sleep_ns(100L * 1000000L);
    uint32_t g2 = rows_read();
    printf("scan  : %u rows in 100 ms (expected about %d)  -> %s\n", g2 - g, 100 * 60 * H / 1000, (g2 - g) > 0 ? "running" : "NOT RUNNING");
    uint32_t shown;
    uint32_t fed = 0;
    int s = ST_OK;
    for (int i = 0; i < 20 && s != ST_NOSCAN; i++) { s = feed_frame(frame_buf, &shown); fed++; }
    printf("feed  : %u frames, torn %u, last write %u us, min %u us, max %u us\n", fed, st.torn, st.last_us, st.min_us, st.max_us);
    return 0;
}

int main(int argc, char **argv)
{
    const char *mode = argc > 1 ? argv[1] : "serve";
    signal(SIGINT, on_signal); signal(SIGTERM, on_signal); signal(SIGPIPE, SIG_IGN);
    if (posix_memalign((void **)&frame_buf, 64, FRAME_BYTES) || posix_memalign((void **)&blk_buf, 64, FRAME_BYTES)) { fprintf(stderr, "out of memory\n"); return 1; }
    bus_open();
    int rc = 0;
    if (!strcmp(mode, "serve")) rc = serve(argc > 2 ? atoi(argv[2]) : 5002);
    else if (!strcmp(mode, "play") && argc > 2) rc = play(argv[2], argc > 3 ? atof(argv[3]) : 60.0, argc > 4 && !strcmp(argv[4], "loop"));
    else if (!strcmp(mode, "bench")) rc = bench();
    else if (!strcmp(mode, "info")) {
        printf("ID %08x  CAPS %u  FEED_CTRL %u  scan rows %u\n", bus_rd(A_CSR + 4u * CSR_ID), bus_rd(A_CSR + 4u * CSR_CAPS),
               bus_rd(A_CSR + 4u * CSR_FEED_CTRL), rows_read());
    } else {
        fprintf(stderr, "usage: %s serve [port] | play clip.u8 [fps] [loop] | bench | info\n", argv[0]);
        rc = 2;
    }
#ifdef MOCK
    fprintf(stderr, "mock: %u displayed frames, %u torn\n", mock_displayed_frames, mock_displayed_torn);
    FILE *r = fopen(getenv("MOCK_RESULT") ? getenv("MOCK_RESULT") : "/dev/null", "w");
    if (r) { fprintf(r, "frames %u torn %u feeds %u feed_torn %u\n", mock_displayed_frames, mock_displayed_torn, st.feeds, st.torn); fclose(r); }
#endif
    bus_close();
    return rc;
}
