# How the protocol was found

The car: Fiat Grande Punto (type 199) 1.4 8V, engine 350A1000, South African market.
The adapter: Veepeak OBDCheck BLE, an ELM327 clone reporting firmware "v2.2".
The host: a Linux laptop with BlueZ and Python [bleak](https://github.com/hbldh/bleak).

No generic OBD app had ever connected to this car. One Windows tool, AlfaOBD, could. So the
ECU does talk, and the task was to find out how.

The session logs referenced below are in [examples/logs](../examples/logs). The VIN, serial
numbers and the adapter's Bluetooth address are redacted.

## Ground rules

1. **Read-only.** Only identification, fault-code reads and data reads. No clearing, writing,
   actuator tests, security access or programming sessions. This was enforced in code with an
   allow-list, so a typo could not send something else.
2. **Least intrusive first.** Adapter only, then passive listening, then standard requests,
   then addressed manufacturer requests.
3. **Read the adapter's error words.** `NO DATA`, `CAN ERROR`, `UNABLE TO CONNECT` and
   `BUS INIT: ERROR` mean different things, and the difference is evidence.

## 1. Reach the adapter

The Veepeak is a Bluetooth Low Energy device, so there is no serial port and no pairing. It
exposes a vendor service `FFF0` with two characteristics: write commands to `FFF2`, receive
replies as notifications on `FFF1`. A second service on the same device also has a
characteristic with UUID `FFF1`, so the lookup has to be scoped to service `FFF0`.

Commands are ELM327 text terminated with a carriage return. A reply is complete when the `>`
prompt arrives.

## 2. Talk to the adapter alone

```
ATZ   -> ELM327 v2.2
ATRV  -> 12.4V
```

`ATRV` reads the voltage on OBD pin 16. The adapter is powered even with the key out, so a lit
adapter says nothing about the ECU being awake.

## 3. Standard OBD-II fails, and how it fails matters

Log: [01-standard-obd-all-protocols.log](../examples/logs/01-standard-obd-all-protocols.log)

| Protocol tried | Reply to `0100` | Meaning |
|---|---|---|
| Automatic search | `UNABLE TO CONNECT` | No protocol produced an answer |
| CAN 11-bit, 500 kbps | `NO DATA` | The frame was sent **and acknowledged**. Nobody replied. |
| CAN 11-bit, 250 kbps | `CAN ERROR` | Nothing acknowledged the frame. Wrong bit rate. |
| KWP2000 fast init, 5-baud init, ISO 9141 | `BUS INIT: ERROR` | No K-line response at all |

A CAN frame is only acknowledged if another node on the bus receives it. So `NO DATA` at
500 kbps against `CAN ERROR` at 250 kbps proves a live 500 kbps CAN bus on pins 6 and 14,
with modules that hear the request and choose not to answer. The ECU is not EOBD compliant.

## 4. Listen before talking

With `ATCSM1` (silent monitoring) and `ATMA` (monitor all) the adapter receives frames without
acknowledging or sending anything.

- 11-bit, 500 kbps: nothing.
- 29-bit, 500 kbps: steady traffic.

```
0030A002  BF05F0D1C3413E8D
0210A006  FF09FF0000000000
0218A006  002C002C002C002C
0618A001  0000000000220000
0628A001  001100800C000000
0810A000  01FE1400
0A18A000  200948000251201E
```

The bus uses 29-bit identifiers. The last byte of each ID turned out to be the sender:
`A000` body computer, `A001` engine, `A002` steering, `A006` ABS. So the engine ECU is present
and broadcasting on this bus.

A practical point: the BLE link is slow, and `ATMA` overflows within about a second
(`BUFFER FULL`). Listen in short bursts, or set a receive filter (`ATCF`, `ATCM`) for one ID.

## 5. Addressed requests, still silence

Log: [02-addressed-requests-padded.log](../examples/logs/02-addressed-requests-padded.log)

Manufacturer diagnostics use physical addressing. For 29-bit CAN the ISO 15765 convention is
`18DA` + target + source, so tester `F1` to engine `10` is `18DA10F1`, and the reply comes
back on `18DAF110`.

KWP2000 and UDS identification requests (`1A 80`, `22 F190`, `3E`, `10 81`) were sent that
way, then to the 11-bit pair `7E0`/`7E8`, then over K-line with the engine address `10`.
Every one returned `NO DATA` or a bus init error.

## 6. The breakthrough: stop padding

Log: [03-survey-sniff-sweep-unpadded.log](../examples/logs/03-survey-sniff-sweep-unpadded.log)

Two experiments ran next.

**An address sweep.** The same request went to every address `18DAxxF1`, with the receive
filter open to any `18DAF1xx`. Three modules reacted, at `28`, `30` and `40`, though with
frames that looked like ISO-TP flow control rather than answers. The engine at `10` stayed
silent. That suggested modules were reacting to the *shape* of the frame.

**Framing variants.** An ELM327 normally formats requests for you: it adds the ISO-TP length
byte and pads the frame to 8 data bytes. With `ATCAF0` formatting is off and you supply the
bytes yourself. With `ATV1` the adapter sends the real length instead of always 8.

```
ATCAF0
ATV1
021A80  ->  18DAF110 03 7F 1A 11
023E00  ->  18DAF110 02 7E 00
```

The first reply the engine ECU ever gave was a refusal: `7F 1A 11` means "service `1A` not
supported". A refusal is still an answer. It showed three things at once: the address is
right, the ECU only accepts unpadded frames, and it does not speak KWP2000 (`1A` is the KWP
identification service). `3E 00` then got a clean positive `7E 00`, so it speaks UDS.

Padding is legal under ISO 15765, and most ECUs accept either form. This one does not. That
single detail is why automatic detection and every generic app fail on this car.

## 7. K-line is not connected

Fast init and 5-baud init were tried against addresses `10`, `01`, `11`, `12` and `33` with
several header formats. All failed at bus initialisation. Published tool documentation agrees
that this model's engine ECU is reached over CAN only. There is nothing to find on pin 7.

## 8. UDS reads, and the flow-control problem

Logs: [04](../examples/logs/04-first-uds-pass-truncated-multiframe.log),
[05](../examples/logs/05-identification-and-dtc.log)

Short answers worked at once. Long answers came back cut off after six bytes:

```
22 F187  ->  62 F1 87 35 31 39        "519", truncated
```

A reply longer than 7 bytes is sent as a First Frame, after which the ECU waits for a Flow
Control frame from the tester before sending the rest. Two things went wrong:

- My own allow-list refused the flow control frame `30 00 00`, since `30` is not a read
  service. Flow control carries no service at all, so it got its own rule.
- Once allowed, sending flow control from the laptop worked for the modules at `30` and `40`
  but not for the engine ECU. A round trip over BLE takes too long and the engine ECU gives up.

The fix is to let the adapter send flow control itself, which it does within a millisecond.
The frame is set explicitly to three bytes so that it is not padded either:

```
ATFCSH18DA10F1
ATFCSD300000
ATFCSM1
ATCFC1
0322F190  ->  18DAF110 10 14 62 F1 90 20 20 20
              18DAF110 21 20 20 20 20 20 20 20
              18DAF110 22 20 20 20 20 20 20 20
```

## 9. Fault codes

`19 02 <mask>` (reportDTCByStatusMask) works. `19 01` and `19 0A` are refused. Each record is
three bytes of code and failure type plus a status byte.

One trap: mask `FF` returns codes the ECU *can* set, with status `40` (test not completed
this cycle). That is a list of monitors, not a list of faults. Ask with mask `08`
for confirmed codes, `04` for pending and `01` for failing right now.

`19 04 <code> FF` returns the stored snapshot for a code, and `19 06 <code> FF` its extended
data. The snapshot is worth reading closely, because it names data identifiers:

```
59 04 01 35 14 08 00 09
   1008 0003CFC0   1009 0023   200A 2DB6   6082 14   1000 0B10
   1924 0000       1003 0083   1937 00FA   1812 0029
```

Nine identifier and value pairs. Four of those identifiers (`6082`, `1924`, `1937`, `1812`)
sit in ranges that the sweeps below never covered. That makes `1800` to `19FF` the obvious
place to look next for live data.

## 10. Finding live data

Log: [06](../examples/logs/06-did-sweep.log), [07](../examples/logs/07-dtc-status-and-live-dids.log)

UDS has a convention that DIDs `F400` to `F4FF` mirror the OBD-II PIDs. Here only `F40C`
(engine speed) answers, and it always reads zero. It is a stub.

So ranges were swept with `22 xxxx`, noting which identifiers return data instead of
`7F 22 31` (request out of range). At about 5 requests per second a 256-identifier block takes
51 seconds. Hits appeared only in `1000`-`100F` and `2000`-`2010`. Eight other blocks were
empty: `0200`, `0300`, `1100`, `2100`, `2200`, `3000`, `4000` and `F000`.
The extended session (`10 03`) unlocked nothing further.

An identifier is just a number until its meaning is established. Three methods were used:

- **Compare states.** Read everything with the engine off, then running, then warm.
  `1004` read 123 with the engine off and 142 to 143 running. The adapter's own voltmeter read
  12.3 V and 14.3 V. So `1004` is battery voltage in tenths of a volt.
- **Sample repeatedly.** Values that never change at idle are configuration or stored data.
  The whole `2000` block is static while running. `200B` equals the value `1008` had in the
  snapshot above, so that block looks like stored fault-environment data.
- **Cross-check against another channel.** `1000` divided by 4 gave 717 rpm while the
  broadcast frame `0618A001` gave 716 rpm. `1003` tracked byte 3 of broadcast frame `0A18A001`
  throughout warm-up.

## 11. Decoding the broadcast frames

Polling over BLE gives a few readings per second. The broadcast frames arrive on their own,
up to 100 times per second, and reading them needs no transmission at all.

Public CAN definitions for the Fiat 500, which shares this platform, gave candidate meanings.
They were checked against the UDS readings before being trusted. The engine-speed field
turned out to be one byte earlier in the frame than the published bit offset suggests: bytes 2
and 3 of `0618A001`, big-endian, one rpm per bit.

Although the frame is sent every 10 ms, its value changes only about 21 times per second at
idle. The ECU appears to compute engine speed once per firing segment, which is about 24 per
second at 716 rpm. That limits what a frequency analysis of this signal can resolve to about
12 Hz. See [example-results.md](example-results.md).

## 12. Cross-check against published work

After the hardware work, a literature search confirmed the main findings independently: the
`18DA10F1` / `18DAF110` pair, the module addresses, CAN-only access for this model, and a
separate "outside EU" engine profile in one commercial tool. None of the sources mention the
padding requirement.

## What generalises

- An ECU that is silent to OBD-II may still be awake. Check with a passive listen.
- The error words tell you which layer failed.
- Sweep addresses with the simplest request there is, TesterPresent.
- When nothing answers, vary the frame format before varying the content: padding, data
  length, 11-bit against 29-bit, bit rate.
- A negative response is a success. It proves addressing and framing are right.
- Let the adapter handle anything timing-critical.
- Never trust an identifier's meaning until two independent readings agree.

## Sources

- MultiECUScan supported vehicles list and user guide: https://www.multiecuscan.net/SupportedVehiclesList.aspx
- AlfaOBD supported units: https://www.alfaobd.com/supported_units.html
- P1kachu, notes on a Fiat 500: https://github.com/P1kachu/talking-with-cars/blob/master/notes/fiat-500.txt
- FiatMon, a Fiat 500L monitor: https://github.com/VeryBusyBee/FiatMon
- CAN definitions for Fiat and Abarth 500: https://github.com/billyjack2/CAN-DBC-Collection
- ELM327 data sheet, for the AT command set
