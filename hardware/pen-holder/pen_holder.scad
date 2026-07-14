// =============================================================================
// Braccio Sketchbot — spring-loaded pen holder
// =============================================================================
// A pen holder for the TinkerKit Braccio robotic arm. The stock gripper clamps
// this holder (no arm disassembly needed); a spring-loaded piston gives the
// drawing tool ~6 mm of vertical compliance so small Z-calibration errors keep
// a light, constant contact pressure on the paper instead of lifting the tool
// or snapping a pencil lead.
//
// Works with a hex pencil OR a Sharpie marker. A Sharpie is recommended for
// live/booth use: consistent barrel size, globally available, and it won't run
// short like a sharpened pencil. Pick one with the `tool` variable below.
//
// Reference: https://docs.arduino.cc/retired/getting-started-guides/Braccio/
//
// PARTS (set `part` below, or render each in the OpenSCAD GUI):
//   "assembly" – both parts shown together (visual check only, do not print)
//   "body"     – outer shell that the Braccio gripper grips           (print 1)
//   "piston"   – sliding tool clamp                                   (print 1)
//   "rigid"    – one-piece holder, no spring (fallback if you have no spring)
//
// HARDWARE:
//   1 x compression spring, ~6 mm OD, ~16 mm free length
//       (a standard ballpoint-pen spring works well)
//   1 x zip tie (2.5 mm) OR M3x10 screw + nut to close the tool clamp
// =============================================================================

part = "assembly";  // "assembly" | "body" | "piston" | "rigid"

// Drawing tool preset. Sets the clamp bore to the barrel diameter.
tool = "sharpie";   // "pencil" | "sharpie" | "sharpie_ultra"

$fn = 96;

// ---- Drawing tool ----------------------------------------------------------
// Barrel diameters (mm), measured across the widest gripped part of the barrel.
// Add clamp_slop so the C-clamp can grip firmly when squeezed shut.
tool_dia =
    tool == "sharpie"       ? 12.0 :  // Sharpie Fine Point barrel (~11.9 mm)
    tool == "sharpie_ultra" ? 11.0 :  // Sharpie Ultra Fine barrel (~10.7 mm)
                               7.8;   // hex pencil across the corners

pencil_dia      = tool_dia;  // clamp bore diameter
clamp_len       = (tool == "pencil") ? 26 : 34;  // longer grip for a marker
clamp_wall      = 3.0;   // wall thickness around the tool
clamp_slot      = 1.6;   // width of the split so the clamp can squeeze closed

// ---- Gripper interface -----------------------------------------------------
// The Braccio fingers close onto the two flats of the body. The capture groove
// stops the holder sliding out of the jaws. Tune grip_width to how far your
// gripper closes (measure the gap when M6 ~= 90 deg).
grip_width      = 16;    // distance between the two gripped flats (mm)
grip_height     = 30;    // vertical length of the gripped section
grip_depth      = 22;    // front-to-back size of the body
groove_depth    = 1.6;   // depth of the finger-capture groove on each flat
groove_height   = 6;     // height of that groove

// ---- Spring / piston -------------------------------------------------------
spring_od       = 6.4;   // spring outer diameter + clearance
spring_free     = 16;    // spring free length (a ballpoint-pen spring)
travel          = 6;     // available compliant travel of the pencil
piston_clear    = 0.35;  // sliding clearance between piston shoulder and bore
wall            = 2.4;   // general wall thickness
shoulder_h      = 13;    // length of the sliding bearing (keeps pen square)
cap             = 3;     // solid ceiling the spring pushes against

// Derived -------------------------------------------------------------------
piston_od       = spring_od + 2 * wall;         // sliding shoulder diameter
bore_dia        = piston_od + 2 * piston_clear; // bore in the body
shaft_dia       = spring_od - 2.0;              // shaft the spring sits around
body_h          = shoulder_h + spring_free + cap; // total body height
ceiling_z       = body_h - cap;                 // underside of the ceiling
rest_shoulder_top = ceiling_z - spring_free;    // shoulder top at rest
cx              = grip_depth/2 - 3;             // bore centre (y) in the block
tab_w           = 4;                            // anti-rotation / retention tab
tab_slot_w      = tab_w + 0.6;

// ---------------------------------------------------------------------------
// Body: gripped block with a vertical bore, a spring ceiling and a slot
// ---------------------------------------------------------------------------
module body() {
    difference() {
        // Main gripped block (rounded for print + comfort).
        hull() {
            for (s = [-1, 1])
                translate([s * (grip_width/2 - 3), 0, 0])
                    cylinder(h = body_h, r = 3);
            for (s = [-1, 1])
                translate([s * (grip_width/2 - 3), grip_depth - 6, 0])
                    cylinder(h = body_h, r = 3);
        }
        // Central bore: piston shoulder + spring chamber, blind under a ceiling.
        translate([0, cx, -1])
            cylinder(h = ceiling_z + 1, d = bore_dia);
        // Small vent hole through the ceiling so the piston isn't air-locked.
        translate([0, cx, ceiling_z - 0.1])
            cylinder(h = cap + 0.2, d = 2);

        // Finger-capture grooves on each gripped flat.
        for (s = [-1, 1])
            translate([s * grip_width/2, cx, body_h/2])
                rotate([90, 0, 0])
                    translate([0, 0, -grip_depth])
                        cube([groove_height, groove_depth * 2, grip_depth * 2],
                             center = true);

        // Retention slot for the piston tab (limits travel, stops rotation).
        hull() {
            translate([bore_dia/2 - 0.3, cx, 2])
                cube([groove_depth * 2 + 1, tab_slot_w, 0.1], center = true);
            translate([bore_dia/2 - 0.3, cx, 2 + travel])
                cube([groove_depth * 2 + 1, tab_slot_w, 0.1], center = true);
        }
    }
}

// ---------------------------------------------------------------------------
// Piston: slides in the body, clamps the pencil, seats the spring.
// The pencil bore is BLIND so the piston top is a solid spring seat.
// ---------------------------------------------------------------------------
module piston() {
    // Blind bore stays inside the wide clamp so the shoulder/top remain a
    // solid spring seat (works even when a Sharpie barrel is wider than it).
    pencil_bore_depth = clamp_len - 2;
    difference() {
        union() {
            // Split clamp (bottom).
            translate([0, 0, -clamp_len])
                cylinder(h = clamp_len + 0.1, d = pencil_dia + 2 * clamp_wall);
            // Sliding shoulder (bearing + solid spring seat on top).
            cylinder(h = shoulder_h, d = piston_od);
            // Shaft that keeps the spring centred.
            translate([0, 0, shoulder_h])
                cylinder(h = spring_free - 1, d = shaft_dia);
            // Retention / anti-rotation tab.
            translate([piston_od/2 - 0.4, 0, 2.5])
                cube([groove_depth * 2, tab_w, 3], center = true);
        }
        // Blind pencil bore from the bottom.
        translate([0, 0, -clamp_len - 1])
            cylinder(h = pencil_bore_depth + 1, d = pencil_dia);
        // Clamp split: single slot from the bore out one side (C-clamp).
        translate([0, -clamp_slot/2, -clamp_len - 1])
            cube([pencil_dia/2 + clamp_wall + 1, clamp_slot, clamp_len + 0.9]);
        // Zip-tie / screw channel to squeeze the clamp closed.
        translate([0, 0, -clamp_len/2])
            rotate([90, 0, 0])
                cylinder(h = pencil_dia + 2 * clamp_wall + 8, d = 3.4, center = true);
    }
}

// ---------------------------------------------------------------------------
// Rigid fallback: one piece, no spring (use only if you have no spring)
// ---------------------------------------------------------------------------
module rigid() {
    difference() {
        union() {
            hull() {
                for (s = [-1, 1])
                    translate([s * (grip_width/2 - 3), 0, 0])
                        cylinder(h = grip_height, r = 3);
                for (s = [-1, 1])
                    translate([s * (grip_width/2 - 3), grip_depth - 6, 0])
                        cylinder(h = grip_height, r = 3);
            }
            translate([0, grip_depth/2 - 3, -clamp_len])
                cylinder(h = clamp_len, d = pencil_dia + 2 * clamp_wall);
        }
        translate([0, grip_depth/2 - 3, -clamp_len - 1])
            cylinder(h = grip_height + clamp_len + 2, d = pencil_dia);
        // Clamp split: single slot from the bore out one side (C-clamp).
        translate([0, grip_depth/2 - 3 - clamp_slot/2, -clamp_len - 1])
            cube([pencil_dia/2 + clamp_wall + 1, clamp_slot, clamp_len + 0.9]);
        // Finger grooves.
        for (s = [-1, 1])
            translate([s * grip_width/2, grip_depth/2 - 3, grip_height/2])
                rotate([90, 0, 0])
                    translate([0, 0, -grip_depth])
                        cube([groove_height, groove_depth * 2, grip_depth * 2], center = true);
        // Zip-tie channel.
        translate([0, grip_depth/2 - 3, -clamp_len/2])
            rotate([90, 0, 0])
                cylinder(h = pencil_dia + 2 * clamp_wall + 8, d = 3.4, center = true);
    }
}

// ---------------------------------------------------------------------------
// Render selector
// ---------------------------------------------------------------------------
if (part == "body")        body();
else if (part == "piston") piston();
else if (part == "rigid")  rigid();
else {
    // assembly preview
    color("SteelBlue")  body();
    color("Tomato")
        translate([0, grip_depth/2 - 3, travel])
            piston();
}
