# send.it.slowly video tools

Python tools for the send.it.slowly motorcycle channel. The first module reads the
per-frame telemetry (orientation, acceleration, exposure) and the recording metadata
that DJI Osmo Action cameras embed in their MP4/LRF files.

## Setup (Windows)

1. **Python 3.12.** Check with `py -3.12 --version`. Install from python.org or
   `winget install Python.Python.3.12` if it is missing.

2. **FFmpeg and ffprobe on PATH.**

   ```powershell
   winget install Gyan.FFmpeg
   ```

   Open a new terminal afterwards, then check both tools:

   ```powershell
   ffmpeg -version
   ffprobe -version
   ```

3. **Create a virtual environment and install the project in editable mode with the dev extras:**

   ```powershell
   cd C:\Users\flo12\projects\sendItSlowlyVideos
   py -3.12 -m venv .venv
   .venv\Scripts\activate
   python -m pip install -e ".[dev]"
   ```

4. **Run the tests.** The tests use small committed fixtures, so they do not need the video files:

   ```powershell
   python -m pytest
   ```

   The integration test that reads the real clips in `videos\` is skipped when that folder is empty.

## Video workspace

A local web app for browsing clips, setting up overlays and exporting. It runs on this machine only (127.0.0.1:8765).

1. **Install** as in Setup above (`pip install -e ".[dev]"` also installs the web dependencies).
2. **Start it** from the project folder with the virtual environment active:

   ```powershell
   python -m app
   ```

   It prints `http://127.0.0.1:8765/` and opens it in your browser. Use `--no-browser` to skip that. Stop it with Ctrl+C.
3. **Add clips.**
   - **Add from folder** (prefilled with `videos\`) references the files where they are. Nothing is copied, so the 10 to 13 GB clips cost no extra disk space. A matching `.LRF` next to a clip is used as its fast preview. Use this for anything already on this machine.
   - **Drop or choose files** uploads copies into `data\media\`. Use it for files coming from an SD card or another computer, and drop the MP4 together with its LRF. Removing an uploaded clip deletes the copy. Removing a referenced clip never touches the original.
4. **Configure.** Open a clip, pick the camera mount (helmet or bike), switch on overlays and set position, size and settings. Changes save automatically and the preview shows them when you pause or seek. Set in and out points to export only a range. A new clip starts from the settings you used last.
5. **Export.** Choose `original` or `social` (1080x1920) and press Export. Progress and the time left show in the job list, and finished files can be played or downloaded there.

Where things go:

- `exports\` - finished videos
- `data\library.db` - the library and each clip's saved settings
- `data\jobs.json` - export job history
- `data\media\` - uploaded copies
- `data\cache\` - telemetry cache, thumbnails and generated previews (clips without an LRF get a 720p preview)

At least one overlay has to be enabled to export.

## G-meter & bumps

The `gmeter` overlay shows the forces of riding, derived from the camera's accelerometer and orientation (gravity removed).

- **Meter:** a circle with rings at 0.5 g and 1.0 g. The dot shows horizontal g relative to the direction of travel: up = accelerating, down = braking, right/left = cornering. A 1 s trail follows the dot, values beyond 1.2 g sit at the edge, and the total is printed below ("0.4 g").
- **Bumps:** short vertical hits are called out as "BUMP 1.4 g" (visible 1 s, then a 0.5 s fade), with an optional counter "Bumps: N" for the exported range.
- **Sensitivity:** `low` (1.2 g), `medium` (0.8 g) and `high` (0.5 g) set the vertical peak needed for a bump. Higher levels always include every bump of the lower ones. Events less than 1 s apart count as one.
- **Settings:** `show_meter`, `show_bumps`, `show_bump_count`, `sensitivity`. At least one of meter and bumps must be on. With the meter off, only the call-out and counter are drawn.
- **Helmet vs bike:** the travel direction is estimated from the camera heading and smoothed more strongly on a helmet (2.5 s, 45�/s cap) so glances do not swing the meter. The rider's body absorbs bumps, so on a helmet bumps read lower: use `high` there.
- **Accuracy:** lateral g follows tan(lean) closely but reads about 25% lower, because of smoothing and tyre width.

## Telemetry command line

Print a clip's metadata and sample count, and optionally write every sample to CSV:

```powershell
python -m app.telemetry videos\DJI_20261026155823_0051_D.MP4
python -m app.telemetry videos\DJI_20261026155823_0051_D.MP4 --csv telemetry_0051.csv
```

The first run decodes the clip (a few seconds) and stores the result in `data\cache\`.
Later runs load from the cache. The cache is refreshed when the file's size or
modification time changes. Use `--no-cache` to bypass it.

To regenerate the test fixtures from a clip (only needed if the fixture format changes):

```powershell
python scripts\make_fixture.py videos\DJI_20261026155823_0051_D.MP4
```

## Export command line

Render a range of a clip with overlays burned in. The export runs through the same job queue the app uses:

```powershell
python -m app.render export videos\DJI_20261026155823_0051_D.MP4 --overlay timestamp --start 300 --end 330 --preset social
```

`--preset` is `original` (source resolution) or `social` (1080x1920 for portrait clips). Outputs go to `exports\`, and the job history is kept in `data\jobs.json`. The command exits with 1 and prints the reason if the export fails.

## Export performance

Measured on this machine (RTX 4070 Ti, FFmpeg 8.1 full build) with a 30 s range of clip 0051 (300 to 330 s) and the test timestamp overlay. The wall-clock time includes Python start-up.

| Preset   | Output size | Encoder     | Wall-clock |
|----------|-------------|-------------|-----------|
| original | 2160x3840   | hevc_nvenc  | 37.3 s    |
| social   | 1080x1920   | hevc_nvenc  | 27.4 s    |

The social preset finishes well under the 3-minute target. The encoder is chosen by probing at start-up, in the order `hevc_nvenc`, `h264_nvenc`, `libx264`. The timestamp overlay is cheap to draw, so real overlays may add time in the overlay pass.

## Layout

- `app/telemetry/` - telemetry extraction (decoder, metadata, cache, CSV export)
- `app/overlays/` - overlay contract, registry, layout and layer rendering
- `app/workspace/` and `app/web/` - the library, settings storage and web app (`app/web/static/` is the plain HTML/JS frontend, no build step)
- `app/render/` - preview, export pipeline, encoder choice and the export job queue
- `tests/` - unit tests and `tests/fixtures/` (cut from clip 0051)
- `scripts/make_fixture.py` - regenerates the test fixtures from a clip
- `data/cache/` - decoded telemetry cache (git-ignored, created on demand)
- `videos/` - source clips (git-ignored, not part of the repo)

## Lean angle

The `lean` overlay shows how far you lean, as a gauge with "L 18°" or "R 23°" and, optionally, the largest left and right lean so far in the exported range.

It is computed from the camera's orientation (the sensor-fused quaternion), not from the accelerometer, which is too noisy. The roll around the camera's viewing direction is measured against an upright reference that is found automatically from stretches of straight riding, so the mounting angle (including the portrait mount) does not show up as lean. The value is smoothed without time lag, and limited to ±65°.

- **Mount:** set it per clip. `bike` smooths lightly (0.25 s). `helmet` smooths more (0.8 s) to reduce head movements, but it still follows head tilt, not the bike. Riders keep their heads more level than the bike, so helmet mode usually reads lower than the true lean.
- **Offset field:** use it only if the gauge does not read 0° on a straight road you know is level, for example when the whole clip is a long curve and the automatic reference is off. Type a value from −15 to 15 in 0.5° steps; it adds to every value.
- **Long curves:** the camera's fusion may lean slightly toward apparent gravity in a long sweeper, so the angle can read a little low there.
