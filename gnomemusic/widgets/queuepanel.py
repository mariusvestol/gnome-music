# SPDX-License-Identifier: GPL-2.0-or-later WITH GStreamer-exception-2008
from gettext import gettext as _

from gi.repository import Adw, Gdk, Gio, GObject, Gtk, Pango

from gnomemusic.coverpaintable import CoverPaintable
from gnomemusic.utils import ArtSize, DefaultIconType
from gnomemusic.widgets.playlistdialog import PlaylistDialog


class QueueEntry(GObject.GObject):
    def __init__(self, song):
        super().__init__()
        self.song = song


class QueuePanel(Gtk.Box):
    """A temporary, editable playback queue, independent of saved playlists."""

    def __init__(self, application, window):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._app = application
        self._window = window
        self._player = application.props.player
        self._entries = Gio.ListStore.new(QueueEntry)
        self.add_css_class('queue-panel')

        header = Adw.HeaderBar(show_start_title_buttons=False,
                               show_end_title_buttons=False)
        header.props.title_widget = Adw.WindowTitle(title=_('Up Next'))
        close = Gtk.Button(icon_name='window-close-symbolic',
                           tooltip_text=_('Close Queue'))
        close.connect('clicked', lambda *_: window.toggle_queue())
        header.pack_end(close)
        self.append(header)

        self._current_box = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=8, margin_start=18, margin_end=18,
            margin_top=10, margin_bottom=18)
        self._now_label = Gtk.Label(label=_('Now Playing'), xalign=0)
        self._now_label.add_css_class('heading')
        self._current_box.append(self._now_label)
        self._current = Gtk.Box(spacing=12)
        self._current_box.append(self._current)
        self.append(self._current_box)

        heading = Gtk.Box(margin_start=18, margin_end=12, margin_bottom=8)
        self._count = Gtk.Label(xalign=0, hexpand=True)
        self._count.add_css_class('dim-label')
        heading.append(self._count)
        self._clear = Gtk.Button(
            label=_('Clear'), tooltip_text=_('Clear Upcoming Songs'))
        self._clear.add_css_class('flat')
        self._clear.connect('clicked', lambda *_: self._player.clear_queue())
        heading.append(self._clear)
        self.append(heading)

        self._stack = Gtk.Stack(vexpand=True)
        empty = Adw.StatusPage(
            icon_name='view-list-symbolic', title=_('Your Queue Is Empty'),
            description=_('Right-click a song to play it next '
                          'or add it to the queue.'))
        empty.add_css_class('compact')
        self._stack.add_named(empty, 'empty')
        factory = Gtk.SignalListItemFactory()
        factory.connect('setup', self._setup_row)
        factory.connect('bind', self._bind_row)
        factory.connect('unbind', self._unbind_row)
        self._list = Gtk.ListView(model=Gtk.NoSelection.new(self._entries),
                                  factory=factory, single_click_activate=False)
        self._list.add_css_class('navigation-sidebar')
        self._list.connect('activate', self._activate)
        scrolled = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            vexpand=True, child=self._list)
        self._stack.add_named(scrolled, 'queue')
        self.append(self._stack)
        self._player.connect('queue-changed', self._refresh)
        self._player.connect('song-changed', self._refresh)
        self._refresh()

    def _song_contents(self, song):
        box = Gtk.Box(spacing=10, hexpand=True)
        cover = Gtk.Image(pixel_size=40)
        cover.set_size_request(40, 40)
        paintable = CoverPaintable(self, ArtSize.SMALL, DefaultIconType.ALBUM)
        paintable.props.coreobject = song
        cover.props.paintable = paintable
        box.append(cover)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                         valign=Gtk.Align.CENTER, hexpand=True, spacing=3)
        title = Gtk.Label(
            label=song.props.title, xalign=0,
            ellipsize=Pango.EllipsizeMode.END, max_width_chars=22)
        title.add_css_class('heading')
        artist = Gtk.Label(
            label=song.props.artist, xalign=0,
            ellipsize=Pango.EllipsizeMode.END, max_width_chars=22)
        artist.add_css_class('dim-label')
        artist.add_css_class('caption')
        labels.append(title)
        labels.append(artist)
        box.append(labels)
        return box

    def _position(self, entry):
        return next((i for i, song in enumerate(self._player.queue_songs())
                     if song is entry.song), -1)

    def _activate(self, widget, index):
        self._player.play_queue_position(self._position(self._entries[index]))

    def _setup_row(self, factory, item):
        row = Gtk.Box(spacing=4, margin_start=6, margin_end=6,
                      margin_top=6, margin_bottom=6)
        item.props.child = row
        drag = Gtk.DragSource(actions=Gdk.DragAction.MOVE)
        drag.connect('prepare', lambda *_: Gdk.ContentProvider.new_for_value(
            item.props.item) if item.props.item else None)
        row.add_controller(drag)
        drop = Gtk.DropTarget.new(QueueEntry, Gdk.DragAction.MOVE)
        drop.connect('drop', self._drop, item)
        row.add_controller(drop)
        click = Gtk.GestureClick(button=3)
        click.connect('pressed', self._right_click, item)
        row.add_controller(click)

    def _bind_row(self, factory, item):
        entry = item.props.item
        row = item.props.child
        handle = Gtk.Image(icon_name='list-drag-handle-symbolic')
        handle.add_css_class('dim-label')
        row.append(handle)
        row.append(self._song_contents(entry.song))
        button = Gtk.MenuButton(icon_name='view-more-symbolic',
                                valign=Gtk.Align.CENTER,
                                tooltip_text=_('Song Options'))
        button.add_css_class('flat')
        menu = Gio.Menu()
        actions = Gio.SimpleActionGroup()
        commands = [
            ('play', _('Play Now'), lambda: self._player.play_queue_position(
                self._position(entry))),
            ('up', _('Move Up'), lambda: self._move(entry, -1)),
            ('down', _('Move Down'), lambda: self._move(entry, 1)),
            ('album', _('Go to Album'),
             lambda: self._window.show_album(entry.song)),
            ('playlist', _('Add to Playlist…'),
             lambda: self._add_playlist(entry.song)),
            ('remove', _('Remove from Queue'),
             lambda: self._player.remove_queue_song(self._position(entry)))
        ]
        for name, label, callback in commands:
            menu.append(label, 'queue.' + name)
            action = Gio.SimpleAction.new(name, None)
            action.connect('activate', lambda a, p, fn=callback: fn())
            actions.add_action(action)
        row.insert_action_group('queue', actions)
        button.props.menu_model = menu
        row.append(button)
        item._queue_menu = button

    def _unbind_row(self, factory, item):
        row = item.props.child
        while row.get_first_child() is not None:
            row.remove(row.get_first_child())
        row.insert_action_group('queue', None)
        item._queue_menu = None

    def _right_click(self, gesture, presses, x, y, item):
        if item.props.item and item._queue_menu:
            item._queue_menu.popup()
            gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _drop(self, target, source, x, y, item):
        if not item.props.item:
            return False
        self._player.move_queue_song(
            self._position(source), self._position(item.props.item))
        return True

    def _move(self, entry, delta):
        position = self._position(entry)
        self._player.move_queue_song(position, position + delta)

    def _add_playlist(self, song):
        self._dialog = PlaylistDialog(self._app, [song])
        self._dialog.present(self._window)

    def _refresh(self, *args):
        current = self._player.props.current_song
        while self._current.get_first_child() is not None:
            self._current.remove(self._current.get_first_child())
        self._current_box.props.visible = current is not None
        if current is not None:
            self._current.append(self._song_contents(current))
        first = self._player.props.position + 1 if current else 0
        upcoming = self._player.queue_songs()[first:]
        self._entries.splice(0, self._entries.get_n_items(),
                             [QueueEntry(song) for song in upcoming])
        self._count.props.label = _('%d songs upcoming') % len(upcoming)
        self._clear.props.sensitive = bool(upcoming)
        self._stack.set_visible_child_name('queue' if upcoming else 'empty')
