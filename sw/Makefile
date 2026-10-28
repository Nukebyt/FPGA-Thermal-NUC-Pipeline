# sw/Makefile -- build frame_feeder (run from WSL / Linux; on the board itself: gcc -std=gnu99 -O2 -o frame_feeder frame_feeder.c)
#   make            native x86 build with warnings (compile check)
#   make arm        static ARM binary for the DE10-Standard's Linux (arm-linux-gnueabihf-gcc), ready to scp
#   make mock       x86 build with -DMOCK (a model of the FPGA behind the same code) for sw/test_feeder.py
#   make test       build the mock and run the protocol / chase tests
#   make test-arm   the same with the mock built for ARM and run under qemu-arm (32-bit / ABI check)
CFLAGS = -std=gnu99 -O2 -Wall -Wextra -Werror
all: frame_feeder
frame_feeder: frame_feeder.c
	gcc $(CFLAGS) -o $@ $<
arm: frame_feeder.c
	arm-linux-gnueabihf-gcc $(CFLAGS) -static -o frame_feeder_arm $<
mock: frame_feeder.c
	gcc $(CFLAGS) -DMOCK -o frame_feeder_mock $<
mock-arm: frame_feeder.c
	arm-linux-gnueabihf-gcc $(CFLAGS) -DMOCK -static -o frame_feeder_mock_arm $<
test: mock
	python3 test_feeder.py
test-arm: mock-arm
	FEEDER_CMD="qemu-arm ./frame_feeder_mock_arm" python3 test_feeder.py
clean:
	rm -f frame_feeder frame_feeder_arm frame_feeder_mock frame_feeder_mock_arm
