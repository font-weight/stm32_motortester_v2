# V2-06s: независимая приёмка контракта post-copy handoff

28.10.2026. Критик `/root/stream200_critic`, не автор контракта или реализации.
**PASS 9,60/10 — только готовность точного документального контракта S/SL
к ограниченной реализации.** Реализация, ARM-образ, ресурсы новой сборки и
аппаратный результат этим отчётом не приняты. P1-M2-01 stable150k остаётся OPEN;
отрицательный R2 и его диагностическая оценка не меняются.

## Проверенное состояние

[Канонический контракт](../streaming-postcopy-handoff.md):32164байта,
SHA256 `521e91d88b8234be6f8db7cbecfd79b6f4bd4c47dbb38dd871242a0d97b1b149`.
[Design manifest](../verification/v2-postcopy-handoff/design-01/manifest.json):
`c128fb7cdf88d6504fe640aa6157b5c8d9ad655851a3cdf165adeaf6f4ecabd2`.
Лично подтверждены размер/SHA и побайтное равенство source/archive. Первые31043
байта канонического файла равны frozen author draft
`e4752a6c35f8cf101ab7e5937d29a06f74857f52fe27feebd0a9ad8992cf0be2`;
единственное дополнение root — §8,1121байт явной offline-идентификации SL.

База продукта — SK/source `bc851d6ee7b16663db95acb32733cacff7a50f36`,
`build/v6r-fw-02`; HEAD чтения — `6510fb93dc1c0bf0a422f48019a1642cfe107f0e`.
Проверены шесть обязанностей [предыдущего review](v2-06r-followup-review.md),
actual adapter/read_block, core prepare/step/prefetch, runtime loss/guard/flush
и bridge scope. Дополнительно прочитан actual `mt_timebase_snapshot`: он делает
новое полное update и требует разных output pointers us/ms. Работа пассивная:
PowerShell Get-Content/rg, Git revision, Python сравнение bytes/SHA. Ни тестов,
сборок, моделей/decoder, COM/SWD, ни implementation edits критик не выполнял.

## Закрытие обязательств R-followup

| Обязанность | Решение точного S-контракта |
|---|---|
| Однократная судьба acquired512 | Stack-only receipt; acquire не offer, publish_next не более128; максимум4 вызова, published учитывает реальные queue acceptance; terminal disposition до выхода/следующего read |
| Healthy cancellation и потеря identity различны | Healthy cancel ведёт к исходным offers; STALE/raw lifecycle к explicit pending=2 hard quarantine. IDLE helper не теряет512; source CLOCK3/DEADLINE2 отделены от TRANSPORT |
| RX и scopes | No RX dispatch/read до disposition; separate nested same-actor scopes/LIFO; raw lifecycle при неизменном epoch не принимается за успешный synchronize_loss |
| Единственная попытка и irreversible commit | Actual cached ticket; handoff_consumed/grant_attempted до fallible barriers, не сбрасываются; old final-TIME commit/flush/Q certificate; после consumed только разрешённый RX и конец pass, даже если write не вызывался |
| Исходный deadline | Saved read_block-origin, fresh pre/post us и transport checks; delta3413 отклоняется, last_poll_us не освежается; уже принятые chunks не повторяются/не откатываются |
| Ресурсы и старые пути | Static0, receipt96B пока расчёт; reserve8192 и exact ARM bound обязательны; original service/driver/DCD/bridge/queue/serializer/TIME и ordinary paths сохраняются |

Новая гранулярность публикации не объявлена атомарным запретом любых ISR между
admission и queue store. §3 честно ограничивает гарантию наблюдением loss:
внутренние old-session stores могут успеть, но post-check карантинирует их до
следующей команды/TX/normal END. Последний post-check нужен и после четвёртого
offer/PUBLISHED. Это осуществимо с прежним single foreground owner без большой
новой PRIMASK вокруг now/offer/quiesce. Проверка pure cached prepare также
осуществима: actual build_tx при ненулевом tx_length возвращает cached frame,
а completion certificate проверяет состоявшийся commit, не одно tx_ok.

§5 устраняет конкретную старую ловушку: raw lifecycle может сделать stable=false
при прежнем epoch, тогда старый synchronize_loss сам не обязан выполнить cleanup.
S явно устанавливает pending=2 и использует existing hard-loss процедуру, не
подделывая epoch/soft receipt. Phase/identity не дают продолжить publication после
cleanup. Нормальные Stop/HELLO bytes лишь ждут disposition; исполнение команды
между acquire/publish запрещено. Уже escaped bytes/prefix/pop сохраняют прежний
fail-closed смысл, а успешно published512 ещё не означает доставки USB.

## Пределы и обязательные точки последующего source review

Блокирующих замечаний к этому контракту нет. Следующий source verdict должен
подтвердить его точную реализацию, особенно:

- no fall-through из consumed handoff в ordinary grant/prepare/TX/flush/Q;
  при0 actual grant из-за отказа — прежний lifecycle fallback следующего pass;
- каждый OWNED выход и final PUBLISHED post-check; сохранение ранее установленной
  причины и запрет source error старого receipt для новой identity;
- existing N prepare/TX diagnostic boundaries на перенесённых вызовах и Q span,
  exact generated SL binding активных136/64/24, без нового observer;
- фактические размер receipt, linked stack с ISR reserve и0 static growth.

Дополнительные fresh checks стоят времени: только adapter pre/post publication
добавляет до8 полных snapshot-наблюдений, помимо runtime barriers. Сохранённая
private copy защищает512, но не следующую DMA half; признаки R2 не квалифицируют
новый темп или WCET. Known0/queue-full/новый deadline fault остаются допустимыми
отрицательными исходами, а не успешной приёмкой150k. Память SK имеет лишь4байта
вне reserve8192; предполагаемый96B локальный receipt сам по себе ничего не
доказывает о суммарном стеке.

## Достаточные следующие свидетельства

Принят уже заданный один integrated actual-C runner (§7): новые adapter/runtime
boundaries и actual core/queue/serializer/wire, q8→4→8 и contiguous source,
known0/partial/unknown/final-TIME/Q ERROR, healthy scope cancellation против
raw lifecycle/epoch/Stop/HELLO quarantine, deadline3412/3413/wrap и partial
offers. Driver/MMIO/USB timing seams раскрываются; весь новый boundary нельзя
заменить логическим stub. Вместе с source preservation и одним ARM/resource
результатом этого достаточно для следующего программного ревью; старые широкие
GUI/firmware suites не нужны.

§8 корректно сохраняет старую SK и добавляет SL только через explicit expected
build, image/nonce/gen; SL не меняет default, future SM и mismatch отклоняются.
Одна узкая identity-проверка должна использовать actual-C SL fixture этого же
запуска и сохранённую SK; synthetic metadata не подменяет actual SL binding.
Flash/START — лишь после отдельного exact-source и аппаратного плана.

| Критерий | Вес | Балл | Основание документационной приёмки |
|---|---:|---:|---|
| C1 | 0,30 | 9,7 | Точные API/identity/publication и сохранённые Fs/wire; шесть обязанностей закрыты |
| C2 | 0,20 | 9,55 | Одноразовый pending, причины, markers, observed-loss и hard quarantine заданы |
| C3 | 0,25 | 9,6 | Сопоставление с actual SK, достаточная узкая future verification без claims запуска |
| C4 | 0,15 | 9,4 | Явные returns/ownership/конец pass; сложность fresh barriers и cleanup остаётся существенной |
| C5 | 0,10 | 9,7 | Frozen canonical/author/archive, common SL identity и критерии следующей приёмки |

`0,30×9,7 + 0,20×9,55 + 0,25×9,6 + 0,15×9,4 + 0,10×9,7 = 9,60`.
**PASS контракта; implementation/ARM/hardware не приняты.** Можно начинать
ограниченную реализацию S. Физическая цель150k и прежние результаты неизменны.
