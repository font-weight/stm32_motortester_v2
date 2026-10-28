# S2 follow-up: независимая проверка гипотезы preflush

28.10.2026. `/root/stream200_critic`, не автор реализации или предложения.
**BLOCKED_EVIDENCE, score:null — полезность выбранного preflush ещё не обоснована достижимым здоровым состоянием.** Разрешено продолжать только draft T, проверяющий этот пробел. Реализация, образ и аппаратный опыт этим отчётом не принимаются. S2 остаётся **REWORK6,375**, P1-M2-01 OPEN; прежнее физическое ревью не изменено.

Проверены [замороженное предложение](../verification/v2-postcopy-handoff/followup-01/analysis.md), SHA `f739c06f06cff169f2ca943345734e7802e5e9ec0df2bd0ad5ff9bad1a5a616e`, и [manifest](../verification/v2-postcopy-handoff/followup-01/manifest.json), SHA `92fec6d376aacb33d044d9a263a52fbd0cda00663076b8d26ea594844cc25254`. Обе source/archive пары (31879байт) лично совпали по байтам, размеру и SHA; предыдущий draft сохранён. База продукта SL — `695efd95e7c4ba72bfa6fb5fb511b85186be6266`, HEAD чтения — `39af5cd5bbc101a88c44614c4488502298162b53`.

## Подтверждённая часть

Поздние FIFO free384, RESUMED/APPLICABLE0 и событие за224cycles до Nclose не определяют FIFO в момент предыдущего whole-fit check. PREqueued320 означает состояние до загрузки последнего PMA64; извлечение из FIFO ещё не означает ACK/delivery. ISR и последующий snapshot могут объяснить позднее свободное место после уже принятого решения queue-full. Предложение правильно отделяет это от причины отказа и не утверждает, что S handoff/hint исполнился. Два опыта с21 DATA не доказывают ни эффект, ни отсутствие эффекта S.

Exact runtime подтверждает два допустимых класса: обычные offers до TX и selected handoff с known0, прежним postflush и последующими offers без final commit/Q. Однако это **не доказывает**, что postflush в выбранной ветви впервые запустил buffered transfer.

## Один существенный пробел: достижимость buffered + claimable

В `build/v6s-fw-02` лично прочитана вся необходимая цепочка:

- `source/.../tinyusb/src/tusb.c:425–434`: accepted write при FIFO≥64 автоматически вызывает `tu_edpt_stream_write_xfer`.
- `patched/usbd.c:218–228`: CDC имеет `xfer_isr=NULL`. Само IN completion в ISR не снимает BUSY для CDC; ожидание foreground completion сохраняет отказ `stream_claim`.
- `patched/usbd.c:842–862`: task снимает BUSY/CLAIMED непосредственно перед class callback. `source/.../cdc_device.c:515–523` затем сам отправляет оставшийся FIFO или ZLP; weak TX callback пустой, собственного переопределения в SL нет.
- `patched/v2/app/mt_live_runtime.c:432–443`: этот task выполняется до postcopy handoff. Между ним и выбранным preflush нет нового foreground producer FIFO. Исходные nested scopes разрешены, но не отменяют BUSY.

Для наблюдённого остатка183 shortage означает FIFO≥202, то есть уже выше порога auto-flush64. Если transfer ещё BUSY, дополнительный flush возвращает0. Если completion обработан task, callback уже пытался отправить остаток. Не показан здоровый переход, оставляющий перед handoff FIFO с такими данными и свободный endpoint. Ошибка submit может снять BUSY, но bridge помечает submit failure; это не разрешает считать состояние здоровым и обходить quarantine.

Следовательно, фраза предложения о возможном порядке «known0 → лишь postflush запускает buffered transfer» требует дополнительного основания. Изолированная модель, вручную начинающая с BUSY=0/FIFO320, не закрывает этот пробел. Это не доказательство невозможности всех путей и не новый установленный дефект SL: это отсутствующий необходимый аргумент для выбора следующего изменения. Автор независимо признал тот же пробел; замороженное предложение не переписывается.

## Что требуется от T до реализации

1. Показать конкретный **здоровый исходный API/event trace** до selected handoff с buffered+claimable endpoint, учитывающий auto-flush, task completion, ZLP, единственного foreground writer и DCD/bridge refusal. Без ручной подмены BUSY/FIFO. Если такого пути нет, отклонить preflush до ARM/HW; задержка от лишнего вызова сама по себе не подтверждает заявленный механизм.
2. Если путь есть, закрепить один nested preflush, zero/denial/submit-loss исходы, сохранение pending512 и consumed marker, fresh TIME/epoch/raw-lifecycle проверки, old postflush/Q и одно grant/TX. Не расширять PRIMASK, не обновлять исходный poll stamp, не считать положительный flush return подтверждением USB delivery. No-IN/BUSY остаются честными known0 без spin/второго DATA.
3. Только затем — одна необходимая actual-boundary модель с явными claim/первым PMA64/последующими IN, нужными отрицательными новыми границами и source/resource audit. Не заменять причинный переход seam «flush всегда освобождает384». Сохранить original3413, 6/<500, zero static growth/8192reserve и честный новый deadline failure. Native не доказывает устойчивость150k.

| Критерий | Вес | Состояние свидетельств |
|---|---:|---|
| C1 | 0,30 | Facts/inference разделены, но полезный source route не установлен |
| C2 | 0,20 | Сохранение S guards предложено; точные T исходы ещё должны быть закреплены |
| C3 | 0,25 | S2 и исходники пригодны; необходимая достижимость initial state отсутствует |
| C4 | 0,15 | Узкая гипотеза, один собранный блокер, без нового profiler/suite |
| C5 | 0,10 | Frozen pins, две точные копии и source anchors воспроизводимы |

Оценка не назначается при отсутствующем обязательном свидетельстве. Пассивно использованы Get-Content/rg, Git revision/status и Python только для SHA/байтов. Продуктовые тесты, decoder/Open, сборки и аппаратные действия не выполнялись. [JSON ревью](../verification/v2-postcopy-handoff/critic-followup.json) содержит точные прочитанные пины. [S2 physical review](v2-06s-physical-review.md) и установленная остановленная SL неизменны.
