/*
Braccio pen finger - 10 mm preset
The geometry lives in braccio_pen_finger.scad; this file picks the bore size.

    openscad -o braccio_pen_finger_10mm.stl braccio_pen_finger_10mm.scad
*/

use <braccio_pen_finger.scad>

braccio_pen_finger(pencil_d = 10.0);
