# SPDX-License-Identifier: GPL-2.0-or-later WITH GStreamer-exception-2008
from gettext import gettext as _

from gi.repository import Adw, Gio, GLib, Gtk


class SoundDialog(Adw.PreferencesDialog):
    PRESETS = {
        'Flat': [0] * 10,
        'Bass Boost': [6, 5, 4, 2, 0, 0, 0, 0, 0, 0],
        'Vocal': [-3, -2, -1, 1, 3, 4, 3, 1, 0, -1],
        'Warm': [3, 3, 2, 1, 0, 0, -1, -2, -2, -3],
        'Bright': [-2, -1, 0, 0, 0, 1, 2, 3, 4, 4]
    }

    def __init__(self, application):
        super().__init__(
            title=_('Sound'), content_width=620, content_height=660)
        self._settings = application.props.settings
        self._updating = True
        page = Adw.PreferencesPage()
        self.add(page)
        eq = Adw.PreferencesGroup(title=_('Equalizer'))
        page.add(eq)
        switch = Adw.SwitchRow(
            title=_('Equalizer'), subtitle=_('Shape the sound of your music'))
        self._settings.bind(
            'equalizer-enabled', switch, 'active',
            Gio.SettingsBindFlags.DEFAULT)
        eq.add(switch)
        names = [_('Custom')] + list(self.PRESETS)
        self._preset = Adw.ComboRow(
            title=_('Preset'), model=Gtk.StringList.new(names))
        self._preset.connect('notify::selected', self._preset_changed)
        eq.add(self._preset)

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                           margin_top=16, margin_bottom=12)
        self._settings.bind('equalizer-enabled', controls, 'sensitive',
                            Gio.SettingsBindFlags.GET)
        self._settings.bind('equalizer-enabled', self._preset, 'sensitive',
                            Gio.SettingsBindFlags.GET)
        bands = Gtk.Box(homogeneous=True, spacing=2)
        controls.append(bands)
        self._sliders = []
        values = self._settings.get_value('equalizer-bands').unpack()
        frequencies = ('29', '59', '119', '237', '474',
                       '947', '1.9k', '3.8k', '7.5k', '15k')
        for index, frequency in enumerate(frequencies):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.VERTICAL, -12, 12, .5)
            scale.props.inverted = True
            scale.props.draw_value = False
            scale.set_size_request(-1, 130)
            scale.set_value(values[index] if index < len(values) else 0)
            scale.set_tooltip_text(frequency + ' Hz')
            gain = Gtk.Label(label=f'{scale.get_value():+.1f}')
            gain.add_css_class('caption')
            scale.connect('value-changed', self._band_changed, gain)
            column.append(gain)
            column.append(scale)
            label = Gtk.Label(label=frequency)
            label.add_css_class('caption')
            label.add_css_class('dim-label')
            column.append(label)
            bands.append(column)
            self._sliders.append(scale)
        self._headroom = Gtk.Label()
        self._headroom.add_css_class('caption')
        self._headroom.add_css_class('dim-label')
        controls.append(self._headroom)
        eq.add(controls)
        self._update_headroom()

        crossfade = Adw.PreferencesGroup(
            title=_('Crossfade'), description=_(
                'Start the next song while the current song fades out.'))
        page.add(crossfade)
        self._fade_row = Adw.ActionRow(title=_('Overlap'))
        fade = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 12, 1)
        fade.set_size_request(210, -1)
        fade.props.valign = Gtk.Align.CENTER
        fade.props.draw_value = False
        fade.set_value(self._settings.get_double('crossfade-seconds'))
        self._fade_row.add_suffix(fade)
        fade.connect('value-changed', self._fade_changed)
        self._fade_row.props.activatable_widget = fade
        crossfade.add(self._fade_row)
        self._fade_changed(fade)
        for index, preset in enumerate(self.PRESETS.values(), 1):
            if values == preset:
                self._preset.props.selected = index
                break
        self._updating = False

    def _update_headroom(self):
        gain = self._settings.get_double('equalizer-preamp')
        self._headroom.props.label = _('Automatic headroom: %.1f dB') % gain

    def _save_bands(self):
        values = [slider.get_value() for slider in self._sliders]
        self._settings.set_double('equalizer-preamp', -max(0.0, *values))
        self._settings.set_value('equalizer-bands', GLib.Variant('ad', values))
        self._update_headroom()

    def _band_changed(self, slider, label):
        label.props.label = f'{slider.get_value():+.1f}'
        if not self._updating:
            self._updating = True
            self._preset.props.selected = 0
            self._updating = False
            self._save_bands()

    def _preset_changed(self, row, pspec):
        if self._updating or row.props.selected == 0:
            return
        values = list(self.PRESETS.values())[row.props.selected - 1]
        self._updating = True
        for slider, value in zip(self._sliders, values):
            slider.set_value(value)
        self._updating = False
        self._save_bands()

    def _fade_changed(self, slider):
        seconds = slider.get_value()
        self._settings.set_double('crossfade-seconds', seconds)
        self._fade_row.props.subtitle = (
            _('Off') if seconds == 0 else _('%g seconds') % seconds)
