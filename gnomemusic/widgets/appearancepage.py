# SPDX-License-Identifier: GPL-2.0-or-later WITH GStreamer-exception-2008
from gettext import gettext as _

from gi.repository import Adw, Gtk

from gnomemusic.appearance import color_hex, parse_accent
from gnomemusic.signals import connect_weak


class AccentColorRow(Adw.ActionRow):
    def __init__(self, settings, key, title):
        super().__init__(title=title)
        self._settings = settings
        self._key = key
        dialog = Gtk.ColorDialog(
            title=_('Choose Accent Color'), with_alpha=False)
        self._button = Gtk.ColorDialogButton(
            dialog=dialog, valign=Gtk.Align.CENTER, tooltip_text=title)
        self.add_suffix(self._button)
        self._reset = Gtk.Button(
            icon_name='edit-undo-symbolic', valign=Gtk.Align.CENTER,
            tooltip_text=_('Reset to Blue'))
        self._reset.add_css_class('flat')
        connect_weak(self._reset, 'clicked', self._reset_color)
        self.add_suffix(self._reset)
        connect_weak(self._button, 'notify::rgba', self._color_changed)
        connect_weak(settings, 'changed::' + key, self._sync_color)
        self._updating = False
        self._sync_color()

    def _sync_color(self, *args):
        self._updating = True
        color = parse_accent(self._settings.get_string(self._key))
        self._button.props.rgba = color
        self.props.subtitle = color_hex(color).upper()
        self._reset.props.sensitive = (
            self._settings.get_user_value(self._key) is not None)
        self._updating = False

    def _color_changed(self, *args):
        if not self._updating:
            self._settings.set_string(
                self._key, color_hex(self._button.props.rgba))

    def _reset_color(self, *args):
        self._settings.reset(self._key)


class AppearancePage(Adw.PreferencesPage):
    def __init__(self, settings):
        super().__init__(
            title=_('Appearance'), name='appearance',
            icon_name='applications-graphics-symbolic')
        group = Adw.PreferencesGroup(
            title=_('Accent Color'),
            description=_(
                'Music follows your system appearance. Choose a color for '
                'each mode; changes are saved automatically.'))
        self.add(group)
        group.add(AccentColorRow(
            settings, 'accent-color-light', _('Light Mode')))
        group.add(AccentColorRow(
            settings, 'accent-color-dark', _('Dark Mode')))
