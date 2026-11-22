# Host build of the portable firmware logic. Needs only gcc and make.
#     make test
FW := ../..
CC ?= gcc
CFLAGS := -std=c11 -Wall -Wextra -Werror -O1 -g \
    -I$(FW)/components/protocol/include -I$(FW)/components/mlx90614/include \
    -I$(FW)/components/emc2101/include -I$(FW)/components/buttons/include -I$(FW)/main

SRC := $(FW)/components/protocol/wp_frame.c \
       $(FW)/components/mlx90614/mlx90614.c \
       $(FW)/components/emc2101/emc2101.c \
       $(FW)/components/buttons/button_classify.c \
       $(FW)/main/thermal_logic.c \
       $(FW)/main/control_logic.c \
       test_main.c

build/test_main: $(SRC) $(wildcard $(FW)/components/*/include/*.h) $(wildcard $(FW)/main/*.h)
	@mkdir -p build
	$(CC) $(CFLAGS) $(SRC) -o $@

.PHONY: test clean
test: build/test_main
	./build/test_main

clean:
	rm -rf build
