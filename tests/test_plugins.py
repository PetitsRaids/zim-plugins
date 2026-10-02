import builtins
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class FakePreferences(dict):
	pass


class FakePluginClass:
	def __init__(self):
		pass


class FakeGtkSettings:
	def __init__(self):
		self.properties = {
			'gtk-application-prefer-dark-theme': False,
			'gtk-theme-name': 'Default',
		}
		self.handlers = {}
		self.next_handler = 1

	def get_property(self, name):
		return self.properties[name]

	def set_property(self, name, value):
		self.properties[name] = value

	def connect(self, signal, callback):
		handler_id = self.next_handler
		self.next_handler += 1
		self.handlers[handler_id] = (signal, callback)
		return handler_id

	def disconnect(self, handler_id):
		self.handlers.pop(handler_id)


class FakeTextStyle:
	def __init__(self, selectors=()):
		self.selectors = tuple(selectors)
		self.set_calls = []

	def set_selectors(self, selectors):
		self.selectors = tuple(selectors or ())
		self.set_calls.append(self.selectors)


class FakeConfigManager:
	preferences = {'GtkInterface': FakePreferences(**{'prefer-dark-theme': False})}
	text_style = FakeTextStyle()

	@classmethod
	def get_config_dict(cls, name):
		return cls.text_style


class FakeMainWindowExtension:
	def __init__(self, plugin, window):
		self.plugin = plugin
		self.window = window

	def connectto(self, obj, signal, handler=None):
		return 1


class FakeGLib:
	SOURCE_REMOVE = False
	_next_id = 1
	callbacks = {}
	removed = []

	@classmethod
	def reset(cls):
		cls._next_id = 1
		cls.callbacks = {}
		cls.removed = []

	@classmethod
	def _add(cls, callback):
		source_id = cls._next_id
		cls._next_id += 1
		cls.callbacks[source_id] = callback
		return source_id

	@classmethod
	def timeout_add(cls, delay, callback):
		return cls._add(callback)

	@classmethod
	def idle_add(cls, callback):
		return cls._add(callback)

	@classmethod
	def source_remove(cls, source_id):
		cls.callbacks.pop(source_id, None)
		cls.removed.append(source_id)

	@classmethod
	def run(cls, source_id):
		callback = cls.callbacks.pop(source_id)
		return callback()


class FakeWidget:
	def __init__(self):
		self.visible = True
		self.no_show_all = False

	def get_no_show_all(self):
		return self.no_show_all

	def set_no_show_all(self, value):
		self.no_show_all = value

	def hide(self):
		self.visible = False

	def show(self):
		self.visible = True


class FakeMainBox:
	def get_preferred_height(self):
		return 42, 56


class FakeNotebookState:
	def __init__(self):
		self.modified = False
		self.write_count = 0

	def write(self):
		self.write_count += 1


class FakeWindow:
	def __init__(self):
		self._zim_window_central_hbox = FakeWidget()
		self._zim_window_main = FakeMainBox()
		self.isfullscreen = False
		self.maximized = False
		self.active = False
		self.size = (800, 600)
		self.resize_calls = []
		self.keep_above_calls = []
		self.mapped = False
		self.uistate = {'windowsize': self.size, 'windowmaximized': False}
		self.notebook = types.SimpleNamespace(state=FakeNotebookState())

	def get_size(self):
		return self.size

	def resize(self, width, height):
		self.size = (width, height)
		self.resize_calls.append(self.size)

	def is_active(self):
		return self.active

	def set_keep_above(self, enabled):
		self.keep_above_calls.append(enabled)

	def get_mapped(self):
		return self.mapped

	def maximize(self):
		self.maximized = True

	def unmaximize(self):
		self.maximized = False


def load_plugin_module(name):
	path = ROOT / name / '__init__.py'
	spec = importlib.util.spec_from_file_location('test_' + name, path)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


class PluginTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.old_translate = getattr(builtins, '_', None)
		builtins._ = lambda text: text

		gi = types.ModuleType('gi')
		repository = types.ModuleType('gi.repository')
		repository.GLib = FakeGLib
		repository.Gio = types.SimpleNamespace()
		cls.gtk_settings = FakeGtkSettings()
		repository.Gtk = types.SimpleNamespace(
			Window=types.SimpleNamespace(list_toplevels=lambda: []),
			Settings=types.SimpleNamespace(get_default=lambda: cls.gtk_settings),
		)
		gi.repository = repository
		sys.modules['gi'] = gi
		sys.modules['gi.repository'] = repository

		zim = types.ModuleType('zim')
		zim.__path__ = []
		plugins = types.ModuleType('zim.plugins')
		plugins.PluginClass = FakePluginClass
		config = types.ModuleType('zim.config')
		config.ConfigManager = FakeConfigManager
		gui = types.ModuleType('zim.gui')
		gui.__path__ = []
		mainwindow = types.ModuleType('zim.gui.mainwindow')
		mainwindow.MainWindowExtension = FakeMainWindowExtension
		sys.modules['zim'] = zim
		sys.modules['zim.plugins'] = plugins
		sys.modules['zim.config'] = config
		sys.modules['zim.gui'] = gui
		sys.modules['zim.gui.mainwindow'] = mainwindow

		cls.alwaysontop = load_plugin_module('alwaysontop')
		cls.autocollapse = load_plugin_module('autocollapse')
		cls.systemtheme = load_plugin_module('systemtheme')

	@classmethod
	def tearDownClass(cls):
		if cls.old_translate is None:
			del builtins._
		else:
			builtins._ = cls.old_translate

	def setUp(self):
		FakeGLib.reset()
		self.gtk_settings.properties = {
			'gtk-application-prefer-dark-theme': False,
			'gtk-theme-name': 'Default',
		}
		FakeConfigManager.preferences = {
			'GtkInterface': FakePreferences(**{'prefer-dark-theme': False})
		}
		FakeConfigManager.text_style = FakeTextStyle(('original',))

	def test_always_on_top_applies_preference_and_cleans_up(self):
		plugin = types.SimpleNamespace(preferences=FakePreferences(enabled=True))
		window = FakeWindow()
		extension = self.alwaysontop.AlwaysOnTopMainWindowExtension(plugin, window)
		self.assertEqual(window.keep_above_calls, [True])

		# Zim creates extensions before the native window is mapped. The map
		# callback must reapply the hint after GTK has created that window.
		extension.on_window_realize(window)
		first_source = extension._reapply_source
		extension.on_window_map_event(window, None)
		self.assertIn(first_source, FakeGLib.removed)
		FakeGLib.run(extension._reapply_source)
		self.assertEqual(window.keep_above_calls, [True, True])
		extension.on_window_focus_in_event(window, None)
		FakeGLib.run(extension._reapply_source)
		self.assertEqual(window.keep_above_calls, [True, True, True])

		plugin.preferences['enabled'] = False
		extension.on_preferences_changed(plugin.preferences)
		extension.teardown()
		self.assertEqual(window.keep_above_calls, [True, True, True, False, False])

	def test_auto_collapse_hides_center_and_restores_geometry(self):
		preferences = FakePreferences(enabled=True, delay=250, ignore_child_windows=True)
		plugin = types.SimpleNamespace(preferences=preferences)
		window = FakeWindow()
		extension = self.autocollapse.AutoCollapseMainWindowExtension(plugin, window)

		extension.collapse()
		self.assertFalse(window._zim_window_central_hbox.visible)
		FakeGLib.run(extension._resize_source)
		self.assertEqual(window.resize_calls[-1], (800, 56))

		extension.expand()
		self.assertTrue(window._zim_window_central_hbox.visible)
		self.assertEqual(window.resize_calls[-1], (800, 600))

	def test_close_persists_expanded_geometry(self):
		preferences = FakePreferences(enabled=True, delay=250, ignore_child_windows=True)
		plugin = types.SimpleNamespace(preferences=preferences)
		window = FakeWindow()
		extension = self.autocollapse.AutoCollapseMainWindowExtension(plugin, window)

		extension.collapse()
		window.uistate['windowsize'] = (800, 56)
		window.notebook.state.modified = True
		extension.on_window_close(window)

		self.assertEqual(window.uistate['windowsize'], (800, 600))
		self.assertEqual(window.notebook.state.write_count, 1)

	def test_system_theme_initial_sync_notification_dedup_and_restore(self):
		class FakeListener:
			def __init__(self, callback):
				self.callback = callback
				self.started = False
				self.stopped = False

			def detect(self):
				return True

			def start(self):
				self.started = True

			def stop(self):
				self.stopped = True

		original_factory = self.systemtheme.create_theme_listener
		listeners = []

		def factory(callback):
			listener = FakeListener(callback)
			listeners.append(listener)
			return listener

		self.systemtheme.create_theme_listener = factory
		try:
			plugin = self.systemtheme.SystemThemePlugin()
			listener = listeners[0]
			self.assertTrue(listener.started)
			self.assertTrue(
				FakeConfigManager.preferences['GtkInterface']['prefer-dark-theme']
			)
			self.assertTrue(self.gtk_settings.get_property(
				'gtk-application-prefer-dark-theme'
			))
			self.assertEqual(FakeConfigManager.text_style.selectors, ('darktheme',))

			listener.callback(False)
			first_source = plugin._idle_source
			listener.callback(False)
			self.assertEqual(plugin._idle_source, first_source)
			FakeGLib.run(first_source)
			self.assertFalse(
				FakeConfigManager.preferences['GtkInterface']['prefer-dark-theme']
			)
			self.assertEqual(FakeConfigManager.text_style.selectors, ())

			listener.callback(True)
			FakeGLib.run(plugin._idle_source)
			plugin.teardown()
			self.assertTrue(listener.stopped)
			self.assertFalse(
				FakeConfigManager.preferences['GtkInterface']['prefer-dark-theme']
			)
			self.assertFalse(self.gtk_settings.get_property(
				'gtk-application-prefer-dark-theme'
			))
			self.assertEqual(FakeConfigManager.text_style.selectors, ('original',))
		finally:
			self.systemtheme.create_theme_listener = original_factory

	def test_system_theme_platform_value_decoders(self):
		self.assertTrue(self.systemtheme.dark_from_apple_interface_style('Dark\n'))
		self.assertFalse(self.systemtheme.dark_from_apple_interface_style(''))
		self.assertTrue(
			self.systemtheme.dark_from_windows_apps_use_light_theme(0)
		)
		self.assertFalse(
			self.systemtheme.dark_from_windows_apps_use_light_theme(1)
		)
		self.assertTrue(self.systemtheme.dark_from_color_scheme('prefer-dark'))
		self.assertTrue(self.systemtheme.dark_from_theme_name('Adwaita-dark'))

	def test_linux_uses_gnome_notifications_and_gtk_fallback(self):
		class FakeSchema:
			def has_key(self, key):
				return key == 'color-scheme'

		class FakeGioSettings:
			def __init__(self):
				self.value = 'prefer-dark'
				self.handler = None

			def get_string(self, key):
				return self.value

			def connect(self, signal, callback):
				self.handler = callback
				return 7

			def disconnect(self, handler_id):
				self.handler = None

		gio_settings = FakeGioSettings()
		fake_gio = types.SimpleNamespace(
			SettingsSchemaSource=types.SimpleNamespace(
				get_default=lambda: types.SimpleNamespace(
					lookup=lambda name, recursive: FakeSchema()
				)
			),
			Settings=types.SimpleNamespace(new=lambda name: gio_settings),
		)
		original_gio = self.systemtheme.Gio
		original_desktop = self.systemtheme.os.environ.get('XDG_CURRENT_DESKTOP')
		try:
			self.systemtheme.Gio = fake_gio
			self.systemtheme.os.environ['XDG_CURRENT_DESKTOP'] = 'GNOME'
			listener = self.systemtheme.LinuxThemeListener(lambda dark: None)
			self.assertIs(listener.settings, gio_settings)
			self.assertTrue(listener.detect())

			self.systemtheme.os.environ['XDG_CURRENT_DESKTOP'] = 'KDE'
			listener = self.systemtheme.LinuxThemeListener(lambda dark: None)
			self.assertIsNone(listener.settings)
			self.assertIsInstance(listener.fallback, self.systemtheme.GtkThemeListener)
		finally:
			self.systemtheme.Gio = original_gio
			if original_desktop is None:
				self.systemtheme.os.environ.pop('XDG_CURRENT_DESKTOP', None)
			else:
				self.systemtheme.os.environ['XDG_CURRENT_DESKTOP'] = original_desktop

	@unittest.skipUnless(sys.platform == 'darwin', 'macOS integration test')
	def test_macos_native_notification_listener_starts_without_polling(self):
		listener = self.systemtheme.MacOSThemeListener(lambda dark: None)
		self.assertIsNone(listener.fallback)
		self.assertIsInstance(listener.detect(), bool)
		listener.start()
		listener.stop()


if __name__ == '__main__':
	unittest.main()
