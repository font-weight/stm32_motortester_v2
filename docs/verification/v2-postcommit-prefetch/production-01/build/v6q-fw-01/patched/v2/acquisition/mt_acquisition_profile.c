#include "mt_acquisition_profile.h"

static const mt_acquisition_profile profiles[5] = {
    {50000u,10240u,1u,71u,19u,20u,1u,20u,12u,1u,128u},
    {100000u,5120u,2u,71u,9u,10u,1u,10u,12u,1u,128u},
    {150000u,3413u,3u,47u,9u,20u,3u,5u,10u,2u,128u},
    {150000u,3413u,4u,47u,9u,20u,3u,5u,10u,2u,256u},
    {150000u,3413u,5u,47u,9u,20u,3u,5u,10u,2u,1024u},
};
const mt_acquisition_profile *mt_acquisition_profile_get(uint16_t mode) {
    return mode>=1u && mode<=5u ? &profiles[mode-1u] : NULL;
}
size_t mt_acquisition_pack(const mt_acquisition_profile *p,
    const uint16_t *codes,uint16_t count,uint8_t *out,size_t capacity) {
    size_t length,used=0; unsigned i,bits=0; uint32_t pending=0;
    if(!p || p!=mt_acquisition_profile_get(p->mode) || !codes || !out ||
       !count || count>128u)return 0;
    length=p->encoding==2u ? ((size_t)count*10u+7u)/8u : (size_t)count*2u;
    if(capacity<length)return 0;
    for(i=0;i<count;i++)
        if(codes[i]>4095u || (p->encoding==2u && (codes[i]&3u)))return 0;
    if(p->encoding==1u) {
        for(i=0;i<count;i++) {
            out[2u*i]=(uint8_t)codes[i];out[2u*i+1u]=(uint8_t)(codes[i]>>8);
        }
    } else {
        for(i=0;i<count;i++) {
            pending|=(uint32_t)(codes[i]>>2)<<bits;bits+=10u;
            while(bits>=8u) {out[used++]=(uint8_t)pending;pending>>=8;bits-=8u;}
        }
        if(bits)out[used++]=(uint8_t)pending;
    }
    return length;
}
