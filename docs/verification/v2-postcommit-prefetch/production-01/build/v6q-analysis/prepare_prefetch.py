"""Strict collect-only Q overlays over preserved SI; no hardware."""
from pathlib import Path
import difflib,hashlib,json
root=Path(__file__).resolve().parents[2];base=root/'build/v6p-fw-01/patched/v2';out=Path(__file__).resolve().parent/'v2';over=root/'firmware/v2-stream/overlays';rows=[]
def once(s,a,b):
    if s.count(a)!=1:raise ValueError(('exact insertion',a[:90],s.count(a)))
    return s.replace(a,b)
def emit(rel,old,new):
    p=out/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(new.encode())
    patch=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel,n=3)).encode()
    name='v2-prefetch-'+rel.replace('/','-')+'.patch';(over/name).write_bytes(patch);sha=lambda b:hashlib.sha256(b).hexdigest()
    rows.append({'source':'patched/v2/'+rel,'target':'v2/'+rel,'patch':name,'source_sha256':sha(old.encode()),'patch_sha256':sha(patch),'result_sha256':sha(new.encode())})

rel='protocol/mt_live_device.c';old=(base/rel).read_text('utf8');s=old
s=once(s,'static int batch_prepare(mt_live_device *d,unsigned *error) {','''/* Keep view/work-copy lifetime outside completion/error callback frames.
 * Both ordinary prepare and post-flush prefetch own at most512 samples here. */
static __attribute__((noinline)) int batch_collect(mt_live_device *d,unsigned *error) {''')
s=once(s,'unsigned blocks,i,j,room,turns;','unsigned blocks,i,j,room;')
s=once(s,'''        if(d->batch.count==1024u || (d->state==MT_LIVE_DRAINING && d->queue.sealed && !d->queue.used)) {''','''    }
    return 1;
}
static int batch_prepare(mt_live_device *d,unsigned *error) {
    unsigned turns;
    if(!batch_collect(d,error))return 0;
    if(d->batch.phase==MT_BATCH1024_COLLECT) {
        if(d->batch.count==1024u || (d->state==MT_LIVE_DRAINING && d->queue.sealed && !d->queue.used)) {''')
at='mt_live_prepare_result mt_live_device_prepare_tx(mt_live_device *d,\n'
prefetch='''/* A published result certificate, not tx_ok or an empty buffer alone.
 * Inspect every old field BEFORE reusing the caller's non-aliasing ticket. */
int mt_live_device_prefetch_ready(const mt_live_device *d,const mt_live_tx_ticket *t) {
    if(!d || !t || t->result!=MT_LIVE_TX_PREPARED || t->error ||
       t->state!=MT_LIVE_STREAMING || t->mode!=5u || t->tx_mode!=5u ||
       t->tx_type!=DATA || t->tx_count!=1024u || !t->tx_offset ||
       t->tx_offset>=t->tx_length || t->tx_length<=384u || t->tx_length>1335u ||
       t->batch.phase!=MT_BATCH1024_READY || t->batch.count!=1024u ||
       t->batch.length!=t->tx_length || t->tx_first_index!=t->prefix_end ||
       UINT64_MAX-t->tx_first_index<1024u || !t->tx_sequence ||
       t->tx_sequence>=RESERVE || t->tx_exhausted)return 0;
    return d->state==MT_LIVE_STREAMING && d->mode==5u && !d->hardware_off &&
        !d->clock_failed && !d->local_error && !d->first_reason &&
        d->nonce==t->nonce && d->nonce==t->tx_nonce && d->generation==t->generation &&
        d->revision==t->revision && d->revision==t->tx_revision &&
        d->tx_mode==t->tx_mode && d->tx_nonce==t->tx_nonce &&
        d->tx_type==DATA && d->tx_sequence==t->tx_sequence && d->tx_count==1024u &&
        !d->tx_length && !d->tx_offset && d->last_write_known &&
        d->last_write_accepted==t->tx_length-t->tx_offset &&
        d->batch.phase==MT_BATCH1024_EMPTY && !d->batch.count &&
        !d->batch.length && !d->batch.offset &&
        d->prefix_end==t->tx_first_index+1024u &&
        d->prefix_crc_state==t->batch.prefix_crc && d->last_data_sequence==t->tx_sequence &&
        !d->tx_exhausted && d->tx_next && d->tx_next<RESERVE &&
        d->tx_next==t->tx_next && d->tx_next==t->tx_sequence+1u &&
        !d->want_start && !d->want_caps && !d->want_error && !d->want_end && !d->want_ack &&
        !d->stop_seen && !d->stop_budget && !d->hello_budget && !d->inherited_budget &&
        !d->queue.sealed && d->queue.used && d->queue.used<=MT_SAMPLE_QUEUE_SLOTS &&
        d->queue.head==t->queue_head && d->queue.used==t->queue_used &&
        d->queue.head_index==t->head_index && d->queue.next_index==t->next_index;
}
mt_live_prepare_result mt_live_device_prefetch_tx(mt_live_device *d,mt_live_tx_ticket *t) {
    unsigned error=MT_LIVE_ERR_NONE;
    if(!mt_live_device_prefetch_ready(d,t))return MT_LIVE_TX_EMPTY;
    /* No seal/frame-CRC/COBS/write or callback, even when collection fills up.
     * Queue pop transfers ownership; the published prefix remains unchanged. */
    (void)batch_collect(d,&error);
    ticket_capture(d,t,error?MT_LIVE_TX_ERROR:MT_LIVE_TX_EMPTY,error);
    return t->result;
}
'''
s=once(s,at,prefetch+at);emit(rel,old,s)

rel='protocol/mt_live_device.h';old=(base/rel).read_text('utf8');s=old
s=once(s,'mt_live_prepare_result mt_live_device_prepare_tx(mt_live_device *device,','''/* Only the actual completed cached full mode5 ticket may start prefetch.
 * ready is a pure scheduling/result check. prefetch_tx rechecks it and may
 * replace that same ticket ONLY AFTER eligibility, with EMPTY or deferred ERROR.
 * No output bytes/callback/prefix advance; <=512 source samples, no encoding.
 * Caller preserves transport identity before/after and guards ERROR recovery. */
int mt_live_device_prefetch_ready(const mt_live_device *device,const mt_live_tx_ticket *ticket);
mt_live_prepare_result mt_live_device_prefetch_tx(mt_live_device *device,mt_live_tx_ticket *ticket);
mt_live_prepare_result mt_live_device_prepare_tx(mt_live_device *device,''')
emit(rel,old,s)

rel='app/mt_live_runtime.c';old=(base/rel).read_text('utf8');s=old
helper='''/* Invoked only AFTER the existing flush and its final clock/loss barrier.
 * No new grant or task dispatch: an already armed tail may overlap collect.
 * The observer span includes this ownership work; it is not CPU-only time. */
static mt_live_runtime_result prefetch_after_tx(mt_live_runtime *r,mt_live_tx_ticket *ticket,
        uint32_t prepared_epoch,uint32_t prepared_soft_serial) {
    mt_usb_scope scope;uint32_t key;
    mt_live_prepare_result result;int ok;
    if(!mt_live_device_prefetch_ready(&r->device,ticket))return MT_LIVE_RUNTIME_OK;
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    if(!usable(r) || r->epoch!=prepared_epoch || r->soft_serial!=prepared_soft_serial)
        return MT_LIVE_RUNTIME_IDLE;
    if(!mt_usb_bridge_app_enter(&scope))return MT_LIVE_RUNTIME_IDLE;
    if(!stable(r)) { mt_usb_bridge_leave(&scope); (void)synchronize_loss(r); return loss_result(r); }
    if(r->epoch!=prepared_epoch || r->soft_serial!=prepared_soft_serial) {
        mt_usb_bridge_leave(&scope);return MT_LIVE_RUNTIME_IDLE;
    }
#if CFG_MT_PROGRESS_TRACE /* Q_PREFETCH_SPAN */
    uint32_t progress_prepare=mt_progress_prepare_begin();
#endif
    result=mt_live_device_prefetch_tx(&r->device,ticket);
#if CFG_MT_PROGRESS_TRACE /* Q_PREFETCH_SPAN */
    mt_progress_prepare_end(progress_prepare);
#endif
    if(live_time(r)==UINT64_MAX) { mt_usb_bridge_leave(&scope); return time_fault(r); }
    if(!stable(r) || r->epoch!=prepared_epoch || r->soft_serial!=prepared_soft_serial) {
        mt_usb_bridge_leave(&scope);(void)synchronize_loss(r);return loss_result(r);
    }
    mt_usb_bridge_leave(&scope);
    if(result!=MT_LIVE_TX_ERROR)return MT_LIVE_RUNTIME_OK;
    /* A second guarded call is allowed ONLY for this matching deferred error.
     * EMPTY/COLLECT can never enter another DATA submit in this pass. */
    key=mt_usb_bridge_lock();
    ok=prepared_tx_step(r,ticket,prepared_epoch,prepared_soft_serial);
    mt_usb_bridge_unlock(key);
    if(live_time(r)==UINT64_MAX)return time_fault(r);
    if(!synchronize_loss(r))return loss_result(r);
    return ok?MT_LIVE_RUNTIME_OK:MT_LIVE_RUNTIME_RECOVERY;
}
'''
s=once(s,'/* Scheduling hint only: the existing prepare and guarded ticket remain the\n',helper+'/* Scheduling hint only: the existing prepare and guarded ticket remain the\n')
s=once(s,'    return tx_ok ? MT_LIVE_RUNTIME_OK : MT_LIVE_RUNTIME_RECOVERY;', '''    if(tx_ok && ticket.tx_mode==5u && ticket.tx_type==152u &&
       ticket.tx_count==1024u && ticket.tx_offset && !r->device.tx_length &&
       r->device.batch.phase==MT_BATCH1024_EMPTY)
        return prefetch_after_tx(r,&ticket,prepared_epoch,prepared_soft_serial);
    return tx_ok ? MT_LIVE_RUNTIME_OK : MT_LIVE_RUNTIME_RECOVERY;''')
emit(rel,old,s)
(over/'prefetch.json').write_text(json.dumps({'schema':'motortester-v2-prefetch-overlay-1','patches':rows},indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps(rows))
