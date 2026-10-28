# V2-06s / S2 — независимый физический результат SL

28.10.2026. **REWORK — 6,375/10 для устойчивых150k.** Единственный опыт
завершился queue-full задолго до30с; **P1-M2-01 остаётся OPEN**. Отдельно:
сохранность полученного префикса, остановка и пригодная ограниченная
диагностика — **PASS9,60**. Это не причинное объяснение или приёмка скорости.
Критик `stream200_critic` не автор реализации и не аппаратный оператор.

## Привязка и личная проверка

Source `695efd95e7c4ba72bfa6fb5fb511b85186be6266`, SL/0x5632534c,
BIN49532 SHA `f82311cde2ce0a3e735543006b2bc7890e8761434c73e7adc7fa332f86cb8cb2`.
Принятый [план S2](v2-06s-flash-review.md) SHA
`477b133fe1a2e7924e7414f2a7a9b38f469b70ebdee19650b0193df7a616bf0e`.
[Физический архив](../verification/v2-postcopy-handoff/physical-01/manifest.json)
SHA `aa0838b9243f22d7ef1d1f77800b7ff943e14c88b7569bae0bc84caa24f1a212`.

Пассивно прочитаны исходный FAIL, offline-analysis, журнал/companion metadata,
decoder outputs, program/readback/reset и SWD argv/logs, операторская хронология.
Лично сверены все **95 пар /420939 байт** source/archive/size/SHA, полный
readback49532 с принятой BIN, пары136/64/24 и пять before/after hashes
исходного offline-анализа. Несовпадений нет. Декодеры, CRC/codec, freshOpen,
тесты и аппаратура критиком повторно не запускались; их сохранённые результаты
проверены вместе с исходными байтами и pins. S1/source и план не переоцениваются.

## Фактический исход

После отдельного SL Reset получен новый пользовательский ответ на
`call_54921eaab0c84269b90897c379be9ab0`; он связан с hash reset.log.
Fresh inventory18:11:10UTC: ожидаемый COM6/code0, owners=[]. По сохранённым
argv/logs и root chronology выполнены один Flash/readback/Reset до ответа
и один START после него. Wrapper trial18:11:27.695157–18:11:28.933361UTC;
это границы команды, не точные аппаратные моменты START/ADC.

Probe **FAIL/device_1**. Nonce `bdfc52fdf5a8dab9`, generation3, exactSL/CAPS
mode5/150000/retained10/DATA1024. Получено21DATA =21504 кодов; ENDseq25,
reason1/flags3/prefix21504/CRC1998538068 пришёл **до** STOPreq4. ACKseq26
подтверждает terminal25 и тот же prefix. Это согласованный отказ с cleanup,
а не нормальное завершение записи. `cleanup_finished=true`, final phase closed.

Сохранённый offline результат — PASS только для непрерывного полученного
префикса: raw SHA `6e6dd49ef64aa628f72a65f2ab9d1754aa42b5b03db8ea70be070b6be681be1d`.
Record[1024,21504) содержит20480 кодов; freshOpen/companion и wire byte-equality
подтверждены, selected raw SHA
`d59252abd379b0d950503e65bb12a8c923341c26a7768d176b6d65991ac0fd78`.
Journal не скрывает `source_failure`, recovery/null и discarded tail0 относятся
к сохранённому файлу. `produced_end` и число потерянных отсчётов неизвестны.
Host Record wall0,141745900с и короткая slope не квалифицируют устойчивость/Fs.
Переданы10MSB, canonical u16 сохраняет их с left-shift2, не восстанавливая2LSB.

## Диагностика и процедура

Первое чтение SWD началось18:12:00.128988UTC после closed owner и offline
END/ACK. Пары одинаковы, decoder accepted/errors[]:

| Запись | SHA-256 | Существенные поля |
|---|---|---|
| 136 | `a106ae43651f3436cc4ed785f6df7cf6fcaa4a0ad6146e27b125f72b2e54fbda` | SL/nonce/gen3, flags4, qhigh8, firstreason1, ADCfault0, poll2939мкс, copy167мкс |
| 64 | `c0c04191fb9f6dba4f6d2b50ef84ec6d0036e89bc357a18e8da252589c33c553` | q8, READY1024, TX1152/1335, FIFO free384, held/deferred/taskready=false |
| 24 | `bb02bf65875e0a453bb025c6811aca258b08fb6f8bee684158bab9951838323c` | historical RESUMED, serial82, total384/prequeued320, evaluated age460мкс/budget1, ACTIVE1/APPLICABLE0 |

N elapsed10615933cycles, prepare4207931/159 inclusive, positive26517B/79,
zero-space45/other0. Gate event предшествует N close на224cycles. Номинальные
147,4435мс и3,1111мкс условны на72MHz/непрерывном DWT/<wrap; это не CPU share,
калиброванное время или WCET. FIFO acceptance не равно USB delivery.
Gate24 — историческое событие, поздний64 не доказывает тот же эпизод.
**Эти поля не показывают, был ли выбран postcopy_hint, и не устанавливают
единственную причину queue-full.** Poll2939<3413 также не доказывает lossless.

Saved stopped checks все true: TIM3 CEN0/PSC47/ARR9, ADC_CR2=0, DMA EN0,
clocks/reset согласованы. ADC read охватывает0x40012408..0x40012413, безDR.
Root отдельно зафиксировал отсутствие SWD/halt при активном COM, отсутствие
повторных START/Reset/Flash/rollback после опыта; SL оставлена остановленной.
Эта процедурная часть основана на журналах и прямых наблюдениях оператора,
не на доказательстве из одного decoder. Длительность физического cold-cycle
и проводка подтверждены пользователем, независимо не измерены. Поле
`image_verified=false` в probe не маскируется: связь image закрывается отдельным
readback и хронологией, а не самим wire build-id.

## Оценка по quality gate

Открыто одно существенное замечание: **P1-M2-01 — требуемые30с150k не
получены, очередь8/8 переполнилась; принятие физической устойчивости запрещено.**
Нового нарушения сохранности полученных данных или процедуры в архиве не найдено.

| Критерий | Балл | Основание |
|---|---:|---|
| C1,30% | 3,0 | Главный физический критерий30с не выполнен. |
| C2,20% | 4,0 | Переполнение сохраняется; явный отказ и сохранение префикса работают. |
| C3,25% | 9,5 | Точные отрицательные свидетельства и допустимая диагностика без ложного PASS. |
| C4,15% | 9,0 | Разделены отказ, сохранность и причинная неопределённость. |
| C5,10% | 9,5 | Exact identity, хронология и исходный отказ сохранены. |

Итог `0.30*3 + 0.20*4 + 0.25*9.5 + 0.15*9 + 0.10*9.5 = 6.375`, **REWORK**.
Отдельная оценка faithful evidence/limited diagnostics: C1=9,7; C2=9,5;
C3=9,6; C4=9,4; C5=9,8, итог9,60/PASS. Она не заменяет основной verdict,
не закрывает P1 и не разрешает следующий START. 50/100 не выполнялись по плану.
