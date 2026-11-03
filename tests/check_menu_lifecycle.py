"""Exercise real window/menu lifetimes with GTK criticals treated as fatal.

Run in a subprocess: a dangling GTK menu callback can terminate Python before
unittest can report an exception. Uses generated audio and silent output.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test_queue_audio import QueueAudioTests, spin
from gi.repository import Gtk

sys.excepthook = sys.__excepthook__

QueueAudioTests.setUpClass()
try:
    for present_first in (True, False, True):
        case = QueueAudioTests()
        case.setUp()
        toolbar, sidebar = case._current_controls()
        box = Gtk.Box()
        box.append(toolbar)
        box.append(sidebar)
        window = Gtk.Window(child=box, default_width=800, default_height=600)
        try:
            if present_first:
                window.present()
                spin(.1)
            case.start()
            if not present_first:
                window.present()
                spin(.1)
            for controls in (toolbar, sidebar):
                menu = controls._menu
                assert menu.get_root() is window
                assert menu.props.position == controls._menu_position
                # Every position notification must target a live section,
                # including when the menu has never been shown.
                for position in (Gtk.PositionType.BOTTOM,
                                 Gtk.PositionType.TOP,
                                 controls._menu_position):
                    menu.props.position = position
                controls._menu_button.popup()
                assert spin(1, menu.get_mapped)
                controls._menu_button.popdown()
            case.player.stop()
            case.app.props.coremodel.props.playlist.remove_all()
            assert toolbar._menu is None
            assert sidebar._menu is None
        finally:
            window.destroy()
            case.tearDown()
finally:
    QueueAudioTests.temp.cleanup()
print('Menu lifecycle passed')
