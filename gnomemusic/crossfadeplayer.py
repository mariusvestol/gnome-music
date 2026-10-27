# SPDX-License-Identifier: GPL-2.0-or-later WITH GStreamer-exception-2008
"""Two playback decks with shared transport and optional overlapping fades."""
from gi.repository import GLib, GObject

from gnomemusic.gstplayer import GstPlayer, Playback


class CrossfadePlayer(GObject.GObject):
    __gsignals__ = {
        'about-to-finish': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'clock-tick': (GObject.SignalFlags.RUN_FIRST, None, (int,)),
        'eos': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'error': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'seek-finished': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'stream-start': (GObject.SignalFlags.RUN_FIRST, None, ()),
        'transition-cancelled': (GObject.SignalFlags.RUN_FIRST, None, ())
    }

    def __init__(self, application):
        super().__init__()
        self._settings = application.props.settings
        self._decks = [GstPlayer(application), GstPlayer(application)]
        self._active = self._decks[0]
        self._pending = None
        self._outgoing = None
        self._requesting = False
        self._requested = False
        self._fade_elapsed = 0.0
        self._fade_length = 0.0
        self._last_tick = GLib.get_monotonic_time()
        self._timer = 0
        self._paused = False
        self._pending_mode = None
        self._active_ended = False
        for deck in self._decks:
            for signal in ('about-to-finish', 'clock-tick', 'eos', 'error',
                           'seek-finished', 'stream-start'):
                deck.connect(signal, self._dispatch, signal)
            deck.connect('notify::state', self._notify_state)
            deck.connect('notify::duration', self._notify_duration)

    def _promote_pending(self):
        old = self._active
        mode = self._pending_mode
        self._active = self._pending
        self._pending = None
        self._pending_mode = None
        self._outgoing = (
            old if mode == 'fade' and not self._active_ended else None)
        self._active_ended = False
        self._fade_elapsed = 0.0
        self._last_tick = GLib.get_monotonic_time()
        self._requested = False
        if self._outgoing is None:
            old.props.state = Playback.STOPPED
            self._active.set_volume(1.0)
        self._active.props.state = (
            Playback.PAUSED if self._paused else Playback.PLAYING)
        self.notify('duration')
        self.notify('state')
        self.emit('stream-start')

    def _request_next(self, mode):
        if self._pending is not None or self._requested:
            return
        self._requested = True
        self._requesting = mode
        try:
            self.emit('about-to-finish')
        finally:
            self._requesting = False

    def _dispatch(self, deck, *args):
        signal = args[-1]
        values = args[:-1]
        if deck is self._pending:
            if signal == 'stream-start' and self._pending_mode == 'fade':
                self._promote_pending()
            elif signal in ('error', 'eos'):
                ended = self._active_ended
                self.cancel_transition()
                self._requested = True
                self.emit('transition-cancelled')
                if ended:
                    self.emit('eos')
            return
        if deck is not self._active:
            if signal in ('eos', 'error'):
                deck.props.state = Playback.STOPPED
                if deck is self._outgoing:
                    self._outgoing = None
                    self._active.set_volume(1.0)
            return
        if signal == 'eos':
            self._active_ended = True
            if self._pending is not None:
                if self._pending_mode == 'gapless':
                    self._promote_pending()
                return
        if signal == 'about-to-finish':
            if self._settings.get_double('crossfade-seconds') == 0:
                self._request_next('gapless')
        else:
            if signal == 'stream-start':
                self._requested = False
                self._active_ended = False
            self.emit(signal, *values)

    def _notify_state(self, deck, pspec):
        if deck is not self._active:
            return
        if deck.props.state == Playback.PLAYING and not self._timer:
            self._last_tick = GLib.get_monotonic_time()
            self._timer = GLib.timeout_add(40, self._update)
        self.notify('state')

    def _notify_duration(self, deck, pspec):
        if deck is self._active:
            self.notify('duration')

    def _update(self):
        now = GLib.get_monotonic_time()
        elapsed = (now - self._last_tick) / 1_000_000
        self._last_tick = now
        if self.props.state == Playback.STOPPED:
            self._timer = 0
            return GLib.SOURCE_REMOVE
        if self._paused or self.props.state != Playback.PLAYING:
            return GLib.SOURCE_CONTINUE
        if self._outgoing is not None:
            self._fade_elapsed += elapsed
            fraction = min(
                1.0, self._fade_elapsed / max(.04, self._fade_length))
            # Complementary gains avoid a combined volume spike at midpoint.
            self._outgoing.set_volume(1.0 - fraction)
            self._active.set_volume(fraction)
            if fraction >= 1:
                old = self._outgoing
                self._outgoing = None
                old.props.state = Playback.STOPPED
            return GLib.SOURCE_CONTINUE
        seconds = self._settings.get_double('crossfade-seconds')
        duration = self._active.props.duration
        position = self._active.props.position
        if (duration > 0 and position >= 0 and not self._requested
                and self._pending is None and duration - position > 0):
            remaining = duration - position
            if seconds > 0 and remaining <= min(seconds, duration / 2):
                self._fade_length = max(.04, remaining)
                self._request_next('fade')
            elif seconds == 0 and remaining <= 2.0:
                self._request_next('gapless')
        return GLib.SOURCE_CONTINUE

    def cancel_transition(self):
        pending, outgoing = self._pending, self._outgoing
        self._pending = self._outgoing = None
        for deck in (pending, outgoing):
            if deck is not None:
                deck.props.state = Playback.STOPPED
        self._active.set_volume(1.0)
        self._requested = False
        self._pending_mode = None

    @GObject.Property(type=int)
    def state(self):
        return self._active.props.state

    @state.setter  # type: ignore
    def state(self, value):
        if value in (Playback.STOPPED, Playback.LOADING):
            self.cancel_transition()
        self._paused = value == Playback.PAUSED
        self._active.props.state = value
        for deck in (self._outgoing, self._pending):
            if deck is not None:
                if (deck is self._pending
                        and self._pending_mode == 'gapless'):
                    deck.props.state = Playback.PAUSED
                else:
                    deck.props.state = value

    @GObject.Property(
        type=float, default=-1., flags=GObject.ParamFlags.READABLE)
    def duration(self):
        return self._active.props.duration

    @GObject.Property(type=float, flags=GObject.ParamFlags.READABLE)
    def position(self):
        return self._active.props.position

    @GObject.Property(type=str)
    def url(self):
        return self._active.props.url or ''

    @url.setter  # type: ignore
    def url(self, value):
        if self._requesting:
            self._pending = next(
                d for d in self._decks if d is not self._active)
            self._pending.props.state = Playback.STOPPED
            self._pending.set_volume(0.0)
            self._pending.props.url = value
            self._pending_mode = self._requesting
            self._pending.props.state = (
                Playback.PLAYING if self._requesting == 'fade'
                else Playback.PAUSED)
        else:
            self._active.props.url = value
            self._requested = False

    def seek(self, seconds):
        self.cancel_transition()
        self.emit('transition-cancelled')
        self._active.seek(seconds)
