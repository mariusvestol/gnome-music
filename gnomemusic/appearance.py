# SPDX-License-Identifier: GPL-2.0-or-later WITH GStreamer-exception-2008
"""System appearance and persistent, per-appearance accent colors."""

from pathlib import Path

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from gnomemusic.signals import connect_weak

DEFAULT_ACCENT = '#0860f2'


def parse_accent(value):
    color = Gdk.RGBA()
    if not color.parse(value):
        color.parse(DEFAULT_ACCENT)
    color.alpha = 1.0
    return color


def color_hex(color):
    return '#' + ''.join(f'{round(c * 255):02x}' for c in (
        color.red, color.green, color.blue))


def luminance(color):
    channels = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4
                for c in (color.red, color.green, color.blue)]
    return sum(c * weight for c, weight in zip(
        channels, (.2126, .7152, .0722)))


def contrast(first, second):
    light, dark = sorted((luminance(first), luminance(second)), reverse=True)
    return (light + .05) / (dark + .05)


def foreground_for(background):
    return max((parse_accent('#ffffff'), parse_accent('#000000')),
               key=lambda color: contrast(color, background))


def text_accent(color, background):
    """Keep accent text readable without changing the chosen fill color."""
    target = foreground_for(background)
    for step in range(101):
        amount = step / 100
        result = Gdk.RGBA()
        for channel in ('red', 'green', 'blue'):
            start = getattr(color, channel)
            delta = getattr(target, channel) - start
            setattr(result, channel, start + delta * amount)
        result.alpha = 1.0
        if contrast(result, background) >= 4.5:
            return result
    return target


class Appearance:
    def __init__(self, settings, log):
        self._settings = settings
        self._manager = Adw.StyleManager.get_default()
        self._manager.set_color_scheme(Adw.ColorScheme.DEFAULT)
        self._display = Gdk.Display.get_default()
        self._dark_theme = None
        dark_path = Path(GLib.get_user_config_dir()) / 'gtk-4.0/gtk-dark.css'
        if dark_path.is_file():
            provider = Gtk.CssProvider()
            try:
                provider.load_from_path(str(dark_path))
                self._dark_theme = provider
            except GLib.Error as error:
                log.warning(f"Could not load the custom dark theme: {error}")

        self._accent = Gtk.CssProvider()
        self._accent_rules = Gio.resources_lookup_data(
            '/org/gnome/Music/accent.css', Gio.ResourceLookupFlags.NONE
        ).get_data().decode()
        Gtk.StyleContext.add_provider_for_display(
            self._display, self._accent, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
        self._handlers = [
            (self._manager, connect_weak(
                self._manager, 'notify::dark', self._update_theme)),
            (settings, connect_weak(
                settings, 'changed::accent-color-light', self._update_accent)),
            (settings, connect_weak(
                settings, 'changed::accent-color-dark', self._update_accent))]
        self._update_theme()

    def _update_theme(self, *args):
        # User gtk.css overrides libadwaita even in dark mode. Apply the
        # matching custom variant within Music, below our accent overrides.
        if self._dark_theme is not None:
            if self._manager.props.dark:
                Gtk.StyleContext.add_provider_for_display(
                    self._display, self._dark_theme,
                    Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
            else:
                Gtk.StyleContext.remove_provider_for_display(
                    self._display, self._dark_theme)
        self._update_accent()

    def _update_accent(self, *args):
        dark = self._manager.props.dark
        key = 'accent-color-dark' if dark else 'accent-color-light'
        color = parse_accent(self._settings.get_string(key))
        foreground = foreground_for(color)
        found, background = Gtk.Box().get_style_context().lookup_color(
            'window_bg_color')
        if not found:
            background = parse_accent('#242424' if dark else '#fafafa')
        text = text_accent(color, background)
        css = f"""
        @define-color accent_bg_color {color.to_string()};
        @define-color accent_fg_color {foreground.to_string()};
        @define-color accent_color {text.to_string()};
        @define-color theme_selected_bg_color @accent_bg_color;
        @define-color theme_selected_fg_color @accent_fg_color;
        @define-color selected_bg_color @accent_bg_color;
        @define-color selected_fg_color @accent_fg_color;
        """
        self._accent.load_from_data((css + self._accent_rules).encode())

    def close(self):
        for source, handler in self._handlers:
            if source.handler_is_connected(handler):
                source.disconnect(handler)
        self._handlers.clear()
        for provider in (self._accent, self._dark_theme):
            if provider is not None:
                Gtk.StyleContext.remove_provider_for_display(
                    self._display, provider)
