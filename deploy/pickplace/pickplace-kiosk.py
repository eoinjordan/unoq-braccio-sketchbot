#!/usr/bin/env python3
"""Full-screen view of the pick-and-place page without a browser.

The UNO Q image ships WebKitGTK and its Python bindings but no browser.
This opens one undecorated full-screen window on the page. It needs a
desktop session to draw in, like any other program.
"""
import sys

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2  # noqa: E402

url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:7110/?kiosk=1"
window = Gtk.Window(title="Sketchbot pick and place")
window.connect("destroy", Gtk.main_quit)
view = WebKit2.WebView()
view.get_settings().set_enable_developer_extras(False)
view.connect("context-menu", lambda *args: True)      # no right-click menu on a kiosk
view.load_uri(url)
window.add(view)
window.fullscreen()
window.show_all()
Gtk.main()
