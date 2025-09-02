# HA-KNX-FAN-step-translataion
Solution to have steps configured in HA and supporting DTP 5.001

KNX Step ↔ Percent Bridge (YAML) — README

A tiny Home Assistant custom component that bridges step-based KNX controls (0…max\_step) with percent values (DPT 5.001). It translates both ways and adds a short anti-echo debounce to avoid loops.

1. Prerequisites
   • Home Assistant (recent version).
   • KNX integration already working.
   • Ability to edit files under /config (e.g., Studio Code Server or File Editor).
   • Two different KNX group addresses for each bridge: one for steps (0…max\_step) and one for percent (DPT 5.001 on the bus as a raw byte 0..255).

2. Installation
   • Create the folder: /config/custom\_components/knx\_step\_bridge/
   • Place two files there: **init**.py and manifest.json (use the versions you already have; this README does not include source code).
   • Restart Home Assistant Core after adding/updating these files.

3. KNX events configuration (tell the KNX integration to emit events for your two GAs)
   configuration.yaml (add or extend your existing knx: block):
   knx:

# your existing KNX config…

event:
\- address: "31/4/111"    # step\_address (0..max\_step)
type: "1byte\_unsigned"
\- address: "31/4/11"     # percent\_address (DPT 5.001 on the bus as raw 0..255)
type: "1byte\_unsigned"
Notes:
• Using type: "1byte\_unsigned" here ensures the KNX event payload is the raw bus byte (0..255). The bridge converts it internally to 0..100%.
• Use two different addresses; do not reuse the same GA for both step and percent.

4. Bridge configuration (define your bridges and optional debounce)
   configuration.yaml (top level):
   knx\_step\_bridge:
   debounce\_ms: 500
   bridges:

   * name: "Ventilation"
     step\_address: "31/4/111"     # real device GA for steps (0..max\_step)
     percent\_address: "31/4/11"   # virtual GA for percent (DPT 5.001)
     max\_step: 3
     Tips:
     • You can add multiple items under bridges: for multiple devices.
     • If you ever see echo loops or double actions, increase debounce\_ms (e.g., 800–1000).
     • Restart Home Assistant Core after editing YAML.

5. How it works (logic and mapping)
   • Step → Percent: percent = floor(step \* 100 / max\_step)
   • Percent (bus byte) → Percent (0..100): percent = round(raw\_byte / 255 \* 100)
   • Percent → Step: if percent <= 0 then step = 0 else step = ceil(percent \* max\_step / 100); clamp step to \[0, max\_step]
   • Threshold examples for max\_step = 3:
   – 0% → step 0
   – 1–33% → step 1
   – 34–66% → step 2
   – 67–100% → step 3
   This keeps percent-based controls in Home Assistant and step-based KNX devices perfectly in sync in both directions, while the short debounce prevents feedback loops.
