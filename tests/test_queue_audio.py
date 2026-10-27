"""Integration checks using real GTK models and silent GStreamer output.

Run after ./run-local --build-only:
GSETTINGS_BACKEND=memory GSETTINGS_SCHEMA_DIR=$PWD/.local-build \
  /usr/bin/python3 -m unittest discover -s tests -v
"""
import logging
from array import array
import math
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
import wave

os.environ['GSETTINGS_BACKEND'] = 'memory'
os.environ.setdefault('GSETTINGS_SCHEMA_DIR', str(Path(__file__).resolve().parents[1] / '.local-build'))
import gi
gi.require_versions({'Gtk': '4.0', 'Adw': '1', 'Gst': '1.0', 'Grl': '0.3'})
from gi.repository import Adw, Gio, GLib, Grl, Gst, Gtk
Adw.init()
Gst.init(None)
Grl.init(None)
CALLBACK_ERRORS = []
sys.excepthook = lambda *error: CALLBACK_ERRORS.append(error)
Gio.resources_register(Gio.Resource.load(str(Path(os.environ['GSETTINGS_SCHEMA_DIR']) / 'org.gnome.Music.gresource')))
from gnomemusic.coresong import CoreSong
from gnomemusic.coremodel import CoreModel
from gnomemusic.search import Search
from gnomemusic.gstplayer import Playback
from gnomemusic.player import Player, RepeatMode
from gnomemusic.widgets.songwidget import SongWidget


def spin(seconds=0, until=None):
    deadline = time.monotonic() + seconds
    context = GLib.MainContext.default()
    while True:
        while context.pending():
            context.iteration(False)
        if until and until():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(.005)


class QueueAudioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.uri = []
        for index in range(3):
            path = Path(cls.temp.name) / f'{index}.wav'
            with wave.open(str(path), 'wb') as output:
                output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
                data = b''.join(struct.pack('<h', int(2000 * math.sin(2*math.pi*(220+index*220)*n/16000))) for n in range(48000))
                output.writeframes(data)
            cls.uri.append(path.as_uri())

    def setUp(self):
        CALLBACK_ERRORS.clear()
        settings = Gio.Settings.new('org.gnome.Music')
        for key in ('repeat', 'crossfade-seconds', 'equalizer-enabled', 'equalizer-bands', 'equalizer-preamp', 'replaygain'):
            settings.reset(key)
        store = Gio.ListStore.new(CoreSong)
        ordered = Gtk.SortListModel.new(store, None)
        recent = Gtk.SliceListModel.new(ordered, 0, 20)
        self.detached = 0
        def detach():
            self.detached += 1
        coremodel = SimpleNamespace(props=SimpleNamespace(playlist=store,
            playlist_sort=ordered, recent_playlist=recent, recent_playlist_size=10),
            detach_playback_queue=detach)
        self.app = SimpleNamespace(props=SimpleNamespace(
            settings=settings, coremodel=coremodel,
            coregrilo=SimpleNamespace(writeback_tracker=lambda *args: None),
            log=logging.getLogger('music-test')))
        self.player = Player(self.app)
        for deck in self.player._gst_player._decks:
            sink = Gst.ElementFactory.make('fakesink')
            sink.props.sync = True
            deck._player.props.audio_sink = sink
        self.songs = []
        for index, uri in enumerate(self.uri):
            media = Grl.Media.audio_new()
            media.set_id(str(index))
            media.set_source('test')
            media.set_url(uri)
            media.set_title(f'Song {index}')
            media.set_artist('Test artist')
            media.set_album('Test album')
            media.set_duration(3)
            song = CoreSong(self.app, media)
            song.props.validation = CoreSong.Validation.SUCCEEDED
            song.props.state = SongWidget.State.UNPLAYED
            self.songs.append(song)
        store.splice(0, 0, self.songs)

    def tearDown(self):
        self.player.stop()
        self.player._playlist._discoverer.stop()
        spin(.08)
        self.assertEqual(CALLBACK_ERRORS, [], str(CALLBACK_ERRORS))

    def start(self):
        self.player.play_queue_position(0)
        self.assertTrue(spin(2, lambda: self.player.props.state == Playback.PLAYING))

    def test_queue_order_duplicates_and_clear_do_not_interrupt(self):
        self.start()
        original = self.player.props.current_song
        duplicate = self.player.enqueue(self.songs[0], play_next=True)
        self.assertIs(self.player.queue_songs()[1], duplicate)
        self.assertIsNot(duplicate, original)
        self.player.move_queue_song(1, 3)
        self.assertIs(self.player.queue_songs()[3], duplicate)
        self.player.remove_queue_song(2)
        self.assertEqual(len(self.player.queue_songs()), 3)
        self.player.remove_queue_song(0)
        self.assertIs(self.player.props.current_song, original)
        self.player.clear_queue()
        self.assertEqual(len(self.player.queue_songs()), 1)
        self.assertEqual(self.player.props.state, Playback.PLAYING)
        self.assertFalse(self.player.props.has_next)
        self.assertGreater(self.detached, 0)

    def test_play_duplicate_selects_correct_occurrence(self):
        duplicate = self.player.enqueue(self.songs[0])
        duplicate.props.validation = CoreSong.Validation.SUCCEEDED
        self.player.play_queue_position(3)
        self.assertTrue(spin(2, lambda: self.player.props.state == Playback.PLAYING))
        self.assertEqual(self.player.props.position, 3)
        self.assertIs(self.player.props.current_song, duplicate)

    def test_shuffle_edit_preserves_current_song(self):
        self.start()
        current = self.player.props.current_song
        self.player.props.repeat_mode = RepeatMode.SHUFFLE
        self.player.enqueue(self.songs[1], play_next=True)
        self.assertIs(self.player.props.current_song, current)
        self.assertEqual(self.player.props.repeat_mode, RepeatMode.NONE)
        self.assertEqual(self.player.props.state, Playback.PLAYING)

    def test_equalizer_live_and_replaygain_independent(self):
        self.start()
        settings = self.app.props.settings
        settings.set_boolean('equalizer-enabled', True)
        settings.set_value('equalizer-bands', GLib.Variant('ad', [3.] * 10))
        settings.set_double('equalizer-preamp', -3.)
        spin(.1)
        for deck in self.player._gst_player._decks:
            self.assertEqual(deck._equalizer.get_property('band0'), 3.)
            self.assertAlmostEqual(deck._preamp.props.volume, 10 ** (-3/20), places=5)
        settings.set_boolean('replaygain', True)
        spin(.1)
        settings.set_boolean('replaygain', False)
        spin(.1)
        self.assertEqual(self.player._gst_player._active._equalizer.get_property('band0'), 3.)
        self.assertEqual(self.player.props.state, Playback.PLAYING)

    def test_replaygain_bypass_handles_new_gain_tags(self):
        deck = self.player._gst_player._active
        settings = self.app.props.settings
        self.assertFalse(deck._limiter.props.enabled)
        deck._rg_volume.set_property('fallback-gain', -6.)
        self.assertEqual(deck._rg_child.props.volume, 1.)
        settings.set_boolean('replaygain', True)
        spin(.05)
        self.assertAlmostEqual(deck._rg_child.props.volume, 10 ** (-6/20), places=5)
        self.assertTrue(deck._limiter.props.enabled)
        settings.set_boolean('replaygain', False)
        spin(.05)
        self.assertEqual(deck._rg_child.props.volume, 1.)
        deck._rg_volume.set_property('fallback-gain', -9.)
        self.assertEqual(deck._rg_child.props.volume, 1.)
        self.assertFalse(deck._limiter.props.enabled)

    def test_equalizer_changes_output_samples(self):
        long_path = Path(self.temp.name) / 'long.wav'
        with wave.open(str(Path(self.temp.name) / '0.wav'), 'rb') as original:
            params = original.getparams()
            data = original.readframes(original.getnframes())
        with wave.open(str(long_path), 'wb') as output:
            output.setparams(params)
            output.writeframes(data * 4)
        self.songs[0].props.media.set_url(long_path.as_uri())
        self.songs[0].props.url = long_path.as_uri()
        self.songs[0].props.duration = 12
        audio = self.player._gst_player
        sink = Gst.parse_bin_from_description(
            'audioconvert ! audio/x-raw,format=F32LE ! fakesink name=measure sync=true signal-handoffs=true', True)
        levels = []
        def measure(element, buffer, pad):
            samples = array('f', buffer.extract_dup(0, buffer.get_size()))
            if samples:
                levels.append(math.sqrt(sum(x*x for x in samples)/len(samples)))
        sink.get_by_name('measure').connect('handoff', measure)
        audio._active._player.props.audio_sink = sink
        self.start()
        spin(.3)
        baseline = sum(levels[-3:])/len(levels[-3:])
        settings = self.app.props.settings
        settings.set_boolean('equalizer-enabled', True)
        settings.set_value('equalizer-bands', GLib.Variant('ad', [0., 0., 0., 9., 0., 0., 0., 0., 0., 0.]))
        self.assertTrue(spin(3, lambda: levels[-1] > baseline * 1.5))
        settings.set_boolean('equalizer-enabled', False)
        self.assertTrue(spin(3, lambda: abs(levels[-1] - baseline) < baseline * .15))
        settings.set_boolean('replaygain', True)
        settings.set_boolean('equalizer-enabled', True)
        settings.set_value('equalizer-bands', GLib.Variant('ad', [0., 0., 0., -9., 0., 0., 0., 0., 0., 0.]))
        self.assertTrue(spin(3, lambda: levels[-1] < baseline * .75))

    def test_crossfade_overlaps_pause_and_seek(self):
        self.app.props.settings.set_double('crossfade-seconds', 1.2)
        self.start()
        audio = self.player._gst_player
        self.assertTrue(spin(3, lambda: audio._outgoing is not None))
        spin(.12)
        outgoing = audio._outgoing
        self.assertIsNotNone(outgoing)
        self.assertEqual(self.player.props.position, 1)
        self.assertGreater(audio._active._player.props.volume, 0)
        self.assertLess(outgoing._player.props.volume, 1)
        self.player.pause()
        spin(.15)
        self.assertEqual(audio._active.props.state, Playback.PAUSED)
        self.assertEqual(outgoing.props.state, Playback.PAUSED)
        volume = outgoing._player.props.volume
        spin(.15)
        self.assertAlmostEqual(outgoing._player.props.volume, volume)
        self.player.play()
        spin(.1)
        self.player.set_position(.3)
        spin(.1)
        self.assertIsNone(audio._outgoing)
        self.assertEqual(outgoing.props.state, Playback.STOPPED)
        self.assertEqual(audio._active._player.props.volume, 1.)
        self.assertEqual(self.player.props.position, 1)
        self.player.next()
        spin(.15)
        self.assertEqual(self.player.props.position, 2)

    def test_gapless_off_crossfade_advances_once(self):
        self.start()
        self.assertTrue(spin(4, lambda: self.player.props.position == 1))
        spin(.2)
        self.assertEqual(self.player.props.position, 1)
        self.assertEqual(self.player.props.state, Playback.PLAYING)

    def test_edit_queue_after_gapless_preload(self):
        self.start()
        self.assertTrue(spin(3, lambda: self.player._gapless_set))
        seen = []
        self.player.connect('song-changed', lambda *_: seen.append(self.player._gst_player.props.url))
        self.player.clear_queue()
        self.assertTrue(spin(4, lambda: self.player.props.state == Playback.STOPPED))
        self.assertEqual(seen, [])

    def test_play_next_replaces_preloaded_successor(self):
        self.start()
        self.assertTrue(spin(3, lambda: self.player._gapless_set))
        queued = self.player.enqueue(self.songs[2], play_next=True)
        self.assertTrue(spin(4, lambda: self.player.props.position == 1))
        self.assertIs(self.player.props.current_song, queued)
        self.assertEqual(self.player._gst_player.props.url, self.uri[2])

    def test_resume_keeps_preloaded_song_at_start(self):
        self.start()
        self.assertTrue(spin(3, lambda: self.player._gst_player._pending is not None))
        audio = self.player._gst_player
        pending = audio._pending
        self.player.pause()
        spin(.1)
        self.player.play()
        spin(.2)
        self.assertEqual(pending.props.state, Playback.PAUSED)
        self.assertLessEqual(pending.props.position, .01)
        self.player.previous()
        spin(.15)
        self.assertEqual(self.player.props.position, 0)
        self.assertEqual(self.player.props.state, Playback.PLAYING)
        self.assertLess(self.player.get_position(), .5)

    def test_queue_does_not_edit_source_playlist(self):
        from gnomemusic.player import PlayerPlaylist
        self.app.props.search = Search()
        coremodel = CoreModel(self.app)
        self.player.stop()
        self.player._playlist._discoverer.stop()
        self.app.props.coremodel = coremodel
        self.player = Player(self.app)
        source = Gio.ListStore.new(CoreSong)
        source.splice(0, 0, self.songs)
        coremodel._set_player_model(PlayerPlaylist.Type.PLAYLIST, source)
        self.player.move_queue_song(0, 2)
        self.player.remove_queue_song(1)
        self.assertEqual(list(source), self.songs)
        snapshot = [s.props.url for s in self.player.queue_songs()]
        source.remove(0)
        self.assertEqual([s.props.url for s in self.player.queue_songs()], snapshot)
        coremodel._set_player_model(PlayerPlaylist.Type.PLAYLIST, source)
        self.assertEqual(len(self.player.queue_songs()), 2)

    def test_end_of_queue_stops_without_replaying(self):
        self.start()
        self.player.clear_queue()
        self.assertTrue(spin(4, lambda: self.player.props.state == Playback.STOPPED))
        self.assertEqual(self.player.props.position, 0)

if __name__ == '__main__':
    unittest.main()
