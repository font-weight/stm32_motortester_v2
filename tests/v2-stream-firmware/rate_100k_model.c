/* Included after the exact-CEN logical model. This exercises real ADC/adapter/
 * queue/core code with logical DMA registers; it never models CPU throughput. */
#include "mt_live_adc.h"
static mt_live_adc binding;
static mt_live_device device;
static unsigned stop_calls;
static unsigned char wire_bytes[16384];
static size_t wire_used;
static size_t write_limit,write_calls,maximum_offer;
static bool write_unknown;
static uint64_t core_clock(void *p) { (void)p; return 1; }
static int core_start(void *p,uint32_t generation) { (void)p;(void)generation;return 1; }
static void core_stop(void *p,mt_live_snapshot *out) {
    (void)p;++stop_calls;mt_live_adc_quiesce(&binding,out);
}
extern size_t whole_fit_accept(const uint8_t *,size_t);
extern void whole_fit_space(size_t);
extern unsigned whole_fit_calls(void);
static size_t core_write(void *p,const uint8_t *bytes,size_t n) {
    (void)p;++write_calls;if(n>maximum_offer)maximum_offer=n;
    size_t accepted=whole_fit_accept(bytes,n);
    if(accepted==SIZE_MAX)return accepted;
    CHECK(accepted<=n && wire_used+accepted<=sizeof wire_bytes);
    memcpy(wire_bytes+wire_used,bytes,accepted);wire_used+=accepted;return accepted;
}
static int core_isolate(void *p) { (void)p;return 1; }
static void active(void) {
    setup(4);
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
    CHECK(*reg(0x40000428u)==71 && *reg(0x4000042cu)==9);
    CHECK(*reg(0x40012410u)==4 && *reg(0x4002000cu)==1024);
    CHECK(MT_ADC_DMA_RATE_HZ==100000 && MT_ADC_DMA_SAMPLE_US==10);
    CHECK(MT_ADC_DMA_BLOCK_SAMPLES==512 && MT_ADC_DMA_BLOCK_US==5120);
    CHECK(MT_SAMPLE_QUEUE_SLOTS==8 && MT_SAMPLE_QUEUE_BLOCK==128);
    /* Align logical acquisition history; no wall-clock claim is made. */
    driver.last_poll_us=adc_now(NULL);
    driver.last_progress_us=driver.last_poll_us;
    for(unsigned i=0;i<1024;i++) driver.dma_samples[i]=(uint16_t)(i&4095);
    memset(&binding,0,sizeof binding);
    binding.driver=&driver;binding.clock=&clock_state;binding.device=&device;
    binding.initialized=1;
    mt_live_io io={.clock_ms=core_clock,.start=core_start,.quiesce=core_stop,
        .write=core_write,.isolate_tx=core_isolate,.transaction_bound_ms=1,
        .firmware_build=
#ifdef MT_TEST_FIRMWARE_BUILD
          MT_TEST_FIRMWARE_BUILD
#else
          0x56325335u
#endif
        };
    CHECK(mt_live_device_init(&device,&io));
    device.state=MT_LIVE_STREAMING;device.generation=1;device.nonce=7;
    device.hardware_off=0;device.tx_next=1;device.rx_next=1;
    stop_calls=0;wire_used=0;write_calls=maximum_offer=0;
    write_limit=SIZE_MAX;write_unknown=false;
}
static void first_half(unsigned remaining) {
    *reg(0x40020000u)=4u; /* HT */
    *reg(0x4002000cu)=remaining;
}
static void check_queue(unsigned blocks,unsigned first) {
    CHECK(device.queue.used==blocks);
    for(unsigned b=0;b<blocks;b++) {
        unsigned slot=(device.queue.head+b)%MT_SAMPLE_QUEUE_SLOTS;
        CHECK(device.queue.counts[slot]==128);
        for(unsigned j=0;j<128;j++)
            CHECK(device.queue.samples[slot][j]==first+b*128+j);
    }
}
static void stop_command(void) {
    mt_wire_message m={.type=5,.session=7,.sequence=1,.request=2,.payload_length=4};
    m.payload[0]=1;
    uint8_t frame[MT_WIRE_FRAME_MAX];size_t n;
    CHECK(mt_wire_encode_revision(&m,0,2,frame,sizeof frame,&n)==MT_WIRE_OK);
    CHECK(mt_live_device_receive(&device,frame,n));
}
static uint32_t fixed_stamp;
static uint32_t fixed_adc_now(void *p) {(void)p;return fixed_stamp;}
int main(void) {
    CHECK(cen_regression_main()==0); /* New10/11us CEN-period gate. */
    active();first_half(500);
    driver.io.now_us=fixed_adc_now;
    fixed_stamp=driver.last_poll_us+5119u;
    mt_adc_dma_block_t block;
    CHECK(mt_adc_dma_read_block(&driver,&block)==MT_ADC_DMA_BLOCK);
    CHECK(block.nominal_rate_hz==100000 && block.first_trigger_offset_us==10 && block.count==512);
    active();first_half(500);driver.io.now_us=fixed_adc_now;
    fixed_stamp=driver.last_poll_us+5120u;
    CHECK(mt_adc_dma_read_block(&driver,&block)==MT_ADC_DMA_ERROR);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_DEADLINE && !driver.stream_history_valid);
    puts("PASS exact 100k TIM3/ADC config / DMA deadline5119 accepted,5120 rejected");

    active();first_half(500);CHECK(mt_live_adc_service(&binding)==1);
    whole_fit_space(0);CHECK(mt_live_device_step(&device));
    CHECK(device.tx_offset==0 && device.tx_next==1 && device.prefix_end==0 && device.queue.used==4);
    CHECK(whole_fit_calls()==0 && wire_used==0);
    size_t length=device.tx_length;
    CHECK(length>=306 && length<=307);
    whole_fit_space(length-1);CHECK(mt_live_device_step(&device));
    CHECK(device.tx_offset==0 && device.tx_next==1 && device.prefix_end==0 && device.queue.used==4);
    CHECK(whole_fit_calls()==0 && wire_used==0);
    whole_fit_space(length);CHECK(mt_live_device_step(&device));
    CHECK(whole_fit_calls()==1 && wire_used==length);
    CHECK(device.tx_next==2 && device.prefix_end==128 && device.queue.used==3);
    mt_wire_message msg;
    CHECK(mt_wire_decode_revision(wire_bytes,wire_used-1,0,2,&msg)==MT_WIRE_OK);
    CHECK(msg.type==152 && msg.sequence==1);
    for(unsigned i=0;i<128;i++)CHECK((msg.payload[20+2*i]|((unsigned)msg.payload[21+2*i]<<8))==i);
    puts("PASS actual whole-fit zero leaves FIFO/prefix/sequence; exact room commits one DATA128/CRC");

    active();whole_fit_space(384);device.state=MT_LIVE_STOPPED;device.hardware_off=1;
    device.want_caps=1;device.caps_request=1;
    CHECK(mt_live_device_step(&device));
    CHECK(mt_wire_decode_revision(wire_bytes,wire_used-1,0,2,&msg)==MT_WIRE_OK);
    uint32_t rate=(uint32_t)msg.payload[8]|((uint32_t)msg.payload[9]<<8)|
        ((uint32_t)msg.payload[10]<<16)|((uint32_t)msg.payload[11]<<24);
    CHECK(msg.type==130 && rate==100000 && msg.payload[16]==128);
    puts("PASS exact CAPS100000/1 / DATA128 unchanged");
    extern void whole_fit_boundaries(void);whole_fit_boundaries();
    return 0;
}
