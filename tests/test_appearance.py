"""Integration checks for saved colors, live appearance and unified settings."""
import gc
import logging
import os
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
import weakref

from test_queue_audio import CALLBACK_ERRORS
from gi.repository import Adw, Gio, Gtk

from gnomemusic.appearance import (
    Appearance, DEFAULT_ACCENT, color_hex, contrast, foreground_for,
    parse_accent, text_accent)
from gnomemusic.widgets.appearancepage import AccentColorRow
from gnomemusic.widgets.preferencesdialog import PreferencesDialog


class AppearanceTests(unittest.TestCase):
    def setUp(self):
        CALLBACK_ERRORS.clear()
        self.settings = Gio.Settings.new('org.gnome.Music')
        for key in ('accent-color-light', 'accent-color-dark'):
            self.settings.reset(key)
        self.manager = Adw.StyleManager.get_default()
        self.previous_scheme = self.manager.props.color_scheme
        self.appearance = Appearance(self.settings, logging.getLogger('test'))
        self.widget = Gtk.Box()

    def tearDown(self):
        self.appearance.close()
        self.manager.props.color_scheme = self.previous_scheme
        self.assertEqual(CALLBACK_ERRORS, [], str(CALLBACK_ERRORS))

    def accent(self):
        found, color = self.widget.get_style_context().lookup_color('accent_bg_color')
        self.assertTrue(found)
        return color_hex(color)

    def test_each_mode_keeps_its_color_during_live_switches(self):
        self.settings.set_string('accent-color-light', '#007f61')
        self.settings.set_string('accent-color-dark', '#f4c04b')
        for _ in range(3):
            self.manager.props.color_scheme = Adw.ColorScheme.FORCE_LIGHT
            self.assertEqual(self.accent(), '#007f61')
            self.manager.props.color_scheme = Adw.ColorScheme.FORCE_DARK
            self.assertEqual(self.accent(), '#f4c04b')
        self.settings.set_string('accent-color-light', '#aa2266')
        self.assertEqual(self.accent(), '#f4c04b')
        self.manager.props.color_scheme = Adw.ColorScheme.FORCE_LIGHT
        self.assertEqual(self.accent(), '#aa2266')

    def test_picker_changes_and_reset_only_affect_one_mode(self):
        light = AccentColorRow(self.settings, 'accent-color-light', 'Light')
        dark = AccentColorRow(self.settings, 'accent-color-dark', 'Dark')
        light._button.props.rgba = parse_accent('#119977')
        dark._button.props.rgba = parse_accent('#ffdd55')
        self.assertEqual(self.settings.get_string('accent-color-light'), '#119977')
        self.assertEqual(self.settings.get_string('accent-color-dark'), '#ffdd55')
        self.assertEqual(dark.props.subtitle, '#FFDD55')
        dark._reset.emit('clicked')
        self.assertEqual(self.settings.get_string('accent-color-dark'), DEFAULT_ACCENT)
        self.assertEqual(self.settings.get_string('accent-color-light'), '#119977')
        self.assertFalse(dark._reset.props.sensitive)
        reference = weakref.ref(light)
        del light
        gc.collect()
        self.assertIsNone(reference())
        self.settings.reset('accent-color-light')

    def test_color_choices_survive_a_process_restart(self):
        code = '''
from gi.repository import Gio
settings = Gio.Settings.new('org.gnome.Music')
'''
        with tempfile.TemporaryDirectory() as config:
            env = dict(os.environ, GSETTINGS_BACKEND='keyfile', XDG_CONFIG_HOME=config)
            write = code + '''
settings.set_string('accent-color-light', '#123abc')
settings.set_string('accent-color-dark', '#fedcba')
Gio.Settings.sync()
'''
            read = code + '''
assert settings.get_string('accent-color-light') == '#123abc'
assert settings.get_string('accent-color-dark') == '#fedcba'
'''
            for script in (write, read):
                result = subprocess.run([sys.executable, '-c', script], env=env,
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_extreme_colors_keep_text_readable(self):
        for value in ('#ffffff', '#000000', '#ffff00', '#0860f2', '#a855f7'):
            color = parse_accent(value)
            self.assertGreaterEqual(contrast(color, foreground_for(color)), 4.5)
            for bg in ('#333333', '#f5f5f5'):
                background = parse_accent(bg)
                text = text_accent(color, background)
                self.assertGreaterEqual(contrast(text, background), 4.5)

    def test_invalid_stored_color_falls_back_to_blue(self):
        self.manager.props.color_scheme = Adw.ColorScheme.FORCE_LIGHT
        self.settings.set_string('accent-color-light', 'bad color; } * { color: red;')
        self.assertEqual(self.accent(), DEFAULT_ACCENT)

    def test_unified_settings_preserve_audio_and_playback_controls(self):
        self.settings.set_double('crossfade-seconds', 7)
        self.settings.set_boolean('equalizer-enabled', True)
        app = SimpleNamespace(props=SimpleNamespace(settings=self.settings))
        dialog = PreferencesDialog(app)
        self.assertEqual(dialog.get_visible_page_name(), 'appearance')
        row = AccentColorRow(self.settings, 'accent-color-dark', 'Dark')
        row._button.props.rgba = parse_accent('#ff8800')
        dialog.set_visible_page_name('sound')
        sound = dialog.get_visible_page()
        sound._preset.props.selected = 2  # Bass Boost
        self.assertEqual(self.settings.get_value('equalizer-bands').unpack(),
                         [6, 5, 4, 2, 0, 0, 0, 0, 0, 0])
        self.assertEqual(self.settings.get_double('equalizer-preamp'), -6)
        self.assertEqual(self.settings.get_double('crossfade-seconds'), 7)
        dialog.set_visible_page_name('playback')
        dialog._replay_gain_row.props.active = True
        self.assertTrue(self.settings.get_boolean('replaygain'))
        dialog._repeatmode_row.props.selected = 2
        self.assertEqual(self.settings.get_enum('repeat'), 2)
        self.assertEqual(self.settings.get_string('accent-color-dark'), '#ff8800')
