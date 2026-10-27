# Copyright 2021 The GNOME Music developers
#
# GNOME Music is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# GNOME Music is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with GNOME Music; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# The GNOME Music authors hereby grant permission for non-GPL compatible
# GStreamer plugins to be used and distributed together with GStreamer
# and GNOME Music.  This permission is above and beyond the permissions
# granted by the GPL license by which GNOME Music is covered.  If you
# modify this code, you may extend this exception to your version of the
# code, but you are not obligated to do so.  If you do not wish to do so,
# delete this exception statement from your version.

from __future__ import annotations
from typing import Any, Optional, Union, cast
import typing

from gettext import gettext as _
from gi.repository import Gio, GLib, GObject, Gtk

from gnomemusic.grilowrappers.grltrackerplaylists import Playlist
from gnomemusic.songtoast import SongToast
from gnomemusic.widgets.playlistdialog import PlaylistDialog
from gnomemusic.widgets.songwidget import SongWidget
if typing.TYPE_CHECKING:
    from gnomemusic.application import Application
    from gnomemusic.corealbum import CoreAlbum
    from gnomemusic.coresong import CoreSong
    CoreObject = Union[CoreAlbum, CoreSong, Playlist]


@Gtk.Template(resource_path="/org/gnome/Music/ui/SongWidgetMenu.ui")
class SongWidgetMenu(Gtk.PopoverMenu):

    __gtype_name__ = "SongWidgetMenu"

    def __init__(
            self, application: Application,
            song_widget: Optional[Union[SongWidget, Gtk.ListItem]],
            coreobject: Optional[CoreObject], *,
            current_song: bool = False) -> None:
        """Actions for a song row or the currently playing song.

        :param Application application: The application object
        :param song_widget: Associated song row, or None for the player
        :param Union[CoreAlbum, CoreSong, Playlist] coreobject: The
            coreobject associated with the menu
        :param bool current_song: Omit Play, which replaces the playback queue
        """
        super().__init__()

        self._application = application
        self._coremodel = application.props.coremodel
        self._player = application.props.player
        self._window = application.props.window

        self._coreobject = coreobject
        self._coresong: CoreSong
        self._song_widget = song_widget
        self._favorite_handler = 0

        self._playlist_dialog: Optional[PlaylistDialog] = None

        action_group = Gio.SimpleActionGroup()
        self._favorite_action = Gio.SimpleAction.new_stateful(
            'favorite', None, GLib.Variant('b', False))
        self._favorite_action.connect('activate', self._toggle_favorite)
        action_group.add_action(self._favorite_action)
        action_entries = [
            ("play", self._play_song),
            ("play_next", self._play_next),
            ("enqueue", self._enqueue),
            ("go_album", self._go_album),
            ("add_playlist", self._add_to_playlist),
            ("open_location", self._open_location)
        ]
        if (isinstance(self._coreobject, Playlist)
                and not self._coreobject.props.is_smart):
            action_entries.append(
                ("remove_playlist", self._remove_from_playlist))

        for name, callback in action_entries:
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", callback)
            action_group.add_action(action)

        self.insert_action_group("songwidget", action_group)

        menu = Gio.Menu()
        playback = Gio.Menu()
        if not current_song:
            playback.append(_("Play"), 'songwidget.play')
        playback.append(_("Play Next"), 'songwidget.play_next')
        playback.append(_("Add to Queue"), 'songwidget.enqueue')
        menu.append_section(None, playback)
        library = Gio.Menu()
        library.append(_("Go to Album"), 'songwidget.go_album')
        library.append(_("Add to Playlist…"), 'songwidget.add_playlist')
        if (isinstance(self._coreobject, Playlist)
                and not self._coreobject.props.is_smart):
            library.append(
                _("Remove from Playlist"), 'songwidget.remove_playlist')
        menu.append_section(None, library)
        self._favorite_section = Gio.Menu()
        menu.append_section(None, self._favorite_section)
        self.props.menu_model = menu
        self.connect('map', self._watch_favorite)
        self.connect('unmap', self._unwatch_favorite)
        self.props.coreobject = coreobject

    def _sync_favorite(self, *args):
        starred = self._coresong.props.favorite
        self._favorite_action.set_enabled(self._coresong.props.is_tracker)
        self._favorite_action.set_state(GLib.Variant('b', starred))
        self._favorite_section.remove_all()
        self._favorite_section.append(
            _('Unstar') if starred else _('Star'), 'songwidget.favorite')

    def _watch_favorite(self, *args):
        if not self._favorite_handler:
            self._favorite_handler = self._coresong.connect(
                'notify::favorite', self._sync_favorite)
        self._sync_favorite()

    def _unwatch_favorite(self, *args):
        if self._favorite_handler:
            self._coresong.disconnect(self._favorite_handler)
            self._favorite_handler = 0

    def _toggle_favorite(self, action, param):
        self.popdown()
        self._coresong.props.favorite = not self._coresong.props.favorite
        self._sync_favorite()

    def _play_next(self, action, param):
        self.popdown()
        self._player.enqueue(self._coresong, play_next=True)
        self._window.show_toast(
            _("Playing next: %s") % self._coresong.props.title)

    def _enqueue(self, action, param):
        self.popdown()
        self._player.enqueue(self._coresong)
        self._window.show_toast(
            _("Added to queue: %s") % self._coresong.props.title)

    def _go_album(self, action, param):
        self.popdown()
        self._window.show_album(self._coresong)

    def _open_location(self, action: Gio.SimpleAction, param: Any) -> None:
        pass

    def _play_song(self, action: Gio.Simple, param: Any) -> None:
        self.popdown()
        signal_id = 0

        def _on_playlist_loaded(klass, playlist_type):
            self._player.play(self._coresong)
            self._coremodel.disconnect(signal_id)

        signal_id = self._coremodel.connect(
            "playlist-loaded", _on_playlist_loaded)
        self._coremodel.props.active_core_object = self._coreobject

    def _add_to_playlist(self, action: Gio.Simple, param: Any) -> None:
        self.popdown()
        self._playlist_dialog = PlaylistDialog(
            self._application, [self._coresong])
        self._playlist_dialog.present(self._window)

    def _remove_from_playlist(self, action: Gio.Simple, param: Any) -> None:
        if self._song_widget is None:
            return
        self.popdown()
        position = self._song_widget.get_index()
        SongToast(
            self._application, cast(Playlist, self._coreobject), position,
            self._coresong)

    @GObject.Property(type=GObject.GObject)
    def coreobject(self) -> CoreObject:
        return self._coreobject

    @coreobject.setter  # type: ignore
    def coreobject(self, coreobject: CoreObject) -> None:
        self._unwatch_favorite()
        self._coreobject = coreobject

        if isinstance(self._song_widget, SongWidget):
            self._coresong = self._song_widget.props.coresong
        else:
            self._coresong = coreobject
        self._sync_favorite()
        if self.get_mapped():
            self._watch_favorite()
