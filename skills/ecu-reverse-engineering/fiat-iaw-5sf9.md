# Reference: Fiat Grande Punto 1.4 8V, Marelli IAW 5SF9

Engine 350A1000, South African market, not EOBD compliant. Expect the same scheme on other
Fiat, Alfa Romeo and Lancia cars of the period with C-CAN diagnostics, but verify each point.

## Connection

```
ATZ  ATE0 ATL0 ATS0 ATH1
ATSP7  ATCP18  ATSHDA10F1  ATCRA18DAF110
ATCAF0  ATV1
ATFCSH18DA10F1  ATFCSD300000  ATFCSM1  ATCFC1
ATAT0  ATST64
```

Then send raw single frames: length byte, then the UDS request.

```
023E00      -> 18DAF110 02 7E 00
0322F196    -> ECU name, multi-frame
03190208    -> confirmed fault codes
```

- 29-bit CAN, 500 kbps, OBD pins 6 and 14. Request `18DA10F1`, reply `18DAF110`.
- The engine ECU ignores frames padded to 8 bytes. This is the reason generic tools fail.
- Standard OBD-II modes are not answered. KWP2000 `1A` is refused. K-line is not connected.
- Flow control must come from the adapter. The engine ECU does not wait for a host round trip.

## Modules

`10` engine, `28` ABS, `30` power steering, `40` body computer (holds the VIN).

## Engine ECU identifiers

| DID | Meaning | Scaling |
|---|---|---|
| `F187` | Part number | ASCII |
| `F192` | Hardware number | ASCII |
| `F194` | Software number | ASCII |
| `F196` | ECU name | ASCII |
| `1000` | Engine speed | raw / 4 rpm |
| `1003` | Coolant temperature | raw − 40 °C |
| `1004` | Battery voltage | raw / 10 V |
| `F40C` | Stub, always zero | |

Seen in a fault snapshot and worth sweeping next: `1812`, `1924`, `1937`, `6082`.

## Broadcast frames

| ID | Content |
|---|---|
| `0618A001` | Engine speed in bytes 2-3, 1 rpm per bit, 100 frames per second. The value itself updates about once per firing segment. |
| `0A18A001` | Coolant temperature in byte 3, raw − 40 °C |
| `0628A001` | Throttle plate position in byte 4 |

The low byte of the identifier is the sender: `00` body, `01` engine, `02` steering, `06` ABS.
