# SPDX-License-Identifier: GPL-2.0-or-later WITH GStreamer-exception-2008
"""Signal connections that do not keep a discarded view alive."""

import weakref


def _disconnect(source_ref, handler_id):
    source = source_ref()
    if source is not None and source.handler_is_connected(handler_id):
        source.disconnect(handler_id)


def weak_callback(callback):
    """Wrap a bound method without retaining its instance."""
    method_ref = weakref.WeakMethod(callback)

    def dispatch(*args):
        method = method_ref()
        if method is not None:
            return method(*args)

    return dispatch


def connect_weak(source, signal, callback, *, after=False):
    """Connect a bound method without retaining its instance.

    Disconnect when the instance is collected. Keep a native weak reference
    to the source so the cleanup also works if its Python wrapper changes.
    """
    connect = source.connect_after if after else source.connect
    handler_id = connect(signal, weak_callback(callback))
    weakref.finalize(
        callback.__self__, _disconnect, source.weak_ref(), handler_id)
    return handler_id
