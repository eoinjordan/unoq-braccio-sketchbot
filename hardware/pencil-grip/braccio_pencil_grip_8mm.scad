/*
Braccio Pencil / Pen Drawing Grip - 8 mm preset
==============================================
Common 7-8 mm wooden pencils. The geometry lives in
braccio_pencil_grip.scad; this file only picks the bore size.

    openscad -o braccio_pencil_grip_8mm.stl braccio_pencil_grip_8mm.scad
*/

use <braccio_pencil_grip.scad>

braccio_pencil_grip(pencil_d = 8.0);
