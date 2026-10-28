# U/SN — границы программного результата

28.10.2026. База exact SL `build/v6s-fw-02`/source695efd9. Production/test
исходники заморожены после одного ARM01 и одного native01; аппаратуры не было.
T/preflush не реализован. Независимый source gate — отдельный отчёт критика.

## Изменение и совместимость

Единственная алгоритмическая дельта — production `mt_batch1024_collect`.
Полная validation остаётся перед любым store. Local count/cursor и группа
4×10→5B убирают повторную индексную работу; scalar prefix/tail сохраняет
owned low bits и очищает speculative high bits при retry. CRC уже был local:
порядок canonical u16le не меняется и отдельного ускорения CRC не заявлено.

Другие семь API и весь остальной текст serializer exact SL. Все54 остальные
patched files совпали byte-for-byte,31 ARM object совпал целиком; observer
object отличается ровно одним common-ID literal SL→SN. Generated board меняет
только ID/product. Runtime/S, Q, DCD/grant6/<500, TIME/ADC/deadline3413, queue,
wire и136/64/24 не менялись. Все compile argv serializer exact прежние, `-Os`.

## Свидетельства

`build/v6u-native-01/result.json`: PASS, input_drift=[]; один actual-C
SL/SN differential executable,4707 API comparisons/28 completed frames.
Return/state32/весь1336B storage/canaries совпали после вызовов. Проверены
4×4 alignment/tails,1/128/512/full1024, last-code4096 и остальные invalid
до stores, rejected-work retry shifts2/4/6. Независимое unpack/frameCRC/
canonical prefixCRC и неизменность accepted frame — в той же модели.
Full runtime/USB/ADC модель не повторялась: рабочие objects exact прежние.

`arm-audit.json`: material compiled work reduction на aligned hot path.
SL0xcc–0x14a —40 listed instruction slots на sample; SN0x102–0x1dc —61 на
четыре samples вместо160 slots четырёх SL iterations. Listing включает
IT/predicated slots/branch tests: это не retired instructions, cycles или WCET;
entry validation/prologue/epilogue и scalar tails в сравнение не входят.
Реальные packed-byte STRB на4 samples:8→5, count state loads:4→0,
count-to-bit MUL:4→0; прежние8 canonical CRC table loads остаются.

ARM01 BIN49744B, SHA
`abc20c98a870c082fce3cb6fab8e0789aa7bd42e53c5bf342861d0c9d3c37714`.
Flash +212B относительно SL. Collect stack frame36→48B(+12), но условный
whole-image bound6348/aligned6352 остаётся прежним. Data128+BSS12156,
0newstatic; с reserve8192 занято20476/20480, арифметический остаток4B.
136@0x20002f1c,64@0x20002fa4,24@0x20002fe4. Это static proof, не watermark.

SN config/generated header — общий источник board/observer. У обоих есть
dependency на тот же header; linked BIN word mt_board+12 равен0x5632534e,
observer .o равен SL после одной замены literal. Host identity использует
отдельно помеченную synthetic derivation старого actual SL трио; нового
actual SN observer execution или физической аутентификации это не означает.

## Неудачи и пределы

ARM/native failed attempts нет, успешных сборок/исполнений по одному.
Первый offline analyzer не распознал mt_board в CRLF nm: прежний script и
`arm-audit-attempt-01.json` сохранены. Исправлена только parsing newline
normalization; повторён offline read-анализ, не ARM/native.

Меньше compiled work не доказывает устойчивые150k, WCET, CPU-долю либо
устранение queue-full. S2 prepare58/147ms — inclusive wall, не доляCPU.
SL physical failure сохраняется. COM/SWD/Reset/Flash не выполнялись;
аппаратный опыт возможен только после exact source/plan review root.
