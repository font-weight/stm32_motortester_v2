/* Included after the exact-CEN logical model. This exercises real ADC/adapter/
 * queue/core code with logical DMA registers; it never models CPU throughput. */
#include "mt_live_adc.h"
static mt_live_adc binding;
static mt_live_device device;
static unsigned stop_calls;
static unsigned char wire_bytes[16384];
static size_t wire_used;
static uint64_t core_clock(void *p) { (void)p; return 1; }
static int core_start(void *p,uint32_t generation) { (void)p;(void)generation;return 1; }
static void core_stop(void *p,mt_live_snapshot *out) {
    (void)p;++stop_calls;mt_live_adc_quiesce(&binding,out);
}
static size_t core_write(void *p,const uint8_t *bytes,size_t n) {
    (void)p;CHECK(wire_used+n<=sizeof wire_bytes);
    memcpy(wire_bytes+wire_used,bytes,n);wire_used+=n;return n;
}
static int core_isolate(void *p) { (void)p;return 1; }
static void active(void) {
    setup(4);
    CHECK(mt_adc_dma_start_transaction(&driver,&guard,transaction)==MT_ADC_DMA_OK);
    CHECK(*reg(0x40000428u)==71 && *reg(0x4000042cu)==4);
    CHECK(*reg(0x40012410u)==4 && *reg(0x4002000cu)==1024);
    CHECK(MT_ADC_DMA_RATE_HZ==200000 && MT_ADC_DMA_SAMPLE_US==5);
    CHECK(MT_ADC_DMA_BLOCK_SAMPLES==512 && MT_ADC_DMA_BLOCK_US==2560);
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
        .firmware_build=0x56325335u};
    CHECK(mt_live_device_init(&device,&io));
    device.state=MT_LIVE_STREAMING;device.generation=1;device.nonce=7;
    device.hardware_off=0;device.tx_next=1;device.rx_next=1;
    stop_calls=0;wire_used=0;
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
int main(void) {
    CHECK(cen_regression_main()==0);
    active();first_half(500);
    CHECK(mt_live_adc_service(&binding)==1);
    CHECK(driver.first_sample_index==512 && device.queue.next_index==512);
    check_queue(4,0);
    /* Logical IFCR effects are applied between calls, as hardware would. */
    *reg(0x40020000u)=2u;*reg(0x4002000cu)=1000;
    CHECK(mt_live_adc_service(&binding)==1);
    CHECK(driver.first_sample_index==1024 && device.queue.next_index==1024);
    check_queue(8,0);
    puts("PASS 200k config / ADC41.5 / DMA1024 / ordered two halves to DATA128");

    for(unsigned half=0;half<2;half++) {
        active();driver.next_half=half!=0;driver.first_sample_index=half?512:0;
        /* Both states retain 1023 pending transfers across the circular end. */
        *reg(0x40020000u)=half?2u:4u;
        *reg(0x4002000cu)=half?513u:1u;
        mt_live_snapshot out;
        mt_live_adc_quiesce(&binding,&out);
        CHECK(out.hardware_off==1 && out.produced_known==0 && out.produced_end==0);
        CHECK(out.acquisition_reason==0 && out.tail_count==8);
        for(unsigned b=0;b<8;b++) {
            CHECK(out.tail[b].first_index==(half?512u:0u)+b*128);
            CHECK(out.tail[b].count==(b==7?127u:128u));
            for(unsigned j=0;j<out.tail[b].count;j++)
                CHECK(out.tail[b].codes[j]==((half?512u:0u)+b*128+j)%1024);
        }
        mt_live_snapshot again;mt_live_adc_quiesce(&binding,&again);
        CHECK(!memcmp(&out,&again,sizeof out));
    }
    puts("PASS frozen Stop tail1023 / eight DATA chunks / both circular halves / unknown produced");

    active();first_half(1);stop_command();
    CHECK(device.state==MT_LIVE_DRAINING && device.first_reason==0 && stop_calls==1);
    CHECK(device.queue.used==8 && device.queue.next_index==1023 && device.queue.sealed);
    CHECK(device.hardware_off==1 && device.produced_known==0);
    for(unsigned i=0;i<100 && !device.end_complete;i++)CHECK(mt_live_device_step(&device));
    CHECK(device.end_complete && device.prefix_end==1023 && device.terminal_flags==3);
    size_t cursor=0;unsigned frame_count=0,code_count=0;
    while(cursor<wire_used) {
        size_t end=cursor;while(end<wire_used && wire_bytes[end])++end;
        CHECK(end<wire_used);
        mt_wire_message m;
        CHECK(mt_wire_decode_revision(wire_bytes+cursor,end-cursor,0,2,&m)==MT_WIRE_OK);
        if(m.type==152) {
            unsigned count=(unsigned)m.payload[16]|((unsigned)m.payload[17]<<8);
            for(unsigned j=0;j<count;j++) {
                unsigned code=m.payload[20+2*j]|((unsigned)m.payload[21+2*j]<<8);
                CHECK(code==code_count++);
            }
            ++frame_count;
        }
        cursor=end+1;
    }
    CHECK(code_count==1023 && frame_count==8);
    puts("PASS real core Stop validation / serialization / raw order / END unknown tail");

    for(unsigned free_slots=0;free_slots<4;free_slots++) {
        active();uint16_t filler[128]={0};
        unsigned existing=8-free_slots;
        for(unsigned b=0;b<8;b++)CHECK(mt_live_device_offer(&device,b*128,filler,128));
        for(unsigned b=0;b<free_slots;b++)
            CHECK(mt_sample_queue_pop(&device.queue,b*128)==MT_SAMPLE_QUEUE_OK);
        device.prefix_end=free_slots*128;
        CHECK(device.queue.used==existing && device.queue.head_index==free_slots*128);
        driver.first_sample_index=1024;
        first_half(500);
        CHECK(mt_live_adc_service(&binding)==-1);
        CHECK(device.queue.sealed && device.queue.first_fault==MT_SAMPLE_QUEUE_FULL);
        CHECK(device.first_reason==1 && stop_calls==1 && device.queue.used==8);
        CHECK(device.queue.next_index==1024+free_slots*128);
        CHECK(device.hardware_off==1);
    }
    puts("PASS queue full at each of four split chunks / no offer across a gap");

    active();first_half(500);*reg(0x40020000u)=6; /* HT and TC: history lost. */
    CHECK(mt_live_adc_service(&binding)==-1);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_DEADLINE && !driver.stream_history_valid);
    CHECK(device.queue.used==0 && device.first_reason==2);
    active();first_half(500);
    ticks+=2560;
    CHECK(mt_live_adc_service(&binding)==-1);
    CHECK(driver.first_fault==MT_ADC_DMA_FAULT_DEADLINE && device.queue.used==0);
    puts("PASS missed DMA boundary and late service reject without invented samples");

    active();device.state=MT_LIVE_STOPPED;device.hardware_off=1;device.want_caps=1;
    device.caps_request=1;
    for(unsigned i=0;i<10 && device.want_caps;i++)CHECK(mt_live_device_step(&device));
    CHECK(wire_used>0 && wire_bytes[wire_used-1]==0);
    mt_wire_message caps;
    CHECK(mt_wire_decode_revision(wire_bytes,wire_used-1,0,2,&caps)==MT_WIRE_OK);
    CHECK(caps.type==130 && caps.payload_length==24);
    uint32_t rate=(uint32_t)caps.payload[8]|((uint32_t)caps.payload[9]<<8)|
        ((uint32_t)caps.payload[10]<<16)|((uint32_t)caps.payload[11]<<24);
    CHECK(rate==200000 && caps.payload[16]==128 && caps.payload[17]==0);
    puts("PASS exact 200000/1 CAPS with unchanged DATA128 wire envelope");
    return 0;
}
