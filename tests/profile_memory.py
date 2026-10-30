"""Measure Music's RAM use with its indexed library on an isolated display.

Run ./run-local --build-only first. Uses temporary settings and does not play
music or modify playlists. MUSIC_TEST_ROOT can select a comparison checkout.
"""
import gc
import json
import os
from pathlib import Path
import sys

ROOT = Path(os.environ.get('MUSIC_TEST_ROOT', Path(__file__).resolve().parents[1]))
os.environ['GSETTINGS_SCHEMA_DIR'] = str(ROOT / '.local-build')
os.environ['GSETTINGS_BACKEND'] = 'memory'
sys.path.insert(0, str(ROOT))

import gi
gi.require_versions({'Gtk': '4.0', 'Adw': '1', 'Gst': '1.0'})
from gi.repository import Adw, Gio, GLib, Gst

Adw.init()
Gst.init(None)
Gio.resources_register(Gio.Resource.load(
    str(ROOT / '.local-build/org.gnome.Music.gresource')))

from gnomemusic.application import Application
from gnomemusic.coverpaintable import CoverPaintable
from gnomemusic.texturecache import TextureCache
from gnomemusic.widgets.songwidget import SongWidget


class MemoryBenchmark:
    def __init__(self):
        self.app = Application('org.gnome.Music.MemoryCheck', 'Memory check')
        self.app.props.settings.set_value(
            'window-size', GLib.Variant('ai', [1180, 800]))
        self.app.props.settings.set_boolean('window-maximized', False)
        self.errors = []
        self.rounds = 0
        self.app.connect_after('activate', self._activated)
        sys.excepthook = self._exception

    def _exception(self, *error):
        self.errors.append(str(error[1]))
        sys.__excepthook__(*error)

    def measure(self, phase):
        gc.collect()
        status = Path('/proc/self/status').read_text().splitlines()
        rss_kib = int(next(line.split()[1] for line in status
                          if line.startswith('VmRSS:')))
        covers = sum(isinstance(obj, CoverPaintable) for obj in gc.get_objects())
        textures = [texture for _, _, texture in TextureCache._textures.values()
                    if texture is not None]
        texture_bytes = sum(texture.get_width() * texture.get_height() * 4
                            for texture in textures)
        print(json.dumps({
            'phase': phase,
            'rss_mib': round(rss_kib / 1024, 1),
            'covers': covers,
            'cached_textures': len(textures),
            'texture_mib': round(texture_bytes / 1024**2, 1),
            'songs': self.app.props.coremodel.props.songs.get_n_items(),
        }), flush=True)

    def _activated(self, *args):
        GLib.timeout_add(5000, self._prepare)

    def _prepare(self):
        self.measure('library_ready')
        songs = list(self.app.props.coremodel.props.songs)[:24]
        if len(songs) < 13:
            self.errors.append('The benchmark needs at least 13 indexed songs')
            return self._finish(force=True)
        player = self.app.props.player
        for song in songs:
            player.enqueue(song)
        # Exercise Now Playing without playing audio or updating play counts.
        player.queue_songs()[0].props.state = SongWidget.State.PLAYING
        player.emit('song-changed')
        self.app.props.window._queue_split.props.show_sidebar = True
        GLib.timeout_add(2500, self._prepared)
        return False

    def _prepared(self):
        self.measure('queue_ready')
        GLib.timeout_add(100, self._edit)
        return False

    def _edit(self):
        for _ in range(4):
            self.app.props.player.move_queue_song(2, 12)
        self.rounds += 4
        if self.rounds % 20 == 0:
            self.measure(f'queue_edits_{self.rounds}')
        if self.rounds >= 80:
            GLib.timeout_add(1500, self._finish)
            return False
        return True

    def _finish(self, force=False):
        queue = TextureCache._async_queue
        if not force and (queue._async_pool or queue._async_active_pool):
            return True
        self.measure('end')
        print('ERRORS:', self.errors, flush=True)
        self.app.quit()
        return False

    def _timed_out(self):
        self.errors.append('Image loading did not finish within 50 seconds')
        return self._finish(force=True)

    def run(self):
        GLib.timeout_add_seconds(50, self._timed_out)
        self.app.run([])
        return bool(self.errors)


if __name__ == '__main__':
    sys.exit(MemoryBenchmark().run())
