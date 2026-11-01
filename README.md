# induction-motor-predictive-maintenance
Machine learning-based predictive maintenance and RUL estimation framework for three-phase induction motors


## Background Health Index publisher (Render)

The Health Index publisher runs independently of dashboard visits. It reads the
latest sensor sample from the sensor ThingSpeak channel, calculates the weighted
Health Index using `health_index.py`, and writes the result to a **separate**
ThingSpeak output channel.

### ThingSpeak channel layout

**Sensor input channel**
- Field 1: Temperature (°C)
- Field 2: Vibration (mm/s RMS)
- Field 3: Current (A)
- Field 4: RPM

**HI output channel**
- Field 4: Source sensor entry ID (traceability)
- Field 5: Health Index (%)
- Field 6: Status code (1 = GOOD, 2 = MODERATE, 3 = BAD)

Create the HI output channel in ThingSpeak and enable at least Fields 4, 5,
and 6. Keep its Write API Key private.

### Deploy the worker on Render

Create a separate **Background Worker** from this repository and select branch
`feature/weighted-health-index` while testing this pull request.

- Build command: `pip install -r requirements.txt`
- Start command: `python hi_worker.py`

Set these environment variables on the worker:

| Variable | Value |
| --- | --- |
| `THINGSPEAK_CHANNEL_ID` | Sensor input channel ID |
| `THINGSPEAK_READ_KEY` | Sensor channel Read API Key (leave blank for a public channel) |
| `THINGSPEAK_HI_CHANNEL_ID` | Separate HI output channel ID |
| `THINGSPEAK_HI_WRITE_KEY` | HI output channel Write API Key |
| `HI_WORKER_POLL_SECONDS` | Optional polling interval; defaults to 20 seconds |
| `SENSOR_MAX_AGE_SECONDS` | Optional freshness limit; defaults to 300 seconds |

The worker skips stale sensor samples and checks the latest HI output entry's
Field 4 to avoid publishing the same source sample repeatedly. ThingSpeak may
reject writes that violate the channel's update interval; rejected writes are
logged and retried on a later poll.

### ESP32 integration

The ESP32 can read the latest HI output feed and use Field 5 for the displayed
HI and Field 6 for the status indicator. Validate that the feed is recent and
that both fields are present before treating the value as current. A missing,
stale, or invalid HI reading must be treated as a communication fault, not as
a valid low-HI reading.

**Safety:** This worker only calculates and publishes a monitoring value. It
does not control motor power. Test the ESP32 decision logic using simulated
values and an indicator/low-voltage prototype only. Any real three-phase motor
power-control equipment and protective interlocks must be selected, installed,
and verified by a qualified electrician/engineer; the software cutoff must
never replace overload protection or an emergency-stop system.
