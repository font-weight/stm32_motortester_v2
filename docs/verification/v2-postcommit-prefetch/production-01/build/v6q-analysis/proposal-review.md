# Q — предварительное независимое чтение collect-only после commit/flush

27.10.2026. Критик `/root/stream200_critic`, не автор реализации. Вывод: **концептуального блокера для ограниченного черновика не найдено**. Это предварительные обязательства к реализации, не source/ARM/physical PASS и не допуск Flash. Балл до exact реализации и свидетельств не выставляется.

Прочитано frozen предложение `build/v6p-followup/analysis.md`, SHA256 `7e0944370b9b99de8b34002ef5a1adf7ffcb8f0e70bb55ac735fd58dfb15f4de`, и exact SI:

- core `mt_live_device.c`: `ebd2826022fa3b538c7f59a31711c19370433056bdcf6b5f406f216de62da5e7`;
- runtime: `31db9f366c635082cb80540e5f0028323c779a132e1fbf5e5aece8519be4f55d`;
- queue: `7ada308d948457cc5e57d53c79feec7cfa400203da98bb74fb8dff103cfe9896`;
- production serializer: `d0d19b559fdf7558827d0eda1c2de33dbfc04dab9bfa0235b6b3a237ff4f37f7`.

Факт P2 — queue-full при EMPTY staging/tx0 и q8. Код подтверждает: после успешного final-time commit старого mode5 DATA runtime делает прежний flush, затем возвращается; следующий ADC service стоит раньше обычного collect. Это обосновывает место следующего ограниченного изменения. Снимок не сообщает occupancy на предыдущем completion и не доказывает, что prefetch предотвратил бы отказ. P1-M2-01 и исторический P2 REWORK сохраняются.

## Один собранный список существенных условий

1. **Eligibility — сертификат опубликованного completion, не успешный return.** `prepared_tx_step` может вернуть1 без write при stale epoch/ticket. Helper должен проверить actual старый PREPARED/DATA/mode5/READY1024 ticket с offset>0, совпавшие nonce/generation/revision и metadata, затем ожидаемое post-final состояние: STREAMING, EMPTY/tx0, end без overflow ровно old_first+1024, last_data_sequence и prefixCRC именно старого batch. Сохранить sequence-next/exhaustion/RESERVE и отсутствие новых control/Stop/HELLO/budget/error intents. Проверять это **до** переиспользования ticket и ownership stores. Не объявлять старый full-frame принятым до последнего TIME guard и не перезаписывать текущий COLLECT по повторному или stale вызову.

2. **Новая ownership-граница требует той же identity до и после.** Сохранить все существующие flush/TIME/loss проверки; flush return/наличие FIFO bytes не означает, что IN уже запущен. Перед helper — fresh TIME, synchronize_loss, stable/usable, текущий app scope; epoch/soft serial сверять с сохранённой identity этого прохода. Collect выполняется вне PRIMASK, ISR может инвалидировать transport. После copy/pop — fresh TIME/epoch/lifecycle и scope leave на каждом выходе. Потеря identity ведёт в прежний cleanup, без восстановления popped slots и без DATA новой сессии из старого staging. Если collect вернул ERROR, нужен заново captured **текущий** matching error ticket и прежняя guarded recovery; второй guarded вызов допускается только ради этой ошибки, никогда ради отправки COLLECT/EMPTY. Старый уже принятый prefix нельзя откатывать. Устаревшая ошибка не должна recover новую identity. First-close диагностика предшествует cleanup.

3. **Общий collect-only helper не должен изменить обычный prepare/drain.** Он проверяет views/индексы/counts/canonical codes, использует локальный work-copy и прежний atomic pop_many; до успешного pop не публикует новый owned count/CRC. Speculative packed bytes не являются accepted prefix; retry/shared-byte контракт сохраняется. Prefetch допускает только максимум4×128/512, не seal/frameCRC/COBS/write/callback, не advance global prefix/sequence. На queue0 — безопасный SKIP без создания пустого нового обязательства. Stop после успешного prefetch обязан сохранить owned-but-unpublished диапазон и выдать правильный short tail/END; replacement HELLO при offset0 обязан его отбросить по прежним правилам. Modes1–4 и обычные mode5 prepare/terminal paths должны сохранить прежний результат.

Все три условия уже заданы предложением по смыслу; это точки проверки actual patch, не требование расширять дизайн. Последний cached проход действительно имеет нулевой обычный collect, поэтому дополнительный collect512 не превышает прежний sample-count budget на проход. Но это **не WCET-доказательство**: packing и1024 canonical CRC-byte updates увеличат время до следующего ADC service, могут задержать task и встретить уже устаревший grant. Deadline3413мкс,6/<500мкс grant, FIFO384, queue8 и wire не расширять. Новых persistent buffers/state не добавлять; точный ARM должен сохранить0 static growth и проверить stack с work-copy/views/ticket. Остаток28байт не считать свободой увеличивать память.

## Минимальное необходимое свидетельство следующего узла

Одна адресная executable-модель с actual core/collect и извлечённой actual runtime границей, разделённая на компактные группы, достаточна:

- Настоящий cached final write → последний TIME → publish → прежний flush → prefetch: queue8→4, owned COLLECT512, глобальные prefix/CRC/sequence не продвигаются вторично; четыре contiguous offer принимаются. Ring wrap,0/1/4 доступных блока, byte/CRC identity после обычного завершения batch; malformed/stale view не делает частичного pop.
- Отсутствие prefetch при zero/непоследнем partial/unknown, final-time failure, stale completion/ticket, control/Stop/HELLO, RESERVE/exhaustion и modes1–4. Actual deferred ERROR через guard, без дополнительного DATA/write; scope отказы и сохранение одного grant на проход.
- Epoch/soft/TIME до или во время нового copy и после него: прежний cleanup, scope восстановлен, нет stale DATA/recovery новой сессии; Stop и HELLO после успешного prefetch обрабатывают новый owned диапазон правильно. Actual observer остаётся включён для SJ, span включает prefetch и late epilogues не меняют FROZEN.

В том же executable использовать exact generated SJ header для actual observer и synthetic legacy136 setup; явно подтвердить ACTIVE и ненулевые prepare counts, чтобы выключенный binding не дал тихий PASS модели. Полный P suite повторять не требуется.

Модельные USB/clock/IRQ seams обозначить явно: это порядок и ownership, не измерение USB/ADC latency. Один exact ARM/resource/source-equivalence анализ; незатронутые driver/DCD/TIME/wire не гонять заново широким набором. Исходный functional diff, generated SJ identity обоих потребителей и новые stack edges должны войти в final source review. Никаких новых полей телеметрии/тестов ради количества не требуется.

Критик прочитал и хешировал только существующие файлы. Production, тесты, сборки, COM/SWD/Reset/Flash/START не выполнял и не изменял. Дальнейший черновик разрешает root; принятие exact реализации и аппаратный план — отдельные узлы.
