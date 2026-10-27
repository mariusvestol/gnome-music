# SPDX-License-Identifier: GPL-2.0-or-later WITH GStreamer-exception-2008
from gettext import gettext as _

from gi.repository import GObject, Gtk

from gnomemusic.widgets.songwidgetmenu import SongWidgetMenu
from gnomemusic.widgets.startoggle import StarToggle


class CurrentSongControls(Gtk.Box):
    """Star and song menu shared by the player bar and Now Playing row."""

    def __init__(self, application, position=Gtk.PositionType.BOTTOM):
        super().__init__(spacing=0, valign=Gtk.Align.CENTER)
        self._application = application
        self._player = application.props.player
        self._song = None
        self._star_binding = None
        self._menu = None
        self._menu_position = position
        self._star = StarToggle()
        self.append(self._star)
        self._menu_button = Gtk.MenuButton(
            icon_name='view-more-symbolic',
            tooltip_text=_('Song Options'))
        self._menu_button.add_css_class('flat')
        self.append(self._menu_button)
        self.connect('map', self._position_menu)
        self._player.connect('song-changed', self._update_song)
        self._player.connect('queue-changed', self._update_song)
        self._update_song()

    def _update_song(self, *args):
        song = self._player.props.current_song
        self.props.visible = song is not None
        if song is self._song:
            return
        if self._star_binding is not None:
            self._star_binding.unbind()
            self._star_binding = None
        if self._menu is not None:
            self._menu.popdown()
        self._song = song
        if song is None:
            self._menu_button.props.popover = None
            self._menu = None
            return
        self._star.props.visible = song.props.is_tracker
        self._star_binding = song.bind_property(
            'favorite', self._star, 'active',
            GObject.BindingFlags.BIDIRECTIONAL
            | GObject.BindingFlags.SYNC_CREATE)
        if self._menu is None:
            self._menu = SongWidgetMenu(
                self._application, None, song, current_song=True)
            self._menu_button.props.popover = self._menu
            self._position_menu()
        else:
            self._menu.props.coreobject = song

    def _position_menu(self, *args):
        # GTK's position notification needs the menu to belong to a window.
        if self._menu is not None and self.get_root() is not None:
            self._menu.props.position = self._menu_position

    def add_context_menu(self, widget):
        click = Gtk.GestureClick(button=3)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect('pressed', self._on_right_click)
        widget.add_controller(click)

    def _on_right_click(self, gesture, presses, x, y):
        if self._song is not None:
            self._menu_button.popup()
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)
