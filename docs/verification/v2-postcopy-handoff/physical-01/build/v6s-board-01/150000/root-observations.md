# S2: фактическая хронология root, 28.10.2026

Новый фактический ответ «готово» на call_54921eaab0c84269b90897c379be9ab0
после SL Reset сохранён в ../150000-user-replug.json. Холодный цикл обоихUSB,
PA0 empty/app closed подтверждены пользователем; их длительность/проводка
независимо не измерялись. Fresh Windows inventory18:11:10.2039213UTC:
ожидаемый COM6/code0, owners=[], USB и ST-LinkOK.

Единственный START точного плана S2: helper18:11:27.695157–18:11:28.933361UTC,
whole command1.2381999с; requested Record30с. ProbeFAIL/source_error/device_1,
ENDreason1/flags3 до hostSTOP. 21DATA1024=21504 codes, retained10/ADC12.
Nonce bdfc52fdf5a8dab9, generation3, exactSL0x5632534c/CAPS5.
ENDseq25/prefix21504/CRC1998538068; STOPreq4→ACKseq26/terminal25/sameprefix.
Record[1024,21504)=20480; host Record wall0.141745900с — не измерение Fs.
RawSHA6e6dd49ef64aa628f72a65f2ab9d1754aa42b5b03db8ea70be070b6be681be1d;
recordrawSHAd59252abd379b0d950503e65bb12a8c923341c26a7768d176b6d65991ac0fd78.
Неизвестный произведённый хвост/число потерянных отсчётов не выдумываются.
Offline wire/indices/CRC/raw/freshOpen PASS относится только к полученному
префиксу. Не меняет отрицательный physical outcome.

После cleanup_finished/phaseclosed root выполнил offline анализ END/ACK/raw.
Только затем root_read_closed.py начал read-only SWD в 2026-10-28T18:12:00.128988+00:00.
Две отдельные копии136,64,24 равны попарно, decoder accepted/errors[].
TIM3CEN0 PSC47 ARR9; ADC_CR2=0; DMAEN0; остальные stoppedchecks true.
Во время COM никакого SWD/halt не было. ADC_DR не читался. После единственного
START не было Reset/Flash/дополнительного START/50/100/автоматического rollback.
На плате оставлена SL, источник остановлен.

Legacy136: qhigh8, firstreason1, ADCfault0, maxpoll2939мкс, copymax167мкс,
copycount43, stepmax228897cycles. Maxpoll ниже3413 сам по себе не lossless proof.
N64 first-close: q8,READY1024, TX1152/1335; FIFO384, held0/deferred0/taskready0.
Elapsed10615933cycles≈147.443514мс при условных72MHz; prepare4207931/159
inclusive, positive26517B/79, zerospace45/other0; maxgap698606cycles,
lastpositive→close67486cycles. Accepted FIFO bytes не равны USB delivery.
G24: flags47, publicationserial82, RESUMED, total384/prequeued320,
evaluatedage460мкс/budget1, ACTIVE1/APPLICABLE0, eventcycle3120308730.
Event→Nclose224cycles≈3.111111мкс при тех же условных72MHz.
Это исторический переход, не причина текущего held и не одновременный64/24
снимок. Нельзя утверждать фактический вход postcopy_hint или его единственную
причину отказа по этим полям: такого счётчика/selector в записи нет.

Пары SHA256:
-136 a106ae43651f3436cc4ed785f6df7cf6fcaa4a0ad6146e27b125f72b2e54fbda
-64 c0c04191fb9f6dba4f6d2b50ef84ec6d0036e89bc357a18e8da252589c33c553
-24 bb02bf65875e0a453bb025c6811aca258b08fb6f8bee684158bab9951838323c

Все raw/неудачные результаты сохранены; дальнейший разбор только offline.
Новая гипотеза/исправление не заявлены измеренным фактом; stable150k OPEN.
