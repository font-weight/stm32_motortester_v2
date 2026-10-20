/* Exact upstream bitwise codec and prefix function are independent oracles.
 * This checks bytes/states, never native execution speed as Cortex-M3 timing. */
#include "mt_wire.h"
#include "mt_v2_crc32.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define CHECK(x) do { if(!(x)) { fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x); exit(1); } } while(0)
uint32_t oracle_mt_wire_crc32(const uint8_t *,size_t);
mt_wire_result oracle_mt_wire_encode_revision(const mt_wire_message *,uint8_t,uint8_t,uint8_t *,size_t,size_t *);
mt_wire_result oracle_mt_wire_decode_revision(const uint8_t *,size_t,uint8_t,uint8_t,mt_wire_message *);

static uint32_t oracle_crc_codes(uint32_t crc,const uint16_t *p,uint16_t count) {
    unsigned i,b,k;
    for(i=0;i<count;i++)for(b=0;b<2;b++) {
        crc^=(uint8_t)(p[i]>>(8u*b));
        for(k=0;k<8;k++)crc=(crc>>1)^((crc&1u)?UINT32_C(0xedb88320):0u);
    }
    return crc;
}
static uint32_t crc_codes(uint32_t crc,const uint16_t *p,uint16_t count) {
    unsigned i;
    for(i=0;i<count;i++) {
        crc=mt_v2_crc32_byte(crc,(uint8_t)p[i]);
        crc=mt_v2_crc32_byte(crc,(uint8_t)(p[i]>>8));
    }
    return crc;
}


static uint32_t read_u32(FILE *f) {
    uint8_t b[4];CHECK(fread(b,1,4,f)==4);
    return (uint32_t)b[0]|((uint32_t)b[1]<<8)|((uint32_t)b[2]<<16)|((uint32_t)b[3]<<24);
}
static void equal_frame(const uint8_t *frame,size_t size) {
    mt_wire_message old={0},now={0};
    uint8_t encoded[MT_WIRE_FRAME_MAX],reference[MT_WIRE_FRAME_MAX];
    size_t a=0,b=0;
    CHECK(size>1 && frame[size-1]==0);
    CHECK(oracle_mt_wire_decode_revision(frame,size-1,0,2,&old)==MT_WIRE_OK);
    CHECK(mt_wire_decode_revision(frame,size-1,0,2,&now)==MT_WIRE_OK);
    CHECK(memcmp(&old,&now,sizeof old)==0);
    CHECK(mt_wire_encode_revision(&now,0,2,encoded,sizeof encoded,&a)==MT_WIRE_OK);
    CHECK(oracle_mt_wire_encode_revision(&old,0,2,reference,sizeof reference,&b)==MT_WIRE_OK);
    CHECK(a==size && b==size && memcmp(encoded,frame,size)==0 && memcmp(reference,frame,size)==0);
}
int main(void) {
    uint8_t bytes[MT_WIRE_RAW_MAX],out[MT_WIRE_FRAME_MAX],reference[MT_WIRE_FRAME_MAX];
    uint16_t codes[128];
    for(unsigned i=0;i<sizeof bytes;i++)bytes[i]=(uint8_t)(37u*i+(i%7u==0?0:19u));
    CHECK(mt_wire_crc32(NULL,0)==0);
    CHECK(mt_wire_crc32((const uint8_t *)"123456789",9)==UINT32_C(0xcbf43926));
    for(unsigned i=0;i<256;i++) {
        uint8_t byte=(uint8_t)i;
        CHECK(mt_wire_crc32(&byte,1)==oracle_mt_wire_crc32(&byte,1));
        uint32_t state=i;
        for(unsigned bit=0;bit<8;bit++)state=(state>>1)^((state&1u)?UINT32_C(0xedb88320):0u);
        CHECK(mt_v2_crc32_table[i]==state);
    }
    for(size_t n=0;n<=sizeof bytes;n++)
        CHECK(mt_wire_crc32(bytes,n)==oracle_mt_wire_crc32(bytes,n));
    puts("PASS all256 table/byte values / known CRC / lengths0..540");

    mt_wire_message message={0};
    message.type=0x98;message.session=UINT64_C(0x0123456789abcdef);
    message.sequence=0x12345678u;message.request=0;
    for(unsigned i=0;i<MT_WIRE_PAYLOAD_MAX;i++)message.payload[i]=bytes[i];
    for(unsigned n=0;n<=MT_WIRE_PAYLOAD_MAX;n++) {
        size_t a=0,b=0;message.payload_length=(uint16_t)n;
        CHECK(mt_wire_encode_revision(&message,0,2,out,sizeof out,&a)==MT_WIRE_OK);
        CHECK(oracle_mt_wire_encode_revision(&message,0,2,reference,sizeof reference,&b)==MT_WIRE_OK);
        CHECK(a==b && memcmp(out,reference,a)==0);
        equal_frame(out,a);
    }
    FILE *wire=fopen("actual-frames.bin","rb");CHECK(wire);
    uint32_t frames=read_u32(wire);
    for(uint32_t i=0;i<frames;i++) {
        uint32_t n=read_u32(wire);CHECK(n<=sizeof out);
        CHECK(fread(out,1,n,wire)==n);equal_frame(out,n);
    }
    CHECK(fgetc(wire)==EOF);fclose(wire);
    printf("PASS full wire payload lengths0..512 / %u actual traffic frames\n",(unsigned)frames);

    for(unsigned i=0;i<128;i++)codes[i]=(uint16_t)(503u*i);
    for(unsigned n=0;n<=128;n++) {
        for(unsigned seed=0;seed<3;seed++) {
            uint32_t state=seed==0?0u:seed==1?UINT32_C(0xffffffff):UINT32_C(0x13579bdf);
            CHECK(crc_codes(state,codes,(uint16_t)n)==oracle_crc_codes(state,codes,(uint16_t)n));
            unsigned split=n/3u;
            uint32_t chunked=crc_codes(state,codes,(uint16_t)split);
            chunked=crc_codes(chunked,codes+split,(uint16_t)(n-split));
            CHECK(chunked==oracle_crc_codes(state,codes,(uint16_t)n));
        }
    }
    FILE *raw=fopen("actual-codes.bin","rb");CHECK(raw);
    uint32_t count=read_u32(raw),expected=read_u32(raw);
    CHECK(count>0 && count<=1000000u);
    uint16_t *actual=malloc((size_t)count*sizeof *actual);CHECK(actual);
    for(uint32_t i=0;i<count;i++) {
        int low=fgetc(raw),high=fgetc(raw);CHECK(low>=0 && high>=0);
        actual[i]=(uint16_t)((unsigned)low|((unsigned)high<<8));
    }
    CHECK(fgetc(raw)==EOF);fclose(raw);
    const unsigned chunks[]={1,17,127,128};
    for(unsigned k=0;k<sizeof chunks/sizeof chunks[0];k++) {
        uint32_t old=UINT32_C(0xffffffff),now=old,offset=0;
        while(offset<count) {
            unsigned n=count-offset<chunks[k]?count-offset:chunks[k];
            old=oracle_crc_codes(old,actual+offset,(uint16_t)n);
            now=crc_codes(now,actual+offset,(uint16_t)n);
            CHECK(old==now);offset+=n;
        }
        CHECK((now^UINT32_C(0xffffffff))==expected);
    }
    free(actual);
    printf("PASS explicit LE incremental prefix / chunking1,17,127,128 / %u actual raw codes\n",(unsigned)count);
    return 0;
}
