"""Regression checks for artwork memory use and queue view lifetimes."""
import gc
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import weakref

from test_queue_audio import spin, CALLBACK_ERRORS
from gi.repository import GdkPixbuf, GObject, Gtk

from gnomemusic.coverpaintable import CoverPaintable
from gnomemusic.mediaartloader import MediaArtLoader
from gnomemusic.signals import connect_weak
from gnomemusic.texturecache import TextureCache
from gnomemusic.utils import ArtSize, DefaultIconType
from gnomemusic.widgets.queuepanel import QueuePanel


class Artwork(GObject.Object):
    thumbnail = GObject.Property(type=str, default='generic')
    title = GObject.Property(type=str, default='Test song')
    artist = GObject.Property(type=str, default='Test artist')
    favorite = GObject.Property(type=bool, default=False)
    is_tracker = GObject.Property(type=bool, default=False)


class QueuePlayer(GObject.Object):
    __gsignals__ = {
        'queue-changed': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'song-changed': (GObject.SignalFlags.RUN_FIRST, None, ())}
    current_song = GObject.Property(type=object)
    position = GObject.Property(type=int, default=0)

    def queue_songs(self):
        return self.songs


class MemoryTests(unittest.TestCase):
    def setUp(self):
        CALLBACK_ERRORS.clear()

    def tearDown(self):
        self.assertEqual(CALLBACK_ERRORS, [], str(CALLBACK_ERRORS))

    def test_removed_covers_and_images_are_released(self):
        host = Gtk.Box()
        song = Artwork()
        covers, images = [], []
        for _ in range(300):
            image = Gtk.Image()
            cover = CoverPaintable.new_for_image(
                image, ArtSize.SMALL, DefaultIconType.ALBUM)
            cover.props.coreobject = song
            host.append(image)
            covers.append(weakref.ref(cover))
            images.append(weakref.ref(image))
            host.remove(image)
            del cover, image
        gc.collect()
        self.assertEqual(sum(ref() is not None for ref in covers), 0)
        self.assertEqual(sum(ref() is not None for ref in images), 0)
        # No callbacks to discarded paintables should remain on the song.
        song.notify('thumbnail')

    def test_image_owns_cover_until_removed(self):
        host = Gtk.Box()
        image = Gtk.Image()
        cover = CoverPaintable.new_for_image(
            image, ArtSize.SMALL, DefaultIconType.ALBUM)
        reference = weakref.ref(cover)
        host.append(image)
        del image, cover
        gc.collect()
        self.assertIsNotNone(reference())
        self.assertIs(host.get_first_child().props.paintable, reference())
        host.remove(host.get_first_child())
        gc.collect()
        self.assertIsNone(reference())

    def test_weak_subscription_disconnects_when_view_is_gone(self):
        class View:
            def changed(self, *args):
                self.calls += 1
        song = Artwork()
        view = View()
        view.calls = 0
        handler = connect_weak(song, 'notify::thumbnail', view.changed)
        song.notify('thumbnail')
        self.assertEqual(view.calls, 1)
        reference = weakref.ref(view)
        del view
        gc.collect()
        self.assertIsNone(reference())
        self.assertFalse(song.handler_is_connected(handler))

    def _art_file(self, directory):
        path = Path(directory) / 'cover.png'
        pixbuf = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, False, 8, 1200, 800)
        pixbuf.fill(0x123456ff)
        pixbuf.savev(str(path), 'png', [], [])
        return path.as_uri()

    def test_large_art_is_decoded_to_display_size(self):
        with tempfile.TemporaryDirectory() as directory:
            loader = MediaArtLoader()
            textures = []
            loader.connect('finished', lambda obj, texture: textures.append(texture))
            loader.start(self._art_file(directory), 192)
            self.assertTrue(spin(4, lambda: bool(textures)))
            texture = textures[0]
            self.assertEqual((texture.get_width(), texture.get_height()), (192, 128))

    def test_corrupt_art_finishes_without_stalling_the_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'broken.png'
            path.write_bytes(b'not an image')
            loader = MediaArtLoader()
            textures = []
            loader.connect('finished', lambda obj, texture: textures.append(texture))
            with patch.object(MediaArtLoader, '_log') as log:
                loader.start(path.as_uri(), 192)
                self.assertTrue(spin(4, lambda: bool(textures)))
                log.warning.assert_called_once()
            self.assertEqual(textures, [None])

    def test_cache_evicts_by_bytes_and_releases_completed_loaders(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(TextureCache, '_textures', {}), \
                patch.object(TextureCache, '_MAX_CACHE_BYTES', 64 * 1024):
            uri = self._art_file(directory)
            cache = TextureCache()
            results = []
            cache.connect('texture', lambda obj, texture: results.append(texture))
            for index, size in enumerate((64, 96, 128)):
                cache.lookup(uri, size)
                loader_ref = weakref.ref(cache._art_loader)
                self.assertTrue(spin(4, lambda: len(results) > index))
                gc.collect()
                self.assertIsNone(cache._art_loader)
                self.assertIsNone(loader_ref())
                self.assertEqual(results[-1].get_width(), size)
                total = sum(t.get_width() * t.get_height() * 4
                            for _, _, t in cache._textures.values() if t)
                self.assertLessEqual(total, 64 * 1024)
            self.assertIsNone(cache._textures[(uri, 64)][2])
            self.assertIsNotNone(cache._textures[(uri, 128)][2])
            cache.lookup(uri, 128)
            self.assertEqual(len(results), 4)
            self.assertIsNone(cache._art_loader)

    def test_queue_refresh_preserves_unchanged_views(self):
        player = QueuePlayer()
        player.songs = [Artwork() for _ in range(6)]
        player.props.current_song = player.songs[0]
        app = SimpleNamespace(props=SimpleNamespace(
            player=player, coremodel=None, window=Mock()))
        panel = QueuePanel(app, app.props.window)
        current = panel._current_contents.get_first_child()
        first = panel._entries[0]
        last = panel._entries[4]
        changes = []
        panel._entries.connect('items-changed', lambda obj, *change: changes.append(change))
        player.emit('queue-changed')
        player.emit('song-changed')
        self.assertEqual(changes, [])
        self.assertIs(panel._current_contents.get_first_child(), current)
        player.songs[2], player.songs[3] = player.songs[3], player.songs[2]
        player.emit('queue-changed')
        self.assertEqual(changes, [(1, 2, 2)])
        self.assertIs(panel._entries[0], first)
        self.assertIs(panel._entries[4], last)
        self.assertEqual([e.song for e in panel._entries], player.songs[1:])
        player.songs = player.songs[:1]
        player.emit('queue-changed')
        self.assertEqual(panel._entries.get_n_items(), 0)
        self.assertIs(panel._current_contents.get_first_child(), current)
