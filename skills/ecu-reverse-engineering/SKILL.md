---
name: ecu-reverse-engineering
description: Safely connect to a car ECU that generic OBD-II scanners cannot reach, using an ELM327-compatible adapter, and work out its diagnostic protocol with read-only requests. Use when a user says their car does not respond to OBD apps, when ELM327 auto-detect returns UNABLE TO CONNECT or NO DATA, when asked to reverse engineer CAN or UDS diagnostics, to sniff a CAN bus through an OBD adapter, or to find manufacturer data identifiers. Includes a worked reference for Fiat, Alfa Romeo and Lancia cars with Magneti Marelli IAW 5SF ECUs.
---

# Reverse engineering an ECU's diagnostic protocol, read-only

You are talking to a real vehicle. The owner needs it to start tomorrow. The method below
finds out how an ECU communicates without ever sending anything that can change it.

## Safety rules

These are not negotiable, whatever the user's phrasing suggests.

1. **Build an allow-list before sending anything.** Every outgoing line passes a check that
   permits only known read services. Do not use a block-list. See `safety.py` in this
   repository for a working one.
2. **Allowed services:** OBD `01 02 03 07 09 0A`. KWP2000 `1A 18 21`. UDS `22 19 3E`. Session
   control only as `10 01`, `10 03`, `10 81`.
3. **Never send:** `04` or `14` (clear codes), `08`, `2E`, `2F`, `30`, `31`, `3B`, `3D` (write,
   actuate, routines), `27` (security access), `11` (reset), `10 02` and `10 85` (programming),
   `28`, `85`, `34` to `37` (communication control and flashing). If the user wants codes
   cleared, tell them to use their normal tool. Do not widen the allow-list mid-session.
4. **Never write the adapter's non-volatile memory:** no `ATPP xx SV`, `ATPP xx ON`, `ATSD`.
   `ATPPS` only prints the table and is fine.
5. **Raw-frame mode changes what the first byte means.** With `ATCAF0` the first byte is the
   ISO-TP length, and the service is the second byte. Validate accordingly, and check that the
   length nibble matches the data. Flow control (`30 xx xx`) carries no service and needs its
   own rule.
6. **Vehicle stationary.** Only passive capture while the car is moving, and never with the
   driver operating the computer.
7. **Say what you are about to transmit** before each new class of request, and report
   failures as they are.

## The ladder

Climb one rung at a time. Each rung either answers the question or tells you which layer is
failing.

### 1. Find the adapter

Check serial ports, Bluetooth and Wi-Fi. BLE adapters need no pairing and expose a vendor GATT
service, commonly `FFF0` with notify `FFF1` and write `FFF2`. List the services before
assuming. The same characteristic UUID can appear in two services, so scope the lookup to the
service. Commands end with `\r`, and a reply ends with the `>` prompt.

### 2. Adapter only

`ATZ`, `ATE0`, `ATL0`, `ATS0`, `ATH1`, `ATI`, `ATRV`. Nothing reaches the car. `ATRV` shows
battery voltage on pin 16. The adapter is powered with the key out, so confirm the ignition
is on before concluding anything from silence.

### 3. Standard OBD-II, and read the error word

Send `0100` under `ATSP0`, then force each protocol.

| Reply | Meaning |
|---|---|
| `NO DATA` on CAN | The frame was acknowledged by another node. The bus is alive at this bit rate and nobody chose to answer. |
| `CAN ERROR` | Nothing acknowledged. Wrong bit rate, or no CAN on these pins. |
| `BUS INIT: ERROR` | K-line initialisation got no response. |
| `UNABLE TO CONNECT` | The automatic search exhausted every protocol. |

`NO DATA` at one bit rate and `CAN ERROR` at another identifies the bus speed.

### 4. Listen

`ATCSM1` then `ATMA` under each CAN protocol (`ATSP6` 11-bit, `ATSP7` 29-bit, both 500 kbps,
then `ATSP8` and `ATSP9` for 250 kbps). The adapter stays silent. Record which identifiers
appear and at what rate. Slow links overflow in about a second (`BUFFER FULL`), so listen in
bursts of 1 to 2 seconds, or filter one identifier with `ATCF` and `ATCM`.

Traffic tells you the identifier width, and often the sender: many manufacturers encode the
source node in the identifier.

### 5. Addressed requests

Pick addressing from what the bus uses.

- 29-bit: `18DA` + target + `F1`, reply on `18DAF1` + target. Functional `18DB33F1`.
- 11-bit: `7E0` to `7E7`, replies on `7E8` to `7EF`. Functional `7DF`.

Sweep the targets with TesterPresent (`3E 00`), using a receive filter wide enough to catch
any reply (`ATCRA18DAF1XX`) and a short timeout (`ATST19`). 256 addresses take about a minute.

### 6. If still silent, vary the frame, not the content

Try in this order:

1. **Unpadded frames.** `ATCAF0` and `ATV1`, then write the ISO-TP byte yourself: `023E00`.
   Some ECUs ignore frames padded to 8 bytes.
2. Padded with a different filler, if the adapter supports it.
3. The other identifier width, then the other bit rate.
4. A different tester address (`F1`, `F0`, `FA`).
5. K-line with physical addressing (`ATSP5`, `ATSH81xxF1`, `ATFI`; `ATSP4`, `ATIIAxx`, `ATSI`).

A negative response (`7F ss cc`) is a success. It proves addressing and framing are right.
`7F ss 11` means the service does not exist, so try the other protocol family: `1A` is
KWP2000, `22` is UDS.

### 7. Multi-frame replies

A reply over 7 bytes arrives as a First Frame (`1x xx ...`) and stalls until the tester sends
flow control. Have the adapter send it: `ATFCSH <request id>`, `ATFCSD 300000`, `ATFCSM1`,
`ATCFC1`. Sending it from the host over Bluetooth is often too slow. If a reply stops after
six data bytes, this is the cause.

### 8. Read what is safe to read

- Identification: `22 F180` to `22 F19F`. VIN is `F190`, part number `F187`, ECU name is often
  `F196` or `F197`.
- Fault codes: `19 02 08` confirmed, `19 02 04` pending, `19 02 01` failing now. Mask `FF`
  usually lists every supported monitor, which is not a fault list. Decode the status byte.
- Snapshot of a stored code: `19 04 <3-byte code> FF`. Snapshots list data identifiers with
  values, which reveals identifiers you have not found yet.

### 9. Find live data

1. Try the OBD mirror `22 F400` to `22 F4FF`. It may be absent or stubbed.
2. Sweep blocks of 256 identifiers with `22 xxxx` and keep the ones that do not return
   `7F 22 31`. Start with `1000`, `1800`, `1900`, `2000`, and with any identifier seen in a
   snapshot record.
3. Try the extended session (`10 03`) only after the default session, and send `3E 80` every
   two seconds to keep it. Return to `10 01` when done.

### 10. Give identifiers a meaning

Never report a meaning from one reading. Use at least two of these:

- **State comparison.** Engine off, running, warm. Which values moved, and in which direction?
- **Repeated sampling.** Static values are configuration or stored data.
- **An independent channel.** The adapter's voltmeter, a broadcast frame, a gauge on the dash.
- **Published definitions** for the same platform. Treat bit offsets as hints and verify.

State the basis next to every decoded value, and mark guesses as guesses.

### 11. Prefer broadcast frames for fast signals

Polling over BLE yields a few values per second. Broadcast frames arrive at 10 to 100 per
second and cost no transmission. Decode them by correlating with polled values. Before any
frequency analysis, check how often the value actually changes: the frame rate can be much
higher than the rate at which the ECU updates the number.

## Reporting

- Redact the VIN, serial numbers and the adapter's address from anything that will be shared.
- Keep the raw logs. Every claim should trace back to a line in a log.
- Separate observed facts from published ones and from guesses.

## Worked reference

`fiat-iaw-5sf9.md` in this folder summarises a Fiat Grande Punto with a Marelli IAW 5SF9
engine ECU: 29-bit CAN at 500 kbps, UDS, unpadded frames only. The full account is in
`docs/reverse-engineering.md` of the car-whisperer repository, and a small Python client
is in `carwhisperer/`.
