/* V2 transport candidate. Board/clock assumptions NOT VERIFIED. */
/* Legacy verified_* names below carry configuration, not measurements. */
#include "mt_board_inputs.h"
#include "mt_firmware_build.h"
static const char v2_manufacturer[] = {102, 111, 110, 116, 45, 119, 101, 105, 103, 104, 116, 0};
static const char v2_product[] = {77, 111, 116, 111, 114, 116, 101, 115, 116, 101, 114, 32, 86, 50, 32, 66, 117, 105, 108, 100, 32, 66, 105, 110, 100, 105, 110, 103, 32, 83, 73, 0};
static const char v2_serial[] = {65, 72, 50, 48, 50, 54, 49, 48, 49, 55, 48, 48, 49, 0};
const mt_board_inputs mt_board = {
 .verified_hse_hz = 8000000u, .hse_mode = MT_CLOCK_CRYSTAL,
 .clock_poll_budget = 1000000u, .usb_irq_priority = 0u,
 .firmware_build = MT_FIRMWARE_BUILD, .require_dtr = 1u,
 .verified_fixed_pullup = 1u,
 .usb = {.vid = 0x1209u, .pid = 1u, .bcd_device = 0x0200u,
 .bus_power_ma = 100u, .manufacturer = v2_manufacturer,
 .product = v2_product, .serial = v2_serial}
};
