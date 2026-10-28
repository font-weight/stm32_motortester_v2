# R2 follow-up: независимый выбор следующей гипотезы

28.10.2026. Критик `/root/stream200_critic`, не автор предложения/реализации.
**PASS 9,60/10 только для ограниченного offline-выбора гипотезы.** Можно
продолжать конкретный draft S/SL: после валидированного private ADC512 дать
единственную возможность закончить cached DATA1024 и выполнить прежний Q
prefetch, затем опубликовать pending512. Готовый контракт реализации пока
**BLOCKED_EVIDENCE, score:null**: точные receipt/API/returns и disposition ошибок
ещё не определены. Этот отчёт не принимает реализацию, образ или Flash/START.

## Точные входы и проверка

[Предложение](../verification/v2-usb-gate/followup-01/analysis.md):18299байт,
SHA256 `8c8a9bac2f18de6a89845e0135fdd6d0183f0b3ccb64ebc99be86e778b7cee63`.
[Manifest](../verification/v2-usb-gate/followup-01/manifest.json):
`cf1c08744f1318a64f4ec925ac4dea0aadc6be9380c20764e5bde5cb7c4f4053`.
Единственная source/archive пара лично сверена побайтно/по размеру/SHA.
База продукта SK — `bc851d6ee7b16663db95acb32733cacff7a50f36`; HEAD при чтении —
`2c85ff5ca6ec1276d894d2c786db4e4e46944f37`.

Прочитаны обязательные V2-документы и exact SK ADC adapter, DMA driver,
runtime, core и USB bridge. Пины пяти файлов, образа и неизменного
[физического ревью R2](v2-06r-physical-review.md) — в
[JSON](../verification/v2-usb-gate/critic-followup.json).
Среда Windows/PowerShell; только чтение Get-Content/rg, Git status/revision
и пассивная Python-сверка SHA. Продуктовые тесты, сборки, decoder/Open и аппаратные
действия не повторялись; implementation не менялась.

## Почему направление обосновано

R2: queue8, READY1024, TX1152/1335, FIFO free64. Остаток183 не проходит whole-fit:
дефицит119байт. G24 PUBLISHED384/queued64/APPLICABLE0 не доказывает callsite,
TIME/FINAL cause, USB delivery или тот же эпизод позднего held64. Полученные
21504кода и их отличие от прежних опытов не доказывают улучшения устойчивости.

Код подтверждает нужную границу: mt_live_adc_service получает проверенную
private copy512 и сразу делает четыре offer128 **до** ordinary grant. Driver
уже продвинул индекс/next_half; samples находятся в private snapshot. Очередь
может отказать раньше завершения cached TX и освобождения staging. После
actual final commit, прежнего flush и Q certificate collect512 условно даёт
queue8→4, а pending offers возвращают8. Это проверяемый путь по коду, не полная
измеренная хронология R2 или обещание throughput. Grant после copy сохраняет
приоритет ADC poll, но следующий3413мкс deadline остаётся: maxpoll2907 и6/<500
не дают WCET/запаса, known0 или новый deadline fault всё ещё возможны.

## Обязательные решения S одним контрактом

1. **Pending receipt.** Определить локальный descriptor/index/count/profile,
   исходные session/epoch/soft и poll stamp, validity и одноразовую disposition
   на каждом выходе. Driver уже продвинул индекс: нельзя забыть512 через IDLE.
   Второй read_block/reinit до disposition запрещён. Указать исходы после0–3
   успешных offers, без повторного push или скрытого пропуска остатка.
2. **Отмена против инвалидации.** Здоровая отмена fastpath — pending RX,
   scope refusal, no-IN/known0 — ведёт к прежним offers либо честному queue-full.
   TIME/epoch/driver/lifecycle loss, recovery или уже выполненный Stop/HELLO —
   к конкретному old-session fail-closed/first-close-before-cleanup. Запретить
   clean normal END/ACK с пропущенным диапазоном и данные старого block в новой
   nonce. Текущий prefetch_after_tx IDLE нельзя непосредственно превратить в skip512.
3. **RX/scope.** Не dispatch/consume RX между acquire и disposition; свежие
   проверки асинхронного OUT/SETUP/lifecycle сохраняются. Nested same-actor
   app scopes разрешены actual scope.previous: отдельные locals и LIFO restore
   достаточны, обязательный leave/reenter не нужен. Не применять receipt после
   synchronize_loss/cleanup лишь потому, что его bytes ещё читаются.
4. **Один grant/TX и реальный commit.** Actual ticket, mode5/STREAMING,
   cached DATA1024 READY, offset>0, remaining1..384, queue free<4, без control/
   Stop/budget/RESERVE. Зафиксировать attempt markers при refusal/known0/stale/
   ERROR. Сохранить old guarded final-TIME constant commit, flush и Q certificate;
   без нового encode/task/spin/второго DATA или grant. Matching Q ERROR recovery
   не является вторым DATA submit. Accepted bytes/prefix и popped ownership не откатывать.
5. **Deadline.** Точный API задаёт clock validity, modulo elapsed и existing
   fault на3413, до publication и при отказе после частичных offers. Срок — от
   исходного read_block stamp; last_poll_us не освежать. Прежние DMA flags/
   copy/ownership guards не ослаблять. Private snapshot не защищает следующую
   DMA half и не гарантирует, что следующий pass уложится.
6. **Ресурс/старые пути.** Ноль новых static bytes, прежние buffers/wire/Fs/
   6/<500 и uncached/control/EMPTY/50/100 пути. Сейчас4 static bytes вне
   stack reserve8192; новый локальный receipt/вложенные вызовы требуют exact
   ARM stack/map. Observer exact binding/freeze остаются действующими.

Это требования к следующему интерфейсу, не дефекты ещё не написанного S-кода.
Новый profiler или дополнительный общий этап выбора гипотезы не требуется.
Неблокирующая точность: текущий stop_snapshot пишет tail в b->stop_scratch,
а quiesce/invalidate_history сами не перезаписывают driver.snapshot.
Причина запрета offers после recovery — потеря session/history/ownership,
даже если bytes целы; обычный overwrite — следующий read_block либо reinit.
Уточнить это в S, историческое предложение не переписывать.

## Минимальные следующие свидетельства

Один actual-C runner новых adapter/runtime boundaries с actual core/queue/
serializer: (1) final commit→flush→Q→offers, индексы/коды, queue8→4→8 и одна
попытка; (2) no-IN/known0, partial/unknown/late-final-TIME/Q ERROR и отказ
промежуточного offer; (3) pending RX/scope denial/stale identity/lifecycle и
deadline boundary, различающие healthy fallback и invalid block. Новую
adapter/runtime границу не заменять целиком stub. USB/DMA timing seams раскрыть;
native не доказывает аппаратный темп. Дополнительно source-preservation старых
driver/DCD/MMIO/completion/Stop guards и один ARM/resource audit, без широких
legacy/GUI suites. Аппаратная приёмка потребует отдельного exact плана и всего
запрошенного непрерывного интервала без faults/gaps.

| Критерий | Вес | Балл | Основание только выбора гипотезы |
|---|---:|---:|---|
| C1 | 0,30 | 9,7 | Source-supported handoff, Fs/wire и пределы вывода сохранены |
| C2 | 0,20 | 9,5 | Pending512/Stop/identity/deadline риски явно ограничены |
| C3 | 0,25 | 9,6 | Пригодный R2 и exact source, без causal/throughput overclaim |
| C4 | 0,15 | 9,4 | Одна перестановка; конкретный интерфейс ещё требуется |
| C5 | 0,10 | 9,8 | Frozen pins и минимальные следующие свидетельства |

Итог `2,91+1,90+2,40+1,41+0,98=9,60`: **PASS выбора гипотезы**.
Implementation-контракт — **BLOCKED_EVIDENCE/null** до решений1–6.
**P1-M2-01 OPEN**, физический R2 **REWORK6,375** и остановленная SK неизменны.
