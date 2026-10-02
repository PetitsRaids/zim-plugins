# Copyright 2026 Zim Wiki plugin contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 2 of the License, or
# (at your option) any later version.

"""Synchronize Zim's built-in light/dark theme with the operating system."""

import ctypes
import logging
import os
import subprocess
import sys
import threading

from gi.repository import Gio, GLib, Gtk

from zim.config import ConfigManager
from zim.plugins import PluginClass


logger = logging.getLogger('zim.plugins.systemtheme')

CF_NOTIFICATION_CALLBACK = ctypes.CFUNCTYPE(
	None,
	ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
	ctypes.c_void_p, ctypes.c_void_p,
)


def dark_from_apple_interface_style(value):
	return str(value or '').strip().casefold() == 'dark'


def dark_from_windows_apps_use_light_theme(value):
	return int(value) == 0


def dark_from_color_scheme(value):
	return str(value or '').strip().casefold() == 'prefer-dark'


def dark_from_theme_name(value):
	return 'dark' in str(value or '').casefold()


class GtkThemeListener:
	"""Fallback for desktops that expose theme changes through GTK itself."""

	def __init__(self, callback):
		self.callback = callback
		self.settings = Gtk.Settings.get_default()
		self.handler_id = None

	def detect(self):
		return dark_from_theme_name(self.settings.get_property('gtk-theme-name'))

	def start(self):
		self.handler_id = self.settings.connect(
			'notify::gtk-theme-name', self._on_theme_changed
		)

	def _on_theme_changed(self, settings, param_spec):
		self.callback(self.detect())

	def stop(self):
		if self.handler_id is not None:
			self.settings.disconnect(self.handler_id)
			self.handler_id = None


class LinuxThemeListener:
	"""Listen for GNOME color-scheme changes, with a GTK fallback."""

	SCHEMA = 'org.gnome.desktop.interface'
	KEY = 'color-scheme'
	GNOME_DESKTOPS = ('gnome', 'ubuntu', 'unity', 'pantheon', 'pop')

	def __init__(self, callback):
		self.callback = callback
		self.settings = None
		self.handler_id = None
		self.fallback = None

		desktop = ':'.join((
			os.environ.get('XDG_CURRENT_DESKTOP', ''),
			os.environ.get('DESKTOP_SESSION', ''),
		)).casefold()
		if any(name in desktop for name in self.GNOME_DESKTOPS):
			try:
				source = Gio.SettingsSchemaSource.get_default()
				schema = source.lookup(self.SCHEMA, True) if source is not None else None
				if schema is not None and schema.has_key(self.KEY):
					self.settings = Gio.Settings.new(self.SCHEMA)
			except Exception:
				logger.exception('Could not initialize GNOME theme notifications')

		if self.settings is None:
			self.fallback = GtkThemeListener(callback)

	def detect(self):
		if self.settings is not None:
			color_scheme = self.settings.get_string(self.KEY)
			if dark_from_color_scheme(color_scheme):
				return True
			if str(color_scheme).strip().casefold() == 'default':
				gtk_settings = Gtk.Settings.get_default()
				return dark_from_theme_name(
					gtk_settings.get_property('gtk-theme-name')
				)
			return False
		return self.fallback.detect()

	def start(self):
		if self.settings is not None:
			self.handler_id = self.settings.connect(
				'changed::' + self.KEY, self._on_theme_changed
			)
		else:
			self.fallback.start()

	def _on_theme_changed(self, settings, key):
		self.callback(self.detect())

	def stop(self):
		if self.settings is not None and self.handler_id is not None:
			self.settings.disconnect(self.handler_id)
			self.handler_id = None
		elif self.fallback is not None:
			self.fallback.stop()


class MacOSThemeListener:
	"""Use macOS' distributed notification center; no polling is performed."""

	NOTIFICATION = 'AppleInterfaceThemeChangedNotification'
	UTF8 = 0x08000100
	DELIVER_IMMEDIATELY = 4

	def __init__(self, callback):
		self.callback = callback
		self.cf = None
		self.center = None
		self.observer = ctypes.c_void_p(id(self))
		self.notification_name = None
		self._native_callback = None
		self.fallback = None

		try:
			self._initialize_core_foundation()
		except Exception:
			logger.exception('Could not initialize macOS appearance notifications')
			self.fallback = GtkThemeListener(callback)

	def _initialize_core_foundation(self):
		framework = (
			'/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation'
		)
		self.cf = ctypes.CDLL(framework)

		self.cf.CFNotificationCenterGetDistributedCenter.restype = ctypes.c_void_p
		self.cf.CFStringCreateWithCString.argtypes = (
			ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32
		)
		self.cf.CFStringCreateWithCString.restype = ctypes.c_void_p
		self.cf.CFNotificationCenterAddObserver.argtypes = (
			ctypes.c_void_p, ctypes.c_void_p, CF_NOTIFICATION_CALLBACK,
			ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
		)
		self.cf.CFNotificationCenterRemoveObserver.argtypes = (
			ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
		)
		self.cf.CFRelease.argtypes = (ctypes.c_void_p,)

		self.center = self.cf.CFNotificationCenterGetDistributedCenter()
		self.notification_name = self.cf.CFStringCreateWithCString(
			None, self.NOTIFICATION.encode('utf-8'), self.UTF8
		)
		if not self.center or not self.notification_name:
			raise RuntimeError('CoreFoundation notification setup failed')

		self._native_callback = CF_NOTIFICATION_CALLBACK(self._on_native_notification)

	def detect(self):
		try:
			result = subprocess.run(
				('/usr/bin/defaults', 'read', '-g', 'AppleInterfaceStyle'),
				stdout=subprocess.PIPE,
				stderr=subprocess.DEVNULL,
				text=True,
				timeout=2,
				check=False,
			)
			return result.returncode == 0 and dark_from_apple_interface_style(
				result.stdout
			)
		except (OSError, subprocess.SubprocessError):
			logger.exception('Could not read the macOS appearance')
			return False

	def start(self):
		if self.fallback is not None:
			self.fallback.start()
			return
		self.cf.CFNotificationCenterAddObserver(
			self.center,
			self.observer,
			self._native_callback,
			self.notification_name,
			None,
			self.DELIVER_IMMEDIATELY,
		)

	def _on_native_notification(self, center, observer, name, obj, user_info):
		self.callback(self.detect())

	def stop(self):
		if self.fallback is not None:
			self.fallback.stop()
			return
		if self.center and self.notification_name:
			self.cf.CFNotificationCenterRemoveObserver(
				self.center, self.observer, self.notification_name, None
			)
			self.cf.CFRelease(self.notification_name)
			self.notification_name = None


class WindowsThemeListener:
	"""Wait for Windows personalization registry notifications."""

	REGISTRY_PATH = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
	REGISTRY_VALUE = 'AppsUseLightTheme'

	def __init__(self, callback):
		import winreg
		from ctypes import wintypes

		self.callback = callback
		self.winreg = winreg
		self.key = winreg.OpenKey(
			winreg.HKEY_CURRENT_USER,
			self.REGISTRY_PATH,
			0,
			winreg.KEY_QUERY_VALUE | winreg.KEY_NOTIFY,
		)
		self.advapi32 = ctypes.WinDLL('advapi32', use_last_error=True)
		self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
		self.kernel32.CreateEventW.argtypes = (
			ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR,
		)
		self.kernel32.CreateEventW.restype = wintypes.HANDLE
		self.kernel32.SetEvent.argtypes = (wintypes.HANDLE,)
		self.kernel32.SetEvent.restype = wintypes.BOOL
		self.kernel32.ResetEvent.argtypes = (wintypes.HANDLE,)
		self.kernel32.ResetEvent.restype = wintypes.BOOL
		self.kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
		self.kernel32.CloseHandle.restype = wintypes.BOOL
		self.kernel32.WaitForMultipleObjects.argtypes = (
			wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE),
			wintypes.BOOL, wintypes.DWORD,
		)
		self.kernel32.WaitForMultipleObjects.restype = wintypes.DWORD
		self.advapi32.RegNotifyChangeKeyValue.argtypes = (
			wintypes.HANDLE, wintypes.BOOL, wintypes.DWORD,
			wintypes.HANDLE, wintypes.BOOL,
		)
		self.advapi32.RegNotifyChangeKeyValue.restype = wintypes.LONG
		self.stop_event = self.kernel32.CreateEventW(None, True, False, None)
		self.change_event = self.kernel32.CreateEventW(None, True, False, None)
		if not self.stop_event or not self.change_event:
			raise ctypes.WinError(ctypes.get_last_error())
		self.thread = None

	def detect(self):
		try:
			value, value_type = self.winreg.QueryValueEx(self.key, self.REGISTRY_VALUE)
			return dark_from_windows_apps_use_light_theme(value)
		except OSError:
			return False

	def start(self):
		self.thread = threading.Thread(
			target=self._watch,
			name='ZimSystemThemeWatcher',
			daemon=True,
		)
		self.thread.start()

	def _watch(self):
		from ctypes import wintypes

		reg_notify_change_last_set = 0x00000004
		wait_object_0 = 0
		wait_failed = 0xFFFFFFFF
		handles = (wintypes.HANDLE * 2)(self.change_event, self.stop_event)

		while True:
			self.kernel32.ResetEvent(self.change_event)
			status = self.advapi32.RegNotifyChangeKeyValue(
				wintypes.HANDLE(int(self.key)), True, reg_notify_change_last_set,
				self.change_event, True,
			)
			if status != 0:
				logger.error('RegNotifyChangeKeyValue failed with status %s', status)
				return

			result = self.kernel32.WaitForMultipleObjects(2, handles, False, 0xFFFFFFFF)
			if result == wait_object_0 + 1:
				return
			if result == wait_object_0:
				self.callback(self.detect())
			elif result == wait_failed:
				logger.error('WaitForMultipleObjects failed: %s', ctypes.get_last_error())
				return

	def stop(self):
		if self.thread is not None:
			self.kernel32.SetEvent(self.stop_event)
			self.thread.join(timeout=2)
			self.thread = None
		self.winreg.CloseKey(self.key)
		self.kernel32.CloseHandle(self.change_event)
		self.kernel32.CloseHandle(self.stop_event)


def create_theme_listener(callback, platform=None):
	platform = sys.platform if platform is None else platform
	if platform == 'darwin':
		return MacOSThemeListener(callback)
	if platform == 'win32':
		try:
			return WindowsThemeListener(callback)
		except Exception:
			logger.exception('Could not initialize Windows appearance notifications')
			return GtkThemeListener(callback)
	if platform.startswith('linux'):
		return LinuxThemeListener(callback)
	return GtkThemeListener(callback)


class SystemThemePlugin(PluginClass):

	plugin_info = {
		'name': _('System Theme'),  # T: plugin name
		'description': _(
			'Keep Zim\'s built-in light or dark theme synchronized with the '
			'operating system.'
		),  # T: plugin description
		'author': 'Zim Wiki plugin contributors',
	}

	def __init__(self):
		PluginClass.__init__(self)
		self.gtk_settings = Gtk.Settings.get_default()
		self.ui_preferences = ConfigManager.preferences['GtkInterface']
		self.ui_preferences.setdefault('prefer-dark-theme', False)
		self.text_style = ConfigManager.get_config_dict('style.conf')

		self._original_preference = bool(self.ui_preferences['prefer-dark-theme'])
		self._original_gtk_preference = bool(
			self.gtk_settings.get_property('gtk-application-prefer-dark-theme')
		)
		self._original_selectors = tuple(self.text_style.selectors)
		self._applied_dark = None
		self._queued_dark = None
		self._idle_source = None

		self.listener = create_theme_listener(self._on_system_theme_changed)
		self._apply_theme(self.listener.detect())
		self.listener.start()

	def _on_system_theme_changed(self, dark):
		dark = bool(dark)
		if dark == self._applied_dark or dark == self._queued_dark:
			return
		self._queued_dark = dark
		if self._idle_source is None:
			self._idle_source = GLib.idle_add(self._apply_queued_theme)

	def _apply_queued_theme(self):
		self._idle_source = None
		dark = self._queued_dark
		self._queued_dark = None
		if dark is not None:
			self._apply_theme(dark)
		return GLib.SOURCE_REMOVE

	def _apply_theme(self, dark):
		dark = bool(dark)
		if dark == self._applied_dark:
			return

		logger.info('Synchronize Zim with system %s theme', 'dark' if dark else 'light')
		self._applied_dark = dark
		if bool(self.ui_preferences['prefer-dark-theme']) != dark:
			self.ui_preferences['prefer-dark-theme'] = dark
		if bool(self.gtk_settings.get_property(
			'gtk-application-prefer-dark-theme'
		)) != dark:
			self.gtk_settings.set_property('gtk-application-prefer-dark-theme', dark)

		selectors = ('darktheme',) if dark else ()
		if tuple(self.text_style.selectors) != selectors:
			self.text_style.set_selectors(selectors)

	def teardown(self):
		self.listener.stop()
		if self._idle_source is not None:
			GLib.source_remove(self._idle_source)
			self._idle_source = None
		self._queued_dark = None

		self.ui_preferences['prefer-dark-theme'] = self._original_preference
		self.gtk_settings.set_property(
			'gtk-application-prefer-dark-theme', self._original_gtk_preference
		)
		self.text_style.set_selectors(self._original_selectors)
