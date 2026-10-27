#include <stdint.h>
typedef struct {uint32_t previous;unsigned entered;} mt_usb_scope;
uint32_t mt_usb_bridge_lock(void);
void mt_usb_bridge_unlock(uint32_t);
int mt_usb_bridge_app_enter(mt_usb_scope*);
void mt_usb_bridge_leave(mt_usb_scope*);
