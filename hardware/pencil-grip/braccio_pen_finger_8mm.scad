/*
Braccio pen finger - 8 mm preset
The geometry lives in braccio_pen_finger.scad; this file picks the bore size.

    openscad -o braccio_pen_finger_8mm.stl braccio_pen_finger_8mm.scad
*/

use <braccio_pen_finger.scad>

braccio_pen_finger(pencil_d = 8.0);
