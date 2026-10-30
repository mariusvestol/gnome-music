# Copyright 2022 The GNOME Music developers
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
from typing import Optional

from gi.repository import Gdk, GdkPixbuf, Gio, GLib, GObject

from gnomemusic.musiclogger import MusicLogger


class MediaArtLoader(GObject.GObject):
    """Handles retrieval of MediaArt cache art

    Signals when the media is loaded and passes a texture or None.
    """

    __gtype_name__ = "MediaArtLoader"

    __gsignals__ = {
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (object, ))
    }

    # Default for callers without a widget size; views request device pixels.
    _MAX_TEXTURE_SIZE = 512
    _log = MusicLogger()

    def __init__(self) -> None:
        """Intialize MediaArtLoader
        """
        super().__init__()

        self._texture: Optional[Gdk.Texture] = None

    def start(self, uri: str, size: int = _MAX_TEXTURE_SIZE) -> None:
        """Start the cache query

        :param str uri: The MediaArt uri
        :param int size: Maximum width and height in device pixels
        """
        self._size = size
        thumb_file = Gio.File.new_for_uri(uri)
        if thumb_file:
            thumb_file.read_async(
                GLib.PRIORITY_DEFAULT_IDLE, None, self._open_stream)
        else:
            self.emit("finished", self._texture)

    def _open_stream(
            self, thumb_file: Gio.File, result: Gio.AsyncResult) -> None:
        try:
            stream = thumb_file.read_finish(result)
        except GLib.Error as error:
            self._log.warning(
                "Error: {}, {}".format(error.domain, error.message))
            self.emit("finished", self._texture)
        else:
            GdkPixbuf.Pixbuf.new_from_stream_at_scale_async(
                stream, self._size, self._size,
                True, None, self._on_pixbuf_loaded, stream)

    def _on_pixbuf_loaded(
            self, source: Optional[GObject.Object], result: Gio.AsyncResult,
            stream: Gio.FileInputStream) -> None:
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream_finish(result)
            self._texture = Gdk.Texture.new_for_pixbuf(pixbuf)
        except GLib.Error as error:
            self._log.warning(
                "Error: {}, {}".format(error.domain, error.message))
        stream.close_async(
            GLib.PRIORITY_DEFAULT_IDLE, None, self._close_stream)

    def _close_stream(
            self, stream: Gio.InputStream, result: Gio.AsyncResult) -> None:
        try:
            stream.close_finish(result)
        except GLib.Error as error:
            self._log.warning(
                "Error: {}, {}".format(error.domain, error.message))

        self.emit("finished", self._texture)
