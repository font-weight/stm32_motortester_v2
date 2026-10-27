"""Produce one strict O runtime overlay over preserved SG; never access hardware."""
from pathlib import Path
import difflib, hashlib, json

root=Path(__file__).resolve().parents[2]
base=root/'build/v6n-fw-01/patched/v2/app/mt_live_runtime.c'
original=base.read_bytes().decode('utf8')
s=original
def once(old,new):
    global s
    if s.count(old)!=1:raise ValueError(('exact insertion',old[:100],s.count(old)))
    s=s.replace(old,new)

helpers='''/* Scheduling hint only: the existing prepare and guarded ticket remain the
 * authority. Delay no cached/collect-only/control or modes1..4 opportunity.
 * Streaming queue blocks have128 samples; malformed metadata cannot grant TX. */
static int defer_data_grant(const mt_live_runtime *r) {
    const mt_live_device *d=&r->device;
    unsigned count=d->batch.count,blocks=(unsigned)d->queue.used;
    if(d->mode!=5u || d->state!=MT_LIVE_STREAMING || d->tx_length ||
       d->want_start || d->want_caps || d->want_error || d->want_end || d->want_ack ||
       d->stop_seen || d->queue.sealed || d->queue.used>MT_SAMPLE_QUEUE_SLOTS ||
       count>1024u || (count&127u))return 0;
    if(d->batch.phase==MT_BATCH1024_EMPTY) {
        if(count)return 0;
    } else if(d->batch.phase!=MT_BATCH1024_COLLECT)return 0;
    if(blocks>4u)blocks=4u;
    return count+128u*blocks>=1024u;
}
static int new_data_ticket(const mt_live_tx_ticket *t) {
    return t->result==MT_LIVE_TX_PREPARED && !t->error &&
        t->state==MT_LIVE_STREAMING && t->mode==5u && t->tx_mode==5u &&
        t->tx_type==152u && !t->tx_offset && t->tx_count==1024u &&
        t->batch.phase==MT_BATCH1024_READY && t->batch.count==t->tx_count &&
        t->batch.length==t->tx_length && t->tx_length && t->tx_length<=1335u;
}
'''
once('static mt_live_runtime_result step(mt_live_runtime *r,unsigned *grant_attempted) {',helpers+'static mt_live_runtime_result step(mt_live_runtime *r,unsigned *grant_attempted) {')
once('    mt_live_tx_ticket ticket;','    mt_live_tx_ticket ticket; unsigned deferred_grant;')
once('    *grant_attempted=1u; grant_irq(r);','''    deferred_grant=(unsigned)defer_data_grant(r);
    if(!deferred_grant) { *grant_attempted=1u; grant_irq(r); }''')
once('    MT_DIAG_STAMP(diag_tx);','''    if(deferred_grant) {
        /* Consume this opportunity even if its fresh admission is refused.
         * A failed app scope must not cause a second ordinary wrapper grant.
         * The next runtime pass retains the normal early-return fallback. */
        *grant_attempted=1u;
        if(live_time(r)==UINT64_MAX)return time_fault(r);
        if(!synchronize_loss(r))return loss_result(r);
        if(!usable(r))return MT_LIVE_RUNTIME_IDLE;
        if(!mt_usb_bridge_app_enter(&scope))return MT_LIVE_RUNTIME_IDLE;
        if(!stable(r)) { mt_usb_bridge_leave(&scope); (void)synchronize_loss(r); return loss_result(r); }
        grant_irq(r);
        /* New IRQ boundary: restore the actor on every failure, then the old
         * guarded submit revalidates the pre-prepare epoch and full ticket. */
        if(live_time(r)==UINT64_MAX) { mt_usb_bridge_leave(&scope); return time_fault(r); }
        if(!stable(r)) { mt_usb_bridge_leave(&scope); (void)synchronize_loss(r); return loss_result(r); }
        mt_usb_bridge_leave(&scope);
        /* Stop/HELLO may cancel the hint during RX. Preserve any newly staged
         * DATA bytes and send them via the ordinary cached path next pass;
         * EMPTY/control/deferred errors retain the original guarded handling. */
        if(ticket.result==MT_LIVE_TX_PREPARED && ticket.tx_type==152u &&
           !new_data_ticket(&ticket))return MT_LIVE_RUNTIME_IDLE;
    }
    MT_DIAG_STAMP(diag_tx);''')
out=root/'build/v6o-analysis/mt_live_runtime.c'
out.write_bytes(s.encode())
patch=''.join(difflib.unified_diff(original.splitlines(True),s.splitlines(True),fromfile='a/app/mt_live_runtime.c',tofile='b/app/mt_live_runtime.c',n=3)).encode()
over=root/'firmware/v2-stream/overlays'
name='v2-late-grant-app-mt_live_runtime.c.patch'
(over/name).write_bytes(patch)
sha=lambda b:hashlib.sha256(b).hexdigest()
manifest={'schema':'motortester-v2-late-grant-overlay-1','patches':[{'source':'patched/v2/app/mt_live_runtime.c','target':'v2/app/mt_live_runtime.c','patch':name,'source_sha256':sha(original.encode()),'patch_sha256':sha(patch),'result_sha256':sha(s.encode())}]}
(over/'late-grant.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8',newline='\n')
print(json.dumps({'prepared_runtime':str(out),'sha256':sha(s.encode()),'manifest':manifest}))
