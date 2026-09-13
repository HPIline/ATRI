# Power expansion candidate

The recommended hardware change is a **separate protected battery source** for
runtime reserve, feeding the 12 V bus through its own fuse and reverse-current
blocking ideal-diode path. Packs must not be wired directly in parallel and a
charger/BMS must be selected for the exact cell chemistry and series count.

The repository does not yet have a purchased secondary pack or an authoritative
mechanical drawing. Therefore the CAD candidate intentionally contains no
invented envelope, connector, hole pattern, or mass. The existing battery tray
and strap are the reusable interface once those documents exist.

The design is currently over the 2.45 kg hard limit, so adding a pack cannot be
declared compliant until an equal mass is removed. This file is a gated
mechanical/electrical proposal, not a release approval.

## Required before integration

1. Select a documented 3S pack and obtain its drawing, mass, connector and BMS
   limits.
2. Verify fuse, wire gauge, connector current and ideal-diode thermal rating.
3. Add the envelope to `profile.py`, then run CAD collision, mass, COM and
   thermal checks.

See `power_expansion.py` for the machine-readable candidate record.
