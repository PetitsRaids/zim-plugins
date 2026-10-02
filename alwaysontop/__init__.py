# Copyright 2026 Zim Wiki plugin contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Keep each Zim main window above normal desktop windows."""

import logging

from gi.repository import GLib

from zim.gui.mainwindow import MainWindowExtension
from zim.plugins import PluginClass


logger = logging.getLogger('zim.plugins.alwaysontop')


class AlwaysOnTopPlugin(PluginClass):

	plugin_info = {
		'name': _('Always on Top'),  # T: plugin name
		'description': _(
			'Keep Zim editor windows above other normal windows.'
		),  # T: plugin description
		'author': 'Zim Wiki plugin contributors',
	}

	plugin_preferences = (
		('enabled', 'bool', _('Keep editor windows on top'), True),
	)


class AlwaysOnTopMainWindowExtension(MainWindowExtension):

	def __init__(self, plugin, window):
		MainWindowExtension.__init__(self, plugin, window)
		self.preferences = plugin.preferences
		self._reapply_source = None
		self.connectto(self.preferences, 'changed', self.on_preferences_changed)
		self.connectto(window, 'realize', self.on_window_realize)
		self.connectto(window, 'map-event', self.on_window_map_event)
		self.connectto(window, 'focus-in-event', self.on_window_focus_in_event)
		self._apply_preference()
		if window.get_mapped():
			self._schedule_reapply()

	def _apply_preference(self):
		enabled = bool(self.preferences['enabled'])
		logger.debug('Set always-on-top to %s', enabled)
		self.window.set_keep_above(enabled)

	def on_preferences_changed(self, preferences):
		self._cancel_reapply()
		self._apply_preference()

	def on_window_realize(self, window):
		# At application startup the extension is created before Gtk has a
		# native window. Reapply after realization, and once more after map.
		self._schedule_reapply()

	def on_window_map_event(self, window, event):
		self._schedule_reapply()
		return False

	def on_window_focus_in_event(self, window, event):
		# Some window managers can drop the hint while a window is hidden,
		# minimized, or moved between desktops.
		if self.preferences['enabled']:
			self._schedule_reapply()
		return False

	def _schedule_reapply(self):
		self._cancel_reapply()
		self._reapply_source = GLib.idle_add(self._apply_on_idle)

	def _apply_on_idle(self):
		self._reapply_source = None
		self._apply_preference()
		return GLib.SOURCE_REMOVE

	def _cancel_reapply(self):
		if self._reapply_source is not None:
			GLib.source_remove(self._reapply_source)
			self._reapply_source = None

	def teardown(self):
		# Do not leave a window modified when the plugin is disabled at runtime.
		self._cancel_reapply()
		self.window.set_keep_above(False)
