# U/SN: независимое ревью эквивалентной упаковки collect

29.10.2026 (Asia/Qyzylorda). Критик `/root/stream200_critic`, не автор реализации, модели или сборки. Свидетельства U созданы28.10.2026.
**PASS9,625/10** в области U: эквивалентность serializer, материальное сокращение работы compiled aligned loop, exact ARM/resources и offline identity. Это не приёмка устойчивых150k, Windows-пакета или аппаратный допуск. S2 REWORK6,375 и **P1-M2-01 OPEN** сохраняются.

## Точное состояние

- Source commit `308406d8627fc2aedc6e8eb7abd833e1f229102f`; функциональная база SL — `695efd95e7c4ba72bfa6fb5fb511b85186be6266`, `build/v6s-fw-02`.
- [Freeze](../../build/v6u-freeze.json): `fe206f96e8c7d5ea6704542870f051278dda18be9570f50faca393e3d4f6cf95`.
- [Delta manifest](../verification/v2-collect-local/production-01/manifest.json): `d4de6d4830efdc7372f7db3bda452b5a1b7cdaf959d7bcf8d2a85759754ac11d`. Лично сверены81строка:48копий/2693095байт и33ссылки/617105байт на frozen S; все source/archive/size/SHA совпали. Все63пина freeze также совпали.
- SN `0x5632534e`, BIN49744байта SHA `abc20c98a870c082fce3cb6fab8e0789aa7bd42e53c5bf342861d0c9d3c37714`; ELF SHA `bb479dc312f68c4636a5dc1b79514393f0a31a4eb17e6ed3581a7db4946322f1`.

## Корректность изменения

Прочитан полный diff production `mt_batch1024_collect` и differential model/runner. Сначала остаются прежние проверки аргументов, phase/count/index overflow и **всех** ADC12 codes; до их завершения stores нет. Локальные start/cursor заменяют повторную адресную арифметику. Scalar prefix/tail переводит shifts2/4/6 к alignment, сохраняет только уже-owned low bits и заменяет speculative high bits. На aligned группе четыре10-битных значения занимают ровно пять байт, без лишнего store за группой. Canonical `(code&4092)` и порядок CRC u16le неизменны. State32 публикуется при том же успешном возврате. Existing disjoint state/input/storage контракт сохранён, `restrict` не добавлен.

Остальные семь API и весь текст вне collect совпадают с SL. Лично побайтно подтверждены54других patched файла и31другой ARM object; N object отличается только одним common-ID literal SL→SN. Board меняет config-derived identity/product. S/runtime/Q/ADC/TIME/DCD, whole-fit384, queue8, staging1336, grants6/<500 и ABI136/64/24 прежние. T/preflush не внедрён.

## Сохранённые необходимые свидетельства

**Native01 — один actual-C запуск, PASS.** [Result](../../build/v6u-native-01/result.json) SHA `c56182f6ce5f41923be88a8016cd0b7fe26fca3702b894064eae820e2cc098f0`; [source-equivalence](../../build/v6u-native-01/source-equivalence.json) SHA `2cfc1ba4ca7a3a0c411067189a99f37412bbcb464c38e71064e07bae5a10c8bc`. Model SHA `52ca19d1630e61d101d56e7195d873eab81a5f1b52b02ec6ab039f4d09a844e7` исполняет отдельно скомпилированные frozen SL и SN, не копирует collect. Сохранены4707сравнений/28frames: return/state32/all1336bytes/canaries, все четыре initial/append-tail alignment,0/max/mixed codes,1/128/512/full1024, late invalid4096 до stores, null/count/index/overflow, rejected-work retry при shifts2/4/6. Независимый unpack/frameCRC/prefixCRC и неизменность accepted frame проверены той же моделью. Лично сверены195input pins, stdout и единственная команда model; input_drift=[].

**ARM01 — одна сборка, PASS.** Receipt SHA `b794a50bdb50025cbc37d4ed9132d975fcd97de313395ec626a3dfe954e543cc`. Лично сверены580inputs_before,121compiler dependency,34objects,36analysis inputs и3image artifacts; drift отсутствует. `-Os` сохранён.

В исходных disassembly лично прочитаны SL loop0xcc–0x14a и SN aligned4 loop0x102–0x1dc. На четыре samples: **8→5 STRB,4→0 count reload,4→0 MUL**; восемь canonical CRC table loads остаются. Позиции листинга160→61 подтверждены пассивным подсчётом. Это содержательное уменьшение работы горячей aligned ветви. Числа включают listing/conditional/branch slots и исключают validation/prologue/epilogue/scalar tails; это **не retired instructions, cycles, WCET или процент ускорения всего collect/прибора**. CRC уже был local в SL, отдельная экономия CRC не заявляется. [ARM audit](../../build/v6u-analysis/arm-audit.json) SHA `970b79d073aadd0aecd9f03fa0b491539b6f5da4ad1f62068c0b042baed7caff` связан с теми же листингами.

Ресурсы: data128+BSS12156+reserve8192=20476/20480; **0новых static bytes, остаток4байта**. Все56RAM symbols совпали по адресу/размеру/типу. Collect frame36→48байт, но критический whole-image путь остаётся6348/aligned6352. [Static bound](../../build/v6u-fw-01/static-bound.json) SHA `7dccfc42ca204a19c2f142dfd9e0673322d7ea602a0d90b63dbeb4ad1db7ebdd`: root5952+IRQ288+exceptions108, при прежних явных предпосылках; это не физический watermark. Legacy136@0x20002f1c, N64@0x20002fa4, gate24@0x20002fe4 прежние.

Common identity: generated header `d70350aec7a6d27f4e2c3541d08481742fa9022045a515aa3c3a3cc167ce38d0` задаёт SN и является dependency board/N. Лично прочитанное слово BIN `mt_board(0x0800c158)+12` равно`0x5632534e`; прежний observer object совпал после единственной замены literal. Так проверена интеграция ID, без подмены synthetic host-данными.

**Host identity01 — один PASS10.** [Result](../../build/v6u-host-identity-01/result.json) SHA `bf86604726dff97fbef2622c39de157ec9c4cc3c1aeb081f40b45d0f50236f15`;11input pins/все output pins лично сверены. Production decoder diff — только docstring и явный SN allowlist; старые defaults, ограничения и SM rejection сохраняются. Архивный actual-C SL decoded SHA `f3851cd9662c6a14d3b65e41de75ad458f51518657ac89548e2ea3c94224fc31` прежний. SN fixture **явно synthetic-derived SL**, только legacy build word offset12 заменён;24/64 прежние. Проверены crossed SL/SN/image, unsupported SM/SO и отсутствие явного SN при default SG. Это не actual SN observer execution, независимые физические пары или аутентификация платы.

Неудачный первый offline ARM parser сохранён: CRLF мешал regex mt_board. Лично проверен repair diff — только newline normalization. ARM/native/host не повторялись; два запуска чтения сохранённых листингов не скрыты как две сборки. Личный одноразовый hash-audit также потребовал исправить Python comprehension до выполнения; он не исполнял продукт и не создавал product evidence.

## Оценка и границы

| Критерий | Вес | Балл | Основание |
|---|---:|---:|---|
| C1 | 0,30 | 9,7 | Точный collect-only diff, bytes/state/CRC и old contract сохранены |
| C2 | 0,20 | 9,6 | Invalid-before-write/retry/capacity, zero static growth, exact stack; физического watermark нет |
| C3 | 0,25 | 9,7 | Actual differential, прочитанные ARM loops и независимые hashes; synthetic host пределы явны |
| C4 | 0,15 | 9,4 | Узкая оптимизация с scalar fallback; unrolled4 требует сохранения модели |
| C5 | 0,10 | 9,6 | Exact source/freeze/delta references, команды и неудачный parser сохранены |

`2,91+1,92+2,425+1,41+0,96=9,625`. Открытых P0/P1 в указанном программном scope не найдено. Windows/PowerShell; лично выполнялись чтение/diff/rg и пассивные SHA/байтовые/листинговые сверки. Никакие model/decoder/build/COM/SWD не запускались критиком. Неизменённые GUI/Windows package и весь legacy suite не повторялись. Новый exact аппаратный план требует отдельного допуска; меньшая работа упаковки не доказывает устранение queue-full или устойчивость150k.
