# Protocol reference

Fiat Grande Punto (199) 1.4 8V, engine 350A1000, South African market.
Engine ECU: Magneti Marelli IAW 5SF9, name `5SF9AG`, hardware `IAW5SFHW405`, software
`881AW23E`, Fiat part number 51926690.

Each table says how the entry was established. "Observed" means read from this car.
"Published" means taken from the sources listed in
[reverse-engineering.md](reverse-engineering.md) and not independently confirmed here.

## Physical and transport layer

| Item | Value | Basis |
|---|---|---|
| Bus | C-CAN on OBD pins 6 and 14 | Observed |
| Bit rate | 500 kbps | Observed |
| Identifiers | 29-bit | Observed |
| Transport | ISO 15765-2 (ISO-TP), normal fixed addressing | Observed |
| Request ID | `18DA` + target + `F1` | Observed |
| Response ID | `18DAF1` + target | Observed |
| Frame padding | **Must not be padded.** Data length equals the real length. | Observed for the engine ECU |
| Flow control | `30 00 00`, three bytes, must follow the First Frame within a few ms | Observed |
| Application protocol | UDS, ISO 14229 | Observed |
| Standard OBD-II (modes 01 to 0A) | Not answered on any protocol | Observed |
| KWP2000 service `1A` | Refused: `7F 1A 11` | Observed |
| K-line, pin 7 | No response to any init | Observed |

## Modules that answer on this bus

| Address | Module | Basis |
|---|---|---|
| `10` | Engine, Marelli IAW 5SF9 | Observed, identified by its own data |
| `28` | ABS | Answers TesterPresent. Role published. |
| `30` | Electric power steering | Answers, part number 51927085. Role published. |
| `40` | Body computer | Answers, part number 51962483, holds the VIN. Role published. |

All other addresses from `00` to `FF` were silent.

## Services on the engine ECU

| Request | Result |
|---|---|
| `3E 00` TesterPresent | `7E 00` |
| `10 01` default session | `50 01 00 32 01 F4` |
| `10 03` extended session | `50 03 00 32 01 F4`. Unlocks no additional identifiers in the ranges tested. |
| `22 xxxx` ReadDataByIdentifier | Works in the default session |
| `19 02 mm` DTCs by status mask | Works. Status availability mask `CF`. |
| `19 04 cccccc FF` DTC snapshot | Works |
| `19 06 cccccc FF` DTC extended data | Works |
| `19 01`, `19 0A` | `7F 19 12`, sub-function not supported |
| `1A xx` (KWP2000) | `7F 1A 11`, service not supported |

Write, clear, routine, security and reset services were never sent.

## Identification identifiers (engine ECU)

| DID | Content | Example |
|---|---|---|
| `F180` | Boot software identification | `01 01 58 09 05 0C ...` |
| `F181` | Application software identification | `01 01 "881A"` |
| `F182` | Application data identification | `01 01 "W23E"` |
| `F183`, `F184`, `F185` | Fingerprint blocks, mostly blank | ends `13 04 15` |
| `F186` | Active session | `01` |
| `F187` | Spare part number | `51926690` |
| `F18C` | ECU serial number | redacted |
| `F190` | VIN | 17 spaces. The engine ECU's VIN field is blank on this car. |
| `F192` | Supplier hardware number | `IAW5SFHW405` |
| `F193` | Supplier hardware version | `00` |
| `F194` | Supplier software number | `881AW23E` |
| `F195` | Supplier software version | `00 00` |
| `F196` | ECU name | `5SF9AG` |
| `F1A0` | Combined identification block | the fields above concatenated |
| `F1A4` | Unknown, blank | six spaces |
| `F1A5` | Unknown | `7A 07 02 08 E0` |

Refused with `7F 22 31`: `F188`, `F189`, `F18A`, `F18B`, `F191`, `F197`, `F198`, `F199`,
`F19D`, `F19E`, `F1A1` to `F1A3`.

## Data identifiers (engine ECU)

| DID | Bytes | Meaning | Scaling | Basis |
|---|---|---|---|---|
| `1000` | 2 | Engine speed | raw / 4 rpm | Confirmed against broadcast `0618A001` |
| `1002` | 2 | Unknown, 0 at idle | | |
| `1003` | 2 | Coolant temperature | raw − 40 °C | Tracks broadcast `0A18A001` byte 3. Offset assumed. |
| `1004` | 2 | Battery voltage | raw / 10 V | Confirmed against the adapter's voltmeter |
| `1008` | 4 | Counter, about +1 per minute while running | Possibly engine running time in minutes | Observed |
| `1009` | 2 | Timer since engine start, about +1 per 15 s | unknown unit | Observed. Reads 1 just after a start. |
| `2000` | 2 | Static, `0010` | | Observed |
| `2001` | 3 | Static, `15C3D6` | | Observed |
| `2002` to `2007` | 1 to 3 | Static, zero | | Observed |
| `2008` | 4 | Static, close to `1008` | | Looks like a stored copy of the `1008` counter |
| `2009` | 2 | Static, `0018` | | Observed |
| `200A` | 2 | Static, 11749 | | Possibly millivolts |
| `200B` | 4 | Static | | Equals `1008` as stored in the DTC snapshot |
| `200C` | 2 | Static, 36 | | Observed |
| `200F` | 1 | Static, `F5` | | Observed |
| `2010` | 4 | `FFFFFFFF` | | Observed |
| `F40C` | 2 | Always zero | | A stub. The `F4xx` OBD mirror is not implemented. |

Identifier `6082` appears in a DTC snapshot record and has not been read directly.

## Live data block, `1800` to `19FF`

The DTC snapshot named identifiers in this range, and a sweep found 100 that answer
([log](../examples/logs/09-did-sweep-1800-19FF.log)). All 100 were then logged 19 times over
four minutes at idle while the engine warmed from 73 to 82 °C, with the air conditioning
switched on for about 45 seconds in the middle. Meanings below come from how each value
behaved. "Confirmed" means it matched an independent reading.

| DID | Idle | With A/C load | Meaning | Basis |
|---|---|---|---|---|
| `186B` | 2800 | 3400 | Idle speed target, raw / 4 rpm: 700 rpm, 850 rpm with A/C | Confirmed. Engine speed `1000` follows it one sample later. |
| `1956` | 845 | 845 | Barometric pressure, mbar | Likely. Static and plausible for the altitude. |
| `181F` | 280 | 450 | Intake manifold pressure, mbar | Likely. Tracks load. |
| `197D`, `197E` | 141 | 141 | Battery voltage, raw / 10 V | Confirmed against `1004` |
| `1898`, `189A` | 60 to 800 | same | Oxygen sensor voltage, mV | Likely. Swings between lean and rich. |
| `1875`, `1876` | 02 or 08 | same | Mixture state flags, toggling | Likely |
| `1811`, `1812` | +50 | −37 to −70 | Signed. Possibly ignition advance in 0.1° | Guess |
| `1824`, `18BC` | −23 | +60 to +88 | Signed. Idle torque or airflow correction | Guess |
| `1804`, `1805`, `1931` | 02, 02, 0000 | 40, 01, 1802 | Status flags that change with the A/C request | Observed |
| `1802`, `1862`, `1863` | 32 | 56 to 72 | Load or torque, percent | Guess |
| `1937`, `1938` | 275, 227 | 465, 390 | Load-related | Observed |
| `1942` | 250 | 555 | Load-related, possibly injection time | Guess |
| `18A6`, `18AD`, `18AE`, `18B1`, `186A`, `1817`, `181D`, `192F`, `18A7`, `1864` | | rise | Load-related | Observed |
| `1865` | 912 | 875 | Falls with load | Observed |
| `1936` | 320 to 338 | | Rises with warm-up | Observed |
| `1934`, `1935` | 326 to 270, 88 to 85 | | Fall with warm-up | Observed |
| `194F` | 101 to 108 | | Rises steadily with time | Observed |
| `18A0`, `18A2`, `18A3`, `18A4` | 988, 1012, 1026, 1001 | each +14 | Four values around 1000 with fixed offsets between them. Possibly per cylinder. | Guess |
| `1891` to `1894` | 46 to 71 each | | Four fluctuating values. Possibly per cylinder. | Guess |
| `1966` to `196B` | | | Static, ascending. Looks like table breakpoints. | Observed |

Another 42 identifiers in the block were static throughout.

One pass over 105 identifiers takes 14.4 seconds, so anything faster than that is undersampled.
The oxygen sensor readings in particular are snapshots of a signal that switches several times
per second.

Ranges swept with no hits: `0200`-`03FF`, `1010`-`11FF`, `2011`-`22FF`, `3000`-`30FF`,
`4000`-`40FF`, `F000`-`F0FF`. Within `F100`-`F1FF` only the identification identifiers above.

## Broadcast frames

29-bit identifiers. The low byte is the sender: `00` body computer, `01` engine, `02`
steering, `06` ABS.

| ID | Rate | Content | Basis |
|---|---|---|---|
| `0618A001` | 100 /s | Bytes 2-3: engine speed, big-endian, 1 rpm per bit. Byte 7: accelerator pedal. | Speed confirmed against DID `1000`. Pedal published. |
| `0A18A001` | 20 /s | Byte 3: coolant temperature, raw − 40 °C. | Tracks DID `1003`. Scaling published. |
| `0628A001` | 100 /s | Byte 4: throttle plate position, 4 to 7 counts at idle. | Published |
| `0210A006` | | Vehicle speed | Published |
| `0218A006` | | Four wheel speeds, 16 bits each | Published |
| `0220A006` | | Unknown | |
| `0030A002` | | Steering angle and rate | Published |
| `0A18A002` | | Steering status | Published |
| `0810A000` | | Brake switch | Published |
| `0A18A000` | | Ambient temperature, fuel level, doors | Published |

The published definitions are for the Fiat 500 on the same platform. Their bit offset for
engine speed is one byte later than what this car sends, so treat every published offset as a
starting point.

## ELM327 settings that matter

| Command | Why |
|---|---|
| `ATSP7` | ISO 15765-4, 29-bit, 500 kbps. Automatic search (`ATSP0`) never finds this ECU. |
| `ATCP18`, `ATSHDA10F1` | The 29-bit request ID, split as priority byte plus three bytes |
| `ATCRA18DAF110` | Receive only the engine's replies |
| `ATCAF0` | Formatting off. You write the ISO-TP length byte yourself. |
| `ATV1` | Variable data length. Without it the adapter pads to 8 bytes. |
| `ATFCSH`, `ATFCSD300000`, `ATFCSM1`, `ATCFC1` | The adapter sends a 3-byte flow control frame itself |
| `ATAT0`, `ATST64` | Fixed 400 ms wait. Use `ATST19` or `ATST28` for sweeps. |
| `ATCSM1`, `ATMA` | Silent monitoring for passive capture |
| `ATCF`, `ATCM` | Receive filter and mask, to capture one ID without overflowing the buffer |
