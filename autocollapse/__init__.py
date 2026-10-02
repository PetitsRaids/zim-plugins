# Copyright 2026 Zim Wiki plugin contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Collapse a Zim window to its top bars while the application is inactive."""

import logging

from gi.repository import GLib, Gtk

from zim.gui.mainwindow import MainWindowExtension
from zim.plugins import PluginClass


logger = logging.getLogger('zim.plugins.autocollapse')


class AutoCollapsePlugin(PluginClass):

	plugin_info = {
		'name': _('Auto Collapse on Focus Loss'),  # T: plugin name
		'description': _(
			'Hide the editor area when its window loses focus, leaving only '
			'the top controls visible.'
		),  # T: plugin description
		'author': 'Zim Wiki plugin contributors',
	}

	plugin_preferences = (
		('enabled', 'bool', _('Collapse when focus is lost'), True),
		('delay', 'int', _('Delay before collapsing (milliseconds)'), 250, (0, 5000)),
		(
			'ignore_child_windows',
			'bool',
			_('Do not collapse for Zim dialogs'),
			True,
		),
	)


class AutoCollapseMainWindowExtension(MainWindowExtension):

	def __init__(self, plugin, window):
		MainWindowExtension.__init__(self, plugin, window)
		self.preferences = plugin.preferences
		self._collapsed = False
		self._collapse_source = None
		self._resize_source = None
		self._restore_size = None
		self._restore_maximized = False
		self._central_no_show_all = False

		self.connectto(window, 'focus-out-event', self.on_focus_out_event)
		self.connectto(window, 'focus-in-event', self.on_focus_in_event)
		self.connectto(window, 'close', self.on_window_close)
		self.connectto(self.preferences, 'changed', self.on_preferences_changed)

	def on_focus_out_event(self, window, event):
		if self.preferences['enabled']:
			self._schedule_collapse()
		return False

	def on_focus_in_event(self, window, event):
		self._cancel_collapse()
		self.expand()
		return False

	def on_preferences_changed(self, preferences):
		if not preferences['enabled']:
			self._cancel_collapse()
			self.expand()

	def on_window_close(self, window):
		"""Prevent Zim from persisting the temporary collapsed geometry."""
		if not self._collapsed:
			return

		restore_size = self._restore_size
		restore_maximized = self._restore_maximized
		self.expand()
		if restore_size:
			window.uistate['windowsize'] = restore_size
		window.uistate['windowmaximized'] = restore_maximized
		if window.notebook.state.modified:
			window.notebook.state.write()

	def _schedule_collapse(self):
		self._cancel_collapse()
		delay = max(0, int(self.preferences['delay']))
		self._collapse_source = GLib.timeout_add(delay, self._collapse_if_inactive)

	def _cancel_collapse(self):
		if self._collapse_source is not None:
			GLib.source_remove(self._collapse_source)
			self._collapse_source = None

	def _cancel_resize(self):
		if self._resize_source is not None:
			GLib.source_remove(self._resize_source)
			self._resize_source = None

	def _collapse_if_inactive(self):
		self._collapse_source = None
		if self.window.is_active():
			return GLib.SOURCE_REMOVE
		if self.preferences['ignore_child_windows'] and self._has_active_child_window():
			return GLib.SOURCE_REMOVE
		self.collapse()
		return GLib.SOURCE_REMOVE

	def _has_active_child_window(self):
		"""Return True if an active transient window belongs to this window."""
		for candidate in Gtk.Window.list_toplevels():
			if candidate is self.window or not candidate.is_active():
				continue
			parent = candidate.get_transient_for()
			while parent is not None:
				if parent is self.window:
					return True
				parent = parent.get_transient_for()
		return False

	def collapse(self):
		if self._collapsed or self.window.isfullscreen:
			return

		central = self.window._zim_window_central_hbox
		self._restore_size = tuple(self.window.get_size())
		self._restore_maximized = bool(getattr(self.window, 'maximized', False))
		self._central_no_show_all = central.get_no_show_all()
		self._collapsed = True

		if self._restore_maximized:
			self.window.unmaximize()

		# The menu and tool bars are siblings of this container. Hiding it
		# removes the editor and all side panes without disturbing their state.
		central.set_no_show_all(True)
		central.hide()
		self._cancel_resize()
		self._resize_source = GLib.idle_add(self._resize_to_top_bars)

	def _resize_to_top_bars(self):
		self._resize_source = None
		if not self._collapsed:
			return GLib.SOURCE_REMOVE

		width = self._restore_size[0] if self._restore_size else self.window.get_size()[0]
		minimum, natural = self.window._zim_window_main.get_preferred_height()
		height = max(1, minimum, natural)
		logger.debug('Collapse editor window to %sx%s', width, height)
		self.window.resize(width, height)
		return GLib.SOURCE_REMOVE

	def expand(self):
		if not self._collapsed:
			return

		self._cancel_resize()
		central = self.window._zim_window_central_hbox
		central.set_no_show_all(self._central_no_show_all)
		central.show()
		self._collapsed = False

		if self._restore_size and not self._restore_maximized:
			self.window.resize(*self._restore_size)
		if self._restore_maximized:
			self.window.maximize()

		self._restore_size = None
		self._restore_maximized = False

	def teardown(self):
		self._cancel_collapse()
		self._cancel_resize()
		self.expand()
