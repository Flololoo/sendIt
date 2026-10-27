# Notes

## Convention (task 1.2)
Found on clip 0051: quaternion order `wxyz`, the quaternion maps camera to world, and the accelerometer reads the direction of gravity (so the world axis is z-down). The camera's x axis looks forward, y is down in the portrait mount, z is sideways. Mean error against the 2 s low-passed accelerometer: 0.5° on the committed fixture (5 s), 6.5° over the whole clip (the accelerometer is noisy in curves).

## Sign (task 2.4)
Pinned by watching frames of clip 0051 (horizon and trees tilt):
- 116.9 s: right-hand curve, lean +25°
- 422.4 s: left-hand curve, lean −25°
- 46 s to 57 s: straight road, |lean| ≤ 2.3°

Positive lean correlates with positive heading rate (r = 0.78), which fits the z-down world.

## End-to-end export (task 4.1)
Exported 0051, 300 to 330 s, `lean`, social preset, mount `bike` (the camera sits on the bike's handlebar in this footage). Frames checked:
- 300.5 s: L 1° on a gentle bend
- 304 s: L 21° while the horizon is tilted into the left-hand curve, and "max L 21°" shows
- 306 s: R 6°
- 315 s: R 2° on a straight, with max L 21° kept
- 329 s: L 10°

Needle direction matches the curves, straights read near 0, and the maxima build up. Not checked: helmet-mounted footage, which the clips do not contain.
