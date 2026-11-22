# Test procedure: calibration reliability and accuracy

Covers the specifications from Table 2.5.1 and 2.5.3:

## Equipment

- Projector (team optics, or a consumer projector for the midterm demo)
- Camera, mounted rigidly beside the projection lens
- Curved test surface, 38 to 42 cm diameter, matte
- Laptop or ROCK 5B running `warpei`
- Tape measure, light meter or phone lux app

## Setup

1. Place the projector so the image centre hits the surface at the chosen distance (0.9 m or 1.2 m). Record that distance.
2. Mount the camera. Confirm it sees the whole projected image with margin on every side: press R in the app to show the raw pattern and check the preview.
3. Record the room lighting (lux at the surface, or "dark", "dim", "bright").
4. Confirm the config file: panel size, rotation, display offset, camera index.
5. If a camera lens calibration exists for this camera at this resolution, make sure `camera_file` points to it. Record whether one was used.

## Procedure

1. From `warpei/sbc`, run:

       python ../testing/scripts/run_trials.py run --config configs/<config>.json \
           --count 20 --surface curved --distance-cm 90 --lighting dim \
           --notes "<projector, camera, anything unusual>"

2. The script runs 20 calibrations back to back with a short pause between them and appends one row per run to `testing/results/calibration_trials_<date>.csv`.
3. Do not touch the projector, camera, or surface during the run.
4. Afterwards, summarise:

       python ../testing/scripts/run_trials.py summarize ../testing/results/calibration_trials_<date>.csv

5. Paste the summary block into the results log and commit the CSV.

## Pass criteria

- Every window of 5 consecutive runs has at least 3 with `passed = yes`.
- Every run with `passed = yes` has `reduction_percent >= 50`.
- Every run has `seconds < 180`.
- Grid detected on the first attempt in at least 90% of captures.

## Record

| Field | Value |
| --- | --- |
| Date, operator | |
| Projector, resolution | |
| Camera, resolution, lens calibration used | |
| Surface, throw distance | |
| Lighting | |
| Config file | |
| Results CSV | |
| Summary (paste) | |
| Pass / fail | |
