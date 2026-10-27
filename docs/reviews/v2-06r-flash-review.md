# V2-06r / R2 — независимый допуск точного плана

27.10.2026. **PASS9,60/10 только для исполнения одного плана R2 при условиях
ниже.** Критик `stream200_critic` не автор helpers и не оператор аппаратуры.
Новых тестов, сборок, COM/SWD/Flash/Reset/START критик не выполнял.

Точный [план](../verification/v2-usb-gate/plan-01/build/v6r-board-01/plan.json):
SHA256 `f7d751dcc2a52e6046cbfaeacd7e4bdc0aa4d97a89e32d2249f5dc95e10ec8ec`.
Source commit `bc851d6ee7b16663db95acb32733cacff7a50f36`.
[Архив плана](../verification/v2-usb-gate/plan-01/manifest.json):
SHA256 `7742bb5e26d25e7b2053f4983312a456c557e3eee8ce1e814f8775a470243d24`.

Лично пассивно сверены16 пар/147379байт архива и28 execution inputs; все
побайтные/размерные/hash привязки совпали. Прочитаны program/run/read helpers,
offline проверки и backup logs. Прежний [R1 PASS9,60](v2-06r-review.md) и
сохранённый Windows L package повторно не тестировались. Package ZIP
`436cdaf1f27322e8ff7e90809f6c091950edcf7a599a97766c128c6e19a6dbfe`
совпал с планом; wire/capture не менялись, новый24B decoder используется offline.

Образ SK/`0x5632534B`:46820байт,
SHA256 `dd6e8322488a1d4ada50c2c722820f971b4b4782c303bdafb1410180e2efc8f1`.
Readback length `0xB6E4` равен всему образу, затем требуется побайтное равенство.
Свежая резервная копия65536байт:
`eb6b98b30914cc5917ecdf7593a4b700a65a3dc8cf2fca6827a5de472f7a34d9`;
первые45372байта лично сравнены с exact SJ и равны. Сохранённый HOTPLUG log
подтверждает SN`57005400120000393333574E`, device0x410,3,2В. Это не заменяет
свежую проверку прямо перед исполнением и не доказывает физическую модель MCU.

Допуск охватывает ровно один program/verify, независимый full readback и один
Reset/Run. До Flash root снова подтверждает expected probe/COM6 с code0,
отсутствие владельцев, прежние условия PA0 пустой/питание платы только USB.
Затем нужен **новый фактический ответ после SK Reset**: выключить USB платы
и ST-Link на10с, включить плату первой и ST-Link через5с. Прежний ответ до
прошивки не подходит. Root связывает actual reply с reset log и сохраняет
свежий inventory/хронологию. Helpers не устанавливают эти внешние факты сами.

После этого допустим единственный START150000, mode5/DATA1024/10 retained bits,
запрос30с Record. Exact CAPS/build до START, fresh discovery/selected nonce,
PSC47/ARR9 и deadline3413 сохраняются. Нет50/100, повторного START,
автоматического retry/Reset/rollback. При отказе план заканчивается;
сохранённый корректный префикс не называется успешными30с.

SWD/halt при активном COM запрещены. `root_read_closed` допускается только
после подтверждённого owner-close и offline PASS согласованных END/STOP/ACK.
Учтены оба receipt пути: PASS `owners_closed`; FAIL `cleanup_finished` плюс
`phase=closed`. Читаются136@0x20002F1C,64@0x20002FA4,24@0x20002FE4 — по два
раза — затем stopped TIM3/ADC/DMA/RCC. ADC block0x40012408+12байт не включает
ADC_DR; иных новых чтений нет. При неподтверждённой остановке/terminal evidence
нельзя обходить gate и продолжать этот helper по прежнему допуску.

Диагностика связывается с exact SK/readback/nonce/gen и single-boot chronology.
24B относится к episode до N CLOSING, а USB64 позже; HELD1 не доказывает один
episode, CAP не объясняет более поздний отказ. Реальное отсутствие SWD во время
захвата фиксируется оператором, не выводится из JSON. В docstrings двух старых
offline helpers осталось имя SJ; фактические build/image берутся из exact SK
plan. Это неблокирующая подпись, а не основание переименовать результат опыта.

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 | 0,30 | 9,70 | Exact SK/режим/адреса и один ограниченный опыт |
| C2 | 0,20 | 9,55 | Backup/full readback/owner-close/fail-stop; внешние условия требуют фактической записи root |
| C3 | 0,25 | 9,60 | Лично сверены pins/архив/helpers; аппаратный результат ещё отсутствует и не подменён |
| C4 | 0,15 | 9,40 | Последовательность ясна; унаследованные подписи и ручная хронология оговорены |
| C5 | 0,10 | 9,70 | Commit/argv/hash/exclusive output и сохранение отказов |

Итог `9,60`. P0/P1 внутри этого exact-plan admission не обнаружены.
**P1-M2-01 OPEN; physical150k и диагностическая пригодность будущего опыта
оцениваются отдельно.** Этот файл разрешает только указанный план с его pins;
новый образ, изменение helpers или повтор опыта требуют отдельного решения.
