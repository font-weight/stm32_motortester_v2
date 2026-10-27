# V2-06q2 — независимый итог единственного опыта SJ

27.10.2026. **Физическая устойчивость150k: REWORK, 6,375/10.** Запрошенные30с не достигнуты: источник сообщил queue-full. **Диагностический результат отдельно: PASS, 9,60/10**, только для сохранённого идентифицированного first-close снимка и подтверждённой остановки. Диагностический балл не входит в физический и не закрывает **P1-M2-01**.

Критик `/root/stream200_critic` не автор реализации, декодера или аппаратный оператор. Выполнено только пассивное чтение свидетельств; тесты, decoder/анализатор, Flash/Reset/COM/SWD повторно не запускались.

## Точное состояние и хронология

- Source SJ: `b8d72a76f623a53cea5f3fa308965ea48f852799`; образ45372байта, SHA256 `5041ae67ccc25eda8d0003121370baed1120b025399099d4c3f42abfee61ca88`, build `0x5632534A`.
- [План](../verification/v2-postcommit-prefetch/plan-01/build/v6q-board-01/plan.json) SHA256 `5089104d2a4fb524bfa044f3c66ae7c92069ab0c3bb8745abd6d61394ca848b4`; прежний [допуск9,60](v2-06q-flash-review.md) был процедурным, не обещанием успеха.
- [Physical archive](../verification/v2-postcommit-prefetch/physical-01/manifest.json), SHA256 `ced3b2e6bae7c310404b1c6eea5ee8b9d4cf227f910383046ac2195c1e282013`:91 source/archive пара,318520байт. Все пары/размеры/хеши лично сверены, дрейфа нет.

Один program27.10 в13:58:05UTC, независимый полный readback и один программный Reset/Run13:58:09 завершились успешно. Критик лично сравнил readback с exact BIN побайтно.

Первое переподключение не восстановило COM: сохранён Windows descriptor/Code43 failure. Этот **pre-START отказ подключения** не является опытом потока: COM не открывался, START0. В17:37:33 root дополнительно прочитал HOTPLUG16байт boot flags по `0x200005BC`, без Flash/Reset/halt. Сохранённые слова `(1,1,1,0)` соответствуют IDLE, USB-init1, IRQ-admitted1, boot-failure0; они не доказывают исправность USB enumeration. Это отдельное предварительное чтение, не скрытое чтение во время захвата.

После нового фактического ответа пользователя `готово`, question `call_4b8193763305491d828e00c738f45b1d`, выполнено подтверждённое пользователем полное снятие питания USB платы и ST-Link, затем включение платы первой и ST-Link через5с. Запись ответа17:39:08.843UTC привязана к прежнему reset.log SHA256 `0bdf3581b5ad76c8ea2f518f0c4c702adff2fbf2ce77b5774ec19019a652aebe`. Новый inventory показывает COM6/ожидаемый PNP/code0, владельцев нет. Причина первого сбоя подключения не установлена и не объявляется исправленной прошивкой.

**Единственный START** относится к trial17:39:09.282207–17:39:10.369009UTC, whole command1,0868004с. После результата повторных START, программных Reset/Flash или rollback нет; SJ оставлена остановленной.50/100k не входили в план и не выполнялись. Пользовательские физические power cycles до START отделены от единственного CLI Reset.

## Поток и сохранение данных

[Probe result](../verification/v2-postcommit-prefetch/physical-01/build/v6q-board-01/150000/run/result.json) — **FAIL/source_error device_1**. Record wall0,099517с — наблюдённый host interval, не измеренная частота АЦП. `cleanup_finished=true`, конечная phase=`closed`.

Discovery nonce `1b14a4eea92919b1`; выбранный nonce `71d28b8a72c1f51a`, generation3. Wire observed SJ, CAPS mode5/150000/1024/retained10, ADC12 с отбрасыванием двух младших бит. Получено18 полных DATA1024, всего18432 канонических кода; largest DATA1335байт с delimiter. Сохранённый полный префикс непрерывен, SHA256 `dc118cf1d9e01800429df6f4908c03233e9c256ee486cd7453afb6c8c34097e3`, CRC32 `3873357665`.

ENDseq22/reason1/flags3/prefix18432 пришёл **до** host STOPreq4; matching STOP_ACKseq23 с terminal22 и тем же prefix. Это подтверждённый обмен после аварийного завершения, **не normal Stop**. `produced_end=null`, количество неполученных отсчётов неизвестно.

[Offline analysis](../verification/v2-postcommit-prefetch/physical-01/build/v6q-board-01/150000/physical-analysis.json), SHA256 `d235ac9bbf545dcc2c02c1b5ec4b937225662b2cd62705ec8c92e3c07b9c0937`, имеет PASS/issues[] **только для сохранённых данных**. Record `[4096,18432)` содержит14336 кодов, wire-selected и fresh-open journal совпадают побайтно, SHA256 `0c3de6ba747306b4efc5c7d90ca64d92551896a48ebe14298ab77bfd549d67d6`. Companion проверен, discarded tail0/recovery null. Критик прочитал результат существующего verifier и сверил сохранённые before/after hashes; raw/Open/CRC вычисления заново не запускал. Успешное сохранение префикса не превращает короткий FAIL в устойчивый поток и не устанавливает нулевые потери АЦП.

## Диагностика и остановка

Первое послеопытное SWD-чтение началось17:39:41.205UTC, после закрытого probe и offline END/ACK. Saved root procedure facts подтверждают отсутствие SWD/halt при активном COM и ADC_DR reads. Это внешнее процедурное свидетельство вместе с invocation timestamps, а не вывод одного поля декодера. Подготовительное чтение boot flags до START отдельно указано выше.

Legacy136 pair SHA256 `62494d534800af5dd54e52e8b89055bc0603c7dd33f6d92a03d88cc3bbbe62a2`: обе копии равны; SJ/nonce/gen совпадают с wire/readback. Phase frozen, flags4, first acquisition reason1, queue8/8, ADCfault0, observed maxpoll2952мкс, copy184мкс. Эти максимумы меньше3413мкс, но не доказывают достаточный темп разгрузки очереди, WCET или отсутствие потерь.

Progress64 pair SHA256 `a2b33237f8b7458fde2dd8a2fc5e06fd9fb4653c28a72815712a75690d429419`: обе копии равны; [decoded record](../verification/v2-postcommit-prefetch/physical-01/build/v6q-board-01/150000/progress-decoded.json) **VALID_WITH_LIMITS**, errors[]/warnings[]. Критик лично распаковал64/136 и сравнил все поля с сохранёнными JSON. Exact image→wire→136→64 identity согласована; hardcoded-ID дефект старой SH здесь не повторился.

- First close queue/primary1; elapsed9 119 434циклов, условно126,658806мс при72МГц.
- Completed prepare3 483 366циклов/145spans, условно48,380083мс; включает ordinary и Q collect-only, IRQ и observer. Это не CPU share и не длительность145 полных encode.
- DATA FIFO acceptance22512байт/67positive callbacks, zero-space47, zero-other0. Max no-positive gap700232цикла, условно9,725444мс; tail через close29403цикла.
- В первом снимке queue8, staging READY/count1024, tx offset1152/length1335, FIFO free64, held/deferred=true, task-ready=false. Эти поля не разделяют причины удержания USB и не устанавливают единственную причину отказа.

FIFOaccepted не равно полным DATA, wire-delivery или committed sample prefix **до первого отказа**: окончательные18432 включают последующий drain.18пакетов SJ против12 SI не являются контролируемым доказательством эффекта prefetch. Условные DWT интервалы согласуются с коротким захватом и заявленным отсутствием halt, но не являются калибровкой времени.

Критик отдельно прочитал сохранённые register bytes: TIM3_CEN0/PSC47/ARR9, ADC_CR2=0/SMPR2 lowbits4, DMA_EN0, необходимые clocks/reset bits согласованы. [Stopped registers](../verification/v2-postcommit-prefetch/physical-01/build/v6q-board-01/150000/registers-decoded.json) all_checks=true. Это подтверждение остановленного состояния после closedowner, не полноценная проверка аналогового входа.

## Замечание, оценки и границы

**P1-M2-01 остаётся OPEN:** точный SJ не выполнил требование30с устойчивого150k; queue-full наступил после18432 полученных кодов. Исправность хранения/Stop/диагностики и Q1 software PASS не снимают это нарушение. Старые неудачные опыты не переименованы; исходные source/plan отзывы не переписаны.

| Область | C1,30% | C2,20% | C3,25% | C4,15% | C5,10% | Итог |
|---|---:|---:|---:|---:|---:|---:|
| Физическая цель150k30с |3,0|4,0|9,5|9,0|9,5|**6,375 — REWORK**|
| Достоверность диагностического результата |9,7|9,5|9,6|9,5|9,65|**9,60 — PASS**|

Физические C1/C2 снижены из-за недостигнутого основного результата и переполнения; C3–C5 отражают сохранённые точные доказательства, ясную маркировку отказа и воспроизводимость. Диагностические C1/C2 основаны на exact paired identity/freeze и явных unknown/first-fault границах; C3–C5 — на сохранённых bytes/chronology/decoder limits. Диагностический PASS означает пригодность конкретного снимка для последующего offline-разбора, не приёмку прошивки по устойчивости.

Аппаратный план Q2 исчерпан. **SJ остаётся остановленной; этот отчёт не разрешает новый опыт, доработку или повтор.** Аналоговая точность, сигнал зажигания, автомобиль и калиброванная Fs не проверялись.
