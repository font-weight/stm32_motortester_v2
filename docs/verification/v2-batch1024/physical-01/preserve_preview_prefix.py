"""Save received Preview codes from the immutable wire log; do not invent a recording start."""
from pathlib import Path
import json,hashlib,sys,zlib
r=Path.cwd();sys.path[:0]=[str(r/'host'),str(r/'host/tools')]
from verify_stream_trial import parse_traffic
from motortester.stream_wire import Kind
p=r/'build/v6l-board-01/150000';a=json.loads((p/'physical-analysis.json').read_bytes())
assert a['owners_closed'] and a['offline_validation_status']=='PASS' and a['unbound_journal'] is not None
wire=p/'run/traffic.bin'; before=hashlib.sha256(wire.read_bytes()).hexdigest()
details={};frames=parse_traffic(wire.read_bytes(),details);nonce=int(a['nonce_hex'],16)
raw=b''.join(payload.raw_samples for direction,stamp,f,payload in frames
    if direction==1 and f.nonce==nonce and f.kind==Kind.DATA)
assert len(raw)==a['received_prefix']['bytes'] and hashlib.sha256(raw).hexdigest()==a['received_prefix']['sha256']
assert zlib.crc32(raw)==a['received_prefix']['crc32']
with (p/'received-preview-prefix.u16le').open('xb') as stream:stream.write(raw)
metadata={'status':'RECEIVED_PREVIEW_PREFIX_SAVED','source':'run/traffic.bin','source_sha256':before,
    'nonce':a['nonce_hex'],'generation':a['generation'],'origin':'device','firmware_build':'0x56325345',
    'mode':5,'sample_rate_hz_nominal':150000,'encoding':'u16le_adc12_scale','retained_bits':10,'discarded_lsb':2,
    'first_sample_index':0,'end_sample_index':8192,'samples':len(raw)//2,'raw_sha256':hashlib.sha256(raw).hexdigest(),
    'recording_start_established':False,'not_a_successful_mtstream_recording':True,'produced_tail_unknown':True,
    'scope':'Derived copy of complete CRC-valid DATA received during Preview; original wire and failed-unbound journal unchanged.'}
(p/'received-preview-prefix.json').write_text(json.dumps(metadata,indent=2)+'\n',encoding='utf-8')
assert hashlib.sha256(wire.read_bytes()).hexdigest()==before
print(json.dumps(metadata))
