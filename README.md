# car-whisperer

Notes, tools and an agent skill from reverse engineering the diagnostic protocol of one
stubborn car: a **Fiat Grande Punto 1.4 8V** (engine 350A1000, South African market) with a
**Magneti Marelli IAW 5SF9** engine ECU, using a cheap **Veepeak OBDCheck BLE** (ELM327 clone)
from a Linux laptop.

Generic OBD apps get nothing from this car. The ECU is not EOBD compliant and ignores every
standard request. It does answer manufacturer diagnostics, but only under conditions that an
ELM327 does not meet by default.

## The finding in one paragraph

The engine ECU speaks **UDS (ISO 14229) over ISO 15765 on 29-bit CAN at 500 kbps**, request ID
`18DA10F1`, response ID `18DAF110`. It **ignores any request frame that is padded to 8 bytes**.
An ELM327 pads by default, so every app fails. Switch formatting off (`ATCAF0`), send the true
data length (`ATV1`), build the ISO-TP frames yourself and let the adapter send flow control,
and the ECU answers.

```
ATZ  ATE0 ATL0 ATS0 ATH1
ATSP7  ATCP18  ATSHDA10F1  ATCRA18DAF110
ATCAF0  ATV1                              no formatting, real DLC: frames are not padded
ATFCSH18DA10F1  ATFCSD300000  ATFCSM1  ATCFC1
023E00      ->  18DAF110 02 7E 00         TesterPresent
0322F196    ->  18DAF110 ...  "5SF9AG"    ReadDataByIdentifier, ECU name
031902FF    ->  every fault code with its status byte
```

## What is in here

| Path | What |
|---|---|
| [docs/reverse-engineering.md](docs/reverse-engineering.md) | The process, step by step, including the dead ends |
| [docs/protocol.md](docs/protocol.md) | Protocol, module addresses, data identifiers and CAN broadcast frames for this car |
| [docs/example-results.md](docs/example-results.md) | What comes out: identification, fault codes, live values, an idle-speed capture and its spectrum |
| [skills/ecu-reverse-engineering/](skills/ecu-reverse-engineering/SKILL.md) | An agent skill that teaches a coding agent to do this safely on another car |
| [carwhisperer/](carwhisperer) | Small Python library and CLI: BLE transport, read-only whitelist, unpadded UDS client |
| [examples/](examples) | Session logs from the car, and a raw engine-speed capture |

## This is not a general tool

It is a record of one car, one ECU calibration and one adapter. Addresses, identifiers and
scalings are documented with how each one was established, so you can judge what carries over.
Other Fiat, Alfa Romeo and Lancia models of the same era use the same addressing scheme, and
the method applies to any ECU that will not talk to a generic scanner.

## Safety

Everything here is read-only, and the code enforces it.
[`carwhisperer/safety.py`](carwhisperer/safety.py) is an allow-list. A request is sent only if
it is a known read service: OBD modes 01, 02, 03, 07, 09 and 0A, KWP2000 `1A` `18` `21`, UDS
`22` `19` `3E`, and the default or extended session. Clearing codes, writing data, actuator
tests, security access, ECU reset and programming sessions are refused before they reach the
Bluetooth link. Adapter commands that write its non-volatile memory are refused too.

Read-only still means transmitting on a vehicle bus. Do it parked, and prefer the passive
commands (`sniff`, `capture`), which put the adapter in silent mode. You use this at your own
risk.

## Using the CLI

```
uv venv && uv pip install -e ".[analysis]"      # or: pip install -e ".[analysis]"

python -m carwhisperer adapter                  # talk to the adapter only
python -m carwhisperer sniff                    # passive: list CAN identifiers on the bus
python -m carwhisperer scan                     # which module addresses answer TesterPresent
python -m carwhisperer ident                    # identification of the engine ECU
python -m carwhisperer dtc                      # fault codes with status, never cleared
python -m carwhisperer live                     # engine speed, coolant, battery voltage
python -m carwhisperer sweep --start 1000 --end 10FF
python -m carwhisperer watch --did-file dids.txt --out log.csv   # log a list of identifiers over time
python -m carwhisperer capture --out idle.json  # passive: record the engine-speed frame
python -m carwhisperer analyze examples/idle_rpm_frames.json --plots out/
```

The adapter is found by its advertised name, `VEEPEAK`. Use `--address` or the
`CARWHISPERER_ADDR` environment variable to pick a specific one. The ignition must be on.

The protocol was worked out with throwaway scripts, and this package is the cleaned-up
version of them. The offline tests pass (`python -m unittest discover -s tests`), and
`analyze` reproduces the published numbers from the example capture. Of the hardware commands,
`live`, `sweep` and `watch` have been run against the car since the clean-up. The others have
not, so treat the first run of each as a test.

## Sources

The addressing scheme and several broadcast-frame decodings were cross-checked against public
work. See the list at the end of [docs/reverse-engineering.md](docs/reverse-engineering.md).

## License

MIT
