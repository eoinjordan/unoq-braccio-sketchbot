/*
Braccio Pencil / Pen Drawing Grip - 10 mm preset
===============================================
Thicker pens and markers. The geometry lives in
braccio_pencil_grip.scad; this file only picks the bore size.

    openscad -o braccio_pencil_grip_10mm.stl braccio_pencil_grip_10mm.scad
*/

use <braccio_pencil_grip.scad>

braccio_pencil_grip(pencil_d = 10.0);
