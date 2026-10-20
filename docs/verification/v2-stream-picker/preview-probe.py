import json, sys, time, threading
from pathlib import Path
from PySide6 import QtCore, QtWidgets
from motortester.v2.stream_ui import StreamDialog
from unittest.mock import patch
out=Path(__file__).resolve().parent
log=(out/'observations.jsonl').open('w',encoding='utf-8')
started=time.monotonic()
lock=threading.Lock()
def note(event, **fields):
    with lock:
        log.write(json.dumps(dict(t=round(time.monotonic()-started,3),event=event,**fields),ensure_ascii=False)+'\n');log.flush()
def state(d):
    s=d.bridge.state
    return dict(phase=s.phase,count=s.validated_samples,revision=s.revision,error=s.error,display_error=s.display_error,can_record=s.can_record,detail=str(s.bridge.session.first_failure) if s.bridge and s.bridge.session else None,max_gap=s.max_service_gap_ms)
class Probe(StreamDialog):
    def record_dialog(self):
        note('picker_before',**state(self))
        super().record_dialog()
        note('picker_returned',**state(self))
    def record_path(self,path):
        note('record_before',path=path,**state(self))
        result=super().record_path(path)
        note('record_returned',accepted=result,**state(self))
        return result
app=QtWidgets.QApplication([])
app.setStyle('Fusion')
with patch('serial.serialwin32.Serial.open',side_effect=AssertionError('COM forbidden')):
    d=Probe();d.setWindowTitle('V2-04a — проверка системного диалога');d.show();d.raw_view.setChecked(True);d.start_live()
    done=threading.Event()
    def observer():
        while not done.wait(.25):note('observer',**state(d))
    watcher=threading.Thread(target=observer,daemon=True);watcher.start()
    timer=QtCore.QTimer();timer.setInterval(500);timer.timeout.connect(lambda: note('qt_tick',**state(d)));timer.start()
    QtCore.QTimer.singleShot(180000,d.close)
    app.exec();done.set();watcher.join(1);note('closed',**state(d));log.close()
