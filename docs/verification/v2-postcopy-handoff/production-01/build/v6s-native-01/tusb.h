#ifndef MODEL_TUSB_H
#define MODEL_TUSB_H
#include <stdbool.h>
#include <stdint.h>
typedef struct {unsigned ignored;} dcd_event_t;
typedef struct {unsigned ignored;} tu_fifo_t;
typedef struct {unsigned ignored;} tusb_desc_endpoint_t;
typedef struct {unsigned ignored;} tusb_control_request_t;
uint32_t tud_cdc_n_write_available(uint8_t);
bool tud_task_event_ready(void);
#endif
