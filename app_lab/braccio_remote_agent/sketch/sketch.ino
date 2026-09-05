#include <Arduino_RouterBridge.h>
#include "UnoQBraccioBridge.h"

// Exposes move_braccio(...) to the Linux side (python/main.py) over the App Lab
// Bridge; the Python server speaks the M/S TCP protocol on :8765.
void setup() {
  Bridge.begin();
  Bridge.provide("move_braccio", move_braccio);
  setupBraccioBridge();
  move_braccio(90.0f, 45.0f, 180.0f, 180.0f, 90.0f, 10.0f);  // rest pose
}

void loop() {
  delay(1000);
}
