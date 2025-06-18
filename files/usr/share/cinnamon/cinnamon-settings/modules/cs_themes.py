#!/usr/bin/python3

import os
import json
import tinycss2
import config

from gi.repository import Gtk, GdkPixbuf, Pango

from xapp.GSettingsWidgets import *
from CinnamonGtkSettings import CssRange, CssOverrideSwitch, GtkSettingsSwitch, PreviewWidget, Gtk2ScrollbarSizeEditor
from SettingsWidgets import LabelRow, SidePage, walk_directories
from ChooserButtonWidgets import PictureChooserButton
from ExtensionCore import DownloadSpicesPage
from Spices import Spice_Harvester

from pathlib import Path

ICON_SIZE = 48

# Gtk and Cinnamon check folders in order of precedence. These lists match the
# order. It doesn't really matter here, since we're only looking for names,
# but it's helpful to be aware of it.

ICON_FOLDERS = [
    os.path.join(GLib.get_home_dir(), ".icons"),
    os.path.join(GLib.get_user_data_dir(), "icons")
] + [os.path.join(datadir, "icons") for datadir in GLib.get_system_data_dirs()]

THEME_FOLDERS = [
    os.path.join(GLib.get_home_dir(), ".themes"),
    os.path.join(GLib.get_user_data_dir(), "themes")
] + [os.path.join(datadir, "themes") for datadir in GLib.get_system_data_dirs()]

THEMES_BLACKLIST = [
    "gnome", # not meant to be used as a theme. Provides icons to inheriting themes.
    "hicolor", # same
    "adwaita", "adwaita-dark", "adwaitalegacy" # incomplete outside of GNOME, doesn't support Cinnamon.
    "highcontrast", # same. Also, available via a11y as a global setting.
    "epapirus", "epapirus-dark", # specifically designed for Pantheon
    "ubuntu-mono", "ubuntu-mono-dark", "ubuntu-mono-light", "loginicons", # ubuntu-mono icons (non-removable in Ubuntu 24.04)
    "humanity", "humanity-dark"  # same
]

class ThemePathManager:
    """Utility class for managing theme paths"""
    
    @staticmethod
    def get_system_paths(theme_name, theme_type):
        """Gets system paths for a theme"""
        paths = []
        for datadir in GLib.get_system_data_dirs():
            if theme_type == "icons":
                paths.append(os.path.join(datadir, "icons", theme_name))
            else:
                paths.append(os.path.join(datadir, "themes", theme_name, theme_type))
        return paths

    @staticmethod
    def get_user_paths(theme_name, theme_type):
        """Gets user paths for a theme"""
        paths = []
        if theme_type == "icons":
            paths.append(os.path.expanduser(f"~/.icons/{theme_name}"))
            paths.append(os.path.join(GLib.get_user_data_dir(), "icons", theme_name))
        else:
            paths.append(os.path.expanduser(f"~/.themes/{theme_name}/{theme_type}"))
            paths.append(os.path.join(GLib.get_user_data_dir(), "themes", theme_name, theme_type))
        return paths

    @staticmethod
    def get_thumbnail_paths(theme_name, theme_type):
        """Gets thumbnail paths for a theme"""
        return [
            f"/usr/share/cinnamon/thumbnails/{theme_type}/{theme_name}.png",
            f"/usr/share/cinnamon/thumbnails/{theme_type}/unknown.png"
        ]

    @staticmethod
    def get_all_paths(theme_name, theme_type):
        """Gets all possible paths for a theme"""
        return (
            ThemePathManager.get_system_paths(theme_name, theme_type) +
            ThemePathManager.get_user_paths(theme_name, theme_type) +
            ThemePathManager.get_thumbnail_paths(theme_name, theme_type)
        )

    @staticmethod
    def get_cache_paths():
        """Gets cache paths"""
        cache_folder = os.path.join(GLib.get_user_cache_dir(), 'cs_themes')
        icon_cache_path = os.path.join(cache_folder, 'icons')
        return cache_folder, icon_cache_path

class Style:
    def __init__(self, json_obj):
        self.name = json_obj["name"]
        self.modes = {}
        self.default_mode = None

class Mode:
    def __init__(self, name):
        self.name = name
        self.default_variant = None
        self.variants = []

    def get_variant_by_name(self, name):
        for variant in self.variants:
            if name == variant.name:
                return variant

        return None

class Variant:
    def __init__(self, json_obj):
        self.name = json_obj["name"]
        self.gtk_theme = None
        self.icon_theme = None
        self.cinnamon_theme = None
        self.cursor_theme = None
        self.color = "#000000"
        self.color2 = "#000000"
        if "themes" in json_obj:
            themes = json_obj["themes"]
            self.gtk_theme = themes
            self.icon_theme = themes
            self.cinnamon_theme = themes
            self.cursor_theme = themes
        if "gtk" in json_obj:
            self.gtk_theme = json_obj["gtk"]
        if "icons" in json_obj:
            self.icon_theme = json_obj["icons"]
        if "cinnamon" in json_obj:
            self.cinnamon_theme = json_obj["cinnamon"]
        if "cursor" in json_obj:
            self.cursor_theme = json_obj["cursor"]
        self.color = json_obj["color"]
        self.color2 = self.color
        if "color2" in json_obj:
            self.color2 = json_obj["color2"]

class Module:
    comment = _("Manage themes to change how your desktop looks")
    name = "themes"
    category = "appear"

    # Preview sizes for each theme type
    PREVIEW_SIZES = {
        "icons": 48,      # Standard size for icons
        "cursors": 48,    # Standard size for cursors
        "gtk-3.0": 120,   # Size for GTK themes
        "cinnamon": 120   # Size for Cinnamon themes
    }

    def __init__(self, content_box):
        self.keywords = _("themes, style")
        self.icon = "cs-themes"
        self.window = None
        sidePage = SidePage(_("Themes"), self.icon, self.keywords, content_box, module=self)
        self.sidePage = sidePage
        self.refreshing = False # flag to ensure we only refresh once at any given moment
        self.theme_buttons = {}  # Dictionary to store theme buttons

        # Initialize settings
        self.initialize_settings()

        widget = SettingsWidget()
        widget.set_spacing(20)
        image = Gtk.Image.new_from_icon_name("cs-themes", Gtk.IconSize.DIALOG)
        image.set_pixel_size(38)
        label = Gtk.Label.new()
        label.set_markup("<b>THEMES</b>")
        label.set_selectable(False)
        label.set_size_request(60, 60) 
        widget.pack_start(image, False, False, 0)
        widget.pack_end(image, True, False, 0)
        widget.pack_start(label, False, False, 0)
        widget.pack_end(label, True, False, 0)
        self.sidePage.add_widget(widget)

        # Add global CSS style
        css = """
        .theme-nav-button {
            padding: 8px;
            border-radius: 4px;
            margin: 0 2px;
        }
        .theme-nav-button:checked {
            background-color: alpha(#3584e4, 0.1);
        }
        .theme-nav-button:hover:not(:checked) {
            background-color: alpha(#000000, 0.05);
        }
        """
        self.apply_css_style(css)

    def initialize_settings(self):
        """Initialize GSettings parameters"""
        try:
            # For GTK themes, icons and cursors
            self.settings = Gio.Settings.new("org.cinnamon.desktop.interface")
            # For Cinnamon theme
            self.cinnamon_settings = Gio.Settings.new("org.cinnamon.theme")
            self.xsettings = Gio.Settings.new("org.x.apps.portal")
        except GLib.Error as e:
            print(f"Error initializing settings: {e}")
            self.settings = None
            self.cinnamon_settings = None
            self.xsettings = None

    def refresh_themes(self):
        # Find all installed themes
        self.gtk_themes = []
        self.gtk_theme_names = set()
        self.icon_theme_names = []
        self.cinnamon_themes = []
        self.cinnamon_theme_names = set()
        self.cursor_themes = []
        self.cursor_theme_names = set()

        # Gtk themes -- Only shows themes that have a gtk-3.* variation
        for (name, path) in walk_directories(THEME_FOLDERS, self.filter_func_gtk_dir, return_directories=True):
            if name.lower() in THEMES_BLACKLIST:
                continue
            for theme in self.gtk_themes:
                if name == theme[0]:
                    if path == THEME_FOLDERS[0]:
                        continue
                    else:
                        self.gtk_themes.remove(theme)
            self.gtk_theme_names.add(name)
            self.gtk_themes.append((name, path))
        self.gtk_themes.sort(key=lambda a: a[0].lower())

        # Cinnamon themes
        for (name, path) in walk_directories(THEME_FOLDERS, lambda d: os.path.exists(os.path.join(d, "cinnamon")), return_directories=True):
            for theme in self.cinnamon_themes:
                if name == theme[0]:
                    if path == THEME_FOLDERS[0]:
                        continue
                    else:
                        self.cinnamon_themes.remove(theme)
            self.cinnamon_theme_names.add(name)
            self.cinnamon_themes.append((name, path))
        self.cinnamon_themes.sort(key=lambda a: a[0].lower())

        # Icon themes
        walked = walk_directories(ICON_FOLDERS, lambda d: os.path.isdir(d), return_directories=True)
        valid = []
        for directory in walked:
            if directory[0].lower() in THEMES_BLACKLIST:
                continue
            path = os.path.join(directory[1], directory[0], "index.theme")
            if os.path.exists(path):
                try:
                    for line in list(open(path)):
                        if line.startswith("Directories="):
                            valid.append(directory)
                            break
                except Exception as e:
                    print (e)
        valid.sort(key=lambda a: a[0].lower())
        for (name, path) in valid:
            if name not in self.icon_theme_names:
                self.icon_theme_names.append(name)

        # Cursor themes
        for (name, path) in walk_directories(ICON_FOLDERS, lambda d: os.path.isdir(d) and os.path.exists(os.path.join(d, "cursors")), return_directories=True):
            if name.lower() in THEMES_BLACKLIST:
                continue
            for theme in self.cursor_themes:
                if name == theme[0]:
                    if path == ICON_FOLDERS[0]:
                        continue
                    else:
                        self.cursor_themes.remove(theme)
            self.cursor_theme_names.add(name)
            self.cursor_themes.append((name, path))
        self.cursor_themes.sort(key=lambda a: a[0].lower())

    def on_module_selected(self):
        if not self.loaded:
            print("Loading Themes module")

            self.refresh_themes()

            self.ui_ready = True

            self.spices = Spice_Harvester('theme', self.window)

            self.sidePage.stack = SettingsStack()
            self.sidePage.add_widget(self.sidePage.stack)

            self.scale = self.window.get_scale_factor()

            self.icon_chooser = self.create_button_chooser(self.settings, 'icon-theme', 'icons', 'icons', button_picture_width=ICON_SIZE, menu_picture_width=ICON_SIZE, num_cols=3, frame=False)
            self.cursor_chooser = self.create_button_chooser(self.settings, 'cursor-theme', 'icons', 'cursors', button_picture_width=32, menu_picture_width=32, num_cols=3, frame=False)
            self.theme_chooser = self.create_button_chooser(self.settings, 'gtk-theme', 'themes', 'gtk-3.0', button_picture_width=125, menu_picture_width=125, num_cols=3, frame=False)
            self.cinnamon_chooser = self.create_button_chooser(self.cinnamon_settings, 'name', 'themes', 'cinnamon', button_picture_width=125, menu_picture_width=125*self.scale, num_cols=3, frame=False)

            selected_meta_theme = None

            gladefile = "/usr/share/cinnamon/cinnamon-settings/themes.ui"
            builder = Gtk.Builder()
            builder.set_translation_domain('cinnamon')
            builder.add_from_file(gladefile)
            page = builder.get_object("page_simplified")
            page.show()

            # Configure style_combo
            self.style_combo = builder.get_object("style_combo")
            # GtkComboBoxText already has an internal model, so we don't need to create a new one
            # Just clear any existing items
            self.style_combo.remove_all()

            self.mixed_button = builder.get_object("mixed_button")
            self.dark_button = builder.get_object("dark_button")
            self.light_button = builder.get_object("light_button")
            self.color_box = builder.get_object("color_box")
            self.customize_button = builder.get_object("customize_button")
            self.preset_button = builder.get_object("preset_button")
            self.color_label = builder.get_object("color_label")
            self.active_style = None
            self.active_mode_name = None
            self.active_variant = None

            # HiDPI support
            for mode in ["mixed", "dark", "light"]:
                path = f"/usr/share/cinnamon/cinnamon-settings/appearance-{mode}.svg"
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(path, 112*self.scale, 80*self.scale)
                surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, self.scale)
                builder.get_object(f"image_{mode}").set_from_surface(surface)

            self.color_dot_svg = ""
            with open("/usr/share/cinnamon/cinnamon-settings/color_dot.svg") as f:
                self.color_dot_svg = f.read()

            self.reset_look_ui()

            self.mixed_button.connect("clicked", self.on_mode_button_clicked, "mixed")
            self.dark_button.connect("clicked", self.on_mode_button_clicked, "dark")
            self.light_button.connect("clicked", self.on_mode_button_clicked, "light")
            self.customize_button.connect("clicked", self.on_customize_button_clicked)
            self.style_combo.connect("changed", self.on_style_combo_changed)

            self.sidePage.stack.add_named(page, "simplified")

            page = SettingsPage()
            self.sidePage.stack.add_titled(page, "themes", _("Themes"))

            # Main vertical container
            main_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            main_container.set_hexpand(True)
            main_container.set_vexpand(True)
            page.add(main_container)

            # Stack to contain different theme pages
            self.theme_stack = Gtk.Stack()
            self.theme_stack.set_hexpand(True)
            self.theme_stack.set_vexpand(True)
            main_container.pack_start(self.theme_stack, True, True, 0)

            # Toolbar
            button_toolbar = Gtk.Toolbar.new()
            Gtk.StyleContext.add_class(Gtk.Widget.get_style_context(button_toolbar), "inline-toolbar")
            main_container.pack_start(button_toolbar, False, False, 0)

            # CSS style for toolbar
            css_provider = Gtk.CssProvider()
            css = """
            .inline-toolbar {
                background: transparent;
                border: none;
                box-shadow: none;
            }           
            """
            css_provider.load_from_data(css.encode())
            style_context = Gtk.StyleContext()
            style_context.add_provider_for_screen(
                Gdk.Screen.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

            button_holder = Gtk.ToolItem()
            button_holder.set_expand(True)
            button_toolbar.add(button_holder)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            button_group = Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL)
            box.set_halign(Gtk.Align.CENTER)
            button_holder.add(box)

            # Define theme pages with their icons
            nav_pages = [
                ("applications", "applications-graphics-symbolic", _("Applications"), "gtk-3.0"),
                ("icons", "user-bookmarks-symbolic", _("Icons"), "icons"),
                ("desktop", "cinnamon-symbolic", _("Desktop"), "cinnamon"),
                ("cursor", "tool-pointer-symbolic", _("Cursor"), "cursors")
            ]

            # Create theme pages and navigation buttons
            self.nav_buttons = {}  # Dictionary to store navigation buttons
            for page_id, icon_name, title, theme_type in nav_pages:
                # Create theme page
                theme_page = self.create_theme_grid(title, 
                    self.gtk_themes if theme_type == "gtk-3.0" else
                    self.icon_theme_names if theme_type == "icons" else
                    self.cinnamon_themes if theme_type == "cinnamon" else
                    self.cursor_themes,
                    theme_type,
                    "gtk-theme" if theme_type == "gtk-3.0" else
                    "icon-theme" if theme_type == "icons" else
                    "name" if theme_type == "cinnamon" else
                    "cursor-theme"
                )
                self.theme_stack.add_named(theme_page, page_id)

                # Create navigation button
                button = Gtk.ToggleButton()
                button.set_size_request(66, 26)  # Set fixed width of 120px
                icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.BUTTON)
                icon.set_pixel_size(20)
                button.add(icon)
                button.set_tooltip_text(title)
                button_group.add_widget(button)
                box.add(button)
                
                # Store button in dictionary
                self.nav_buttons[page_id] = button
                
                # Connect click
                button.connect('toggled', self.on_nav_button_toggled, page_id)

            # Container for simplified settings button
            simplified_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            simplified_box.set_hexpand(True)
            simplified_box.set_halign(Gtk.Align.END)
            simplified_box.set_margin_top(10)
            simplified_box.set_margin_bottom(10)
            simplified_box.set_margin_end(20)
            main_container.pack_end(simplified_box, False, False, 0)

            # Simplified settings button
            simplified_button = Gtk.Button()
            simplified_button.set_label(_("Simplified settings..."))
            simplified_button.connect("clicked", self.on_simplified_button_clicked)
            simplified_box.pack_end(simplified_button, False, False, 0)

            # Activate first button by default
            first_button = box.get_children()[0]
            first_button.set_active(True)
            self.theme_stack.set_visible_child_name("applications")

            page = DownloadSpicesPage(self, 'theme', self.spices, self.window)
            self.sidePage.stack.add_titled(page, 'download', _("Add/Remove"))

            page = SettingsPage()
            self.sidePage.stack.add_titled(page, "options", _("Settings"))

            settings = page.add_section(_("Miscellaneous options"))

            options = [("default", _("Let applications decide")),
                       ("prefer-dark", _("Prefer dark mode")),
                       ("prefer-light", _("Prefer light mode"))]
            widget = GSettingsComboBox(_("Dark mode"), "org.x.apps.portal", "color-scheme", options)
            widget.set_tooltip_text(_("This setting only affects applications which support dark mode"))
            settings.add_row(widget)

            widget = GSettingsSwitch(_("Show icons in menus"), "org.cinnamon.settings-daemon.plugins.xsettings", "menus-have-icons")
            settings.add_row(widget)

            widget = GSettingsSwitch(_("Show icons on buttons"), "org.cinnamon.settings-daemon.plugins.xsettings", "buttons-have-icons")
            settings.add_row(widget)

            settings = page.add_section(_("Scrollbar behavior"))

            # Translators: The 'trough' is the part of the scrollbar that the 'handle'
            # rides in.  This setting determines whether clicking in that trough somewhere
            # jumps directly to the new position, or if it only scrolls towards it.
            switch = GtkSettingsSwitch(_("Jump to position when clicking in a trough"), "gtk-primary-button-warps-slider")
            settings.add_row(switch)

            widget = GSettingsSwitch(_("Use overlay scroll bars"), "org.cinnamon.desktop.interface", "gtk-overlay-scrollbars")
            settings.add_row(widget)

            self.gtk2_scrollbar_editor = Gtk2ScrollbarSizeEditor(widget.get_scale_factor())

            switch = CssOverrideSwitch(_("Override the current theme's scrollbar width"))
            settings.add_row(switch)
            self.scrollbar_switch = switch.content_widget

            widget = CssRange(_("Scrollbar width"), "scrollbar slider", ["min-width", "min-height"], 2, 40, "px", None, switch)
            settings.add_reveal_row(widget)

            try:
                widget.sync_initial_switch_state()
            except PermissionError as e:
                print(e)
                switch.set_sensitive(False)

            self.scrollbar_css_range = widget.content_widget
            self.scrollbar_css_range.get_adjustment().set_page_increment(2.0)

            switch.content_widget.connect("notify::active", self.on_css_override_active_changed)
            widget.content_widget.connect("value-changed", self.on_range_slider_value_changed)

            self.on_css_override_active_changed(switch)

            widget = PreviewWidget()
            settings.add_row(widget)

            label_widget = LabelRow(_(
"""Changes may not apply to already-running programs, and may not affect all applications."""))
            settings.add_row(label_widget)

            self.builder = self.sidePage.builder

            for path in [THEME_FOLDERS[0], ICON_FOLDERS[0], ICON_FOLDERS[1]]:
                try:
                    os.makedirs(path)
                except OSError:
                    pass

            self.monitors = []
            for path in (THEME_FOLDERS + ICON_FOLDERS):
                if os.path.exists(path):
                    file_obj = Gio.File.new_for_path(path)
                    try:
                        file_monitor = file_obj.monitor_directory(Gio.FileMonitorFlags.SEND_MOVED, None)
                        file_monitor.connect("changed", self.on_file_changed)
                        self.monitors.append(file_monitor)
                    except Exception as e:
                        # File monitors can fail when the OS runs out of file handles
                        print(e)

            self.refresh_choosers()
            if config.PARSED_ARGS.module is None or (config.PARSED_ARGS.module == "themes" and config.PARSED_ARGS.tab is None):
                GLib.idle_add(self.set_mode, "simplified" if self.active_variant is not None else "themes", True)

            return

        GLib.idle_add(self.set_mode, self.sidePage.stack.get_visible_child_name())

    def is_variant_active(self, variant):
        # returns whether or not the given variant corresponds to the currently selected themes
        if variant.gtk_theme != self.settings.get_string("gtk-theme"):
            return False
        if variant.icon_theme != self.settings.get_string("icon-theme"):
            return False
        if variant.cinnamon_theme != self.cinnamon_settings.get_string("name"):
            return False
        if variant.cursor_theme != self.settings.get_string("cursor-theme"):
            return False
        return True

    def is_variant_valid(self, variant):
        # returns whether or not the given variant is valid (i.e. made of themes which are currently installed)
        if variant.gtk_theme is None:
            print("No Gtk theme defined")
            return False
        if variant.icon_theme is None:
            print("No icon theme defined")
            return False
        if variant.cinnamon_theme is None:
            print("No Cinnamon theme defined")
            return False
        if variant.cursor_theme is None:
            print("No cursor theme defined")
            return False
        if variant.gtk_theme not in self.gtk_theme_names:
            print("Gtk theme not found:", variant.gtk_theme)
            return False
        if variant.icon_theme not in self.icon_theme_names:
            print("icon theme not found:", variant.icon_theme)
            return False
        if variant.cinnamon_theme not in self.cinnamon_theme_names and variant.cinnamon_theme != "cinnamon":
            print("Cinnamon theme not found:", variant.cinnamon_theme)
            return False
        if variant.cursor_theme not in self.cursor_theme_names:
            print("Cursor theme not found:", variant.cursor_theme)
            return False
        return True

    def cleanup_ui(self):
        """Clean up the user interface"""
        try:
            # Reset mode buttons
            for mode_name in ["mixed", "dark", "light"]:
                button = getattr(self, f"{mode_name}_button", None)
                if button is not None:
                    button.set_state_flags(Gtk.StateFlags.NORMAL, True)
                    button.set_sensitive(False)

            # Clear color box
            if hasattr(self, 'color_box'):
                for child in self.color_box.get_children():
                    self.color_box.remove(child)
                self.color_label.hide()

            # Reset style_combo
            if hasattr(self, 'style_combo'):
                self.style_combo.remove_all()
        except Exception as e:
            print(f"Error cleaning up the interface: {e}")

    def reset_look_ui(self):
        """Reset style interface"""
        if not hasattr(self, 'ui_ready') or not self.ui_ready:
            return

        try:
            self.ui_ready = False
            self.cleanup_ui()

            # Read the JSON files
            self.styles = {}
            self.style_objects = {}
            self.active_style = None
            self.active_mode_name = None
            self.active_variant = None

            path = "/usr/share/cinnamon/styles.d"
            if os.path.exists(path):
                for filename in sorted(os.listdir(path)):
                    if filename.endswith(".styles"):
                        try:
                            with open(os.path.join(path, filename)) as f:
                                json_text = json.loads(f.read())
                                for style_json in json_text["styles"]:
                                    style = Style(style_json)
                                    for mode_name in ["mixed", "dark", "light"]:
                                        if mode_name in style_json:
                                            mode = Mode(mode_name)
                                            for variant_json in style_json[mode_name]:
                                                variant = Variant(variant_json)
                                                if self.is_variant_valid(variant):
                                                    mode.variants.append(variant)
                                                    if mode.default_variant is None:
                                                        mode.default_variant = variant
                                                    if "default" in variant_json and variant_json["default"] == "true":
                                                        mode.default_variant = variant
                                                    if not mode_name in style.modes:
                                                        style.modes[mode_name] = mode
                                                    if style.default_mode is None:
                                                        style.default_mode = mode
                                                    if self.is_variant_active(variant):
                                                        self.active_style = style
                                                        self.active_mode_name = mode_name
                                                        self.active_variant = variant
                                    if "default" in style_json:
                                        default_name = style_json["default"]
                                        if default_name in style.modes:
                                            style.default_mode = style.modes[default_name]

                                    if style.default_mode is None:
                                        print(f"No valid mode/variants found for style: {style.name}")
                                    else:
                                        self.styles[style.name] = style
                        except Exception as e:
                            print(f"Failed to parse styles from {filename}: {e}")

            # Update interface
            self.update_style_ui()
            self.ui_ready = True
        except Exception as e:
            print(f"Error resetting the interface: {e}")
            self.ui_ready = True  # Reactivate interface even in case of error

    def update_style_ui(self):
        """Update style interface"""
        try:
            if not hasattr(self, 'style_combo') or self.style_combo is None:
                return

            # Clear existing items
            self.style_combo.remove_all()
            
            # Add available styles
            for name in sorted(self.styles.keys()):
                self.style_combo.append_text(name)

            if self.active_variant is not None:
                style = self.active_style
                mode = self.active_style.modes[self.active_mode_name]
                variant = self.active_variant
                print("Found active variant:", style.name, mode.name, variant.name)
                
                # Position style_combo on active style
                # Find the index of the active style
                active_index = -1
                for i, name in enumerate(sorted(self.styles.keys())):
                    if name == style.name:
                        active_index = i
                        break
                if active_index >= 0:
                    self.style_combo.set_active(active_index)
                
                # Configure mode buttons
                for mode_name in ["mixed", "dark", "light"]:
                    button = getattr(self, f"{mode_name}_button")
                    if button is not None:
                        if mode_name == mode.name:
                            button.set_state_flags(Gtk.StateFlags.CHECKED, True)
                        else:
                            button.set_state_flags(Gtk.StateFlags.NORMAL, True)
                        button.set_sensitive(mode_name in style.modes)

                # Configure color buttons
                if len(mode.variants) > 1:
                    self.color_label.show()
                    for variant in mode.variants:
                        svg = self.color_dot_svg.replace("#8cffbe", variant.color)
                        svg = svg.replace("#71718e", variant.color2)
                        svg = str.encode(svg)
                        stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(svg))
                        pixbuf = GdkPixbuf.Pixbuf.new_from_stream_at_scale(stream, 22*self.scale, 22*self.scale, True, None)
                        surface = Gdk.cairo_surface_create_from_pixbuf(pixbuf, self.scale)
                        image = Gtk.Image.new_from_surface(surface)
                        button = Gtk.ToggleButton()
                        button.add(image)
                        button.show_all()
                        self.color_box.add(button)
                        if variant == self.active_variant:
                            button.set_state_flags(Gtk.StateFlags.CHECKED, True)
                        button.connect("clicked", self.on_color_button_clicked, variant)
            else:
                # Add "Custom" option if no active style
                self.style_combo.append_text(_("Custom"))
                self.style_combo.set_active(len(self.styles.keys()))
        except Exception as e:
            print(f"Error updating style interface: {e}")
            # Reset interface in case of error
            self.cleanup_ui()

    def on_customize_button_clicked(self, button):
        self.set_button_chooser(self.icon_chooser, self.settings.get_string("icon-theme"), 'icons', 'icons', ICON_SIZE)
        self.set_button_chooser(self.cursor_chooser, self.settings.get_string("cursor-theme"), 'icons', 'cursors', 32)
        self.set_button_chooser(self.theme_chooser, self.settings.get_string("gtk-theme"), 'themes', 'gtk-3.0', 35)
        self.set_button_chooser(self.cinnamon_chooser, self.cinnamon_settings.get_string("name"), 'themes', 'cinnamon', 60)
        self.set_mode("themes")

    def on_simplified_button_clicked(self, button):
        self.reset_look_ui()
        self.set_mode("simplified")

    def set_mode(self, mode, startup=False):
        # When picking a start page at startup, no transition, or else you'll see the tail end of it happening
        # as the page is loading. Otherwise, crossfade when switching between simple/custom. The left/right
        # transition is kept as the default for shifting between the 3 custom pages (themes, downloads, settings).
        if startup:
            transition = Gtk.StackTransitionType.NONE
        else:
            transition = Gtk.StackTransitionType.CROSSFADE

        switcher_widget = Gio.Application.get_default().stack_switcher

        if mode == "simplified":
            switcher_widget.set_opacity(0.0)
            switcher_widget.set_sensitive(False)
        else:
            switcher_widget.set_opacity(1.0)
            switcher_widget.set_sensitive(True)

        self.sidePage.stack.set_visible_child_full(mode, transition)

    def on_color_button_clicked(self, button, variant):
        print("Color button clicked")
        self.activate_variant(variant)

    def on_mode_button_clicked(self, button, mode_name):
        print("Mode button clicked")
        if self.active_style is not None:
            mode = self.active_style.modes[mode_name]
            self.activate_mode(self.active_style, mode)

    def on_style_combo_changed(self, combobox):
        if not self.ui_ready:
            return
        selected_name = combobox.get_active_text()
        if selected_name == None or selected_name == _("Custom"):
            return
        print("Activating style:", selected_name)
        for name in self.styles.keys():
            if name == selected_name:
                style = self.styles[name]
                mode = style.default_mode
                self.activate_mode(style, mode)

    def activate_mode(self, style, mode):
        print("Activating mode:", mode.name)

        if mode.name == "mixed":
            self.xsettings.set_enum("color-scheme", 0)
        elif mode.name == "dark":
            self.xsettings.set_enum("color-scheme", 1)
        elif mode.name == "light":
            self.xsettings.set_enum("color-scheme", 2)

        if self.active_variant is not None:
            new_same_variant = mode.get_variant_by_name(self.active_variant.name)
            if new_same_variant is not None:
                self.activate_variant(new_same_variant)
                return

        self.activate_variant(mode.default_variant)

    def activate_variant(self, variant):
        print("Activating variant:", variant.name)
        self.settings.set_string("gtk-theme", variant.gtk_theme)
        self.settings.set_string("icon-theme", variant.icon_theme)
        self.cinnamon_settings.set_string("name", variant.cinnamon_theme)
        self.settings.set_string("cursor-theme", variant.cursor_theme)
        self.reset_look_ui()

    def on_css_override_active_changed(self, switch, pspec=None, data=None):
        if self.scrollbar_switch.get_active():
            self.gtk2_scrollbar_editor.set_size(self.scrollbar_css_range.get_value())
        else:
            self.gtk2_scrollbar_editor.set_size(0)

    def on_range_slider_value_changed(self, widget, data=None):
        if self.scrollbar_switch.get_active():
            self.gtk2_scrollbar_editor.set_size(widget.get_value())

    def on_file_changed(self, file, other, event, data):
        if self.refreshing:
            return
        self.refreshing = True

        def refresh_complete():
            self.refreshing = False
            return False

        # Remove icon cache
        cache_folder, icon_cache_path = ThemePathManager.get_cache_paths()
        if os.path.exists(icon_cache_path):
            os.remove(icon_cache_path)
        
        # Refresh theme list
        self.refresh_themes()
        
        # Refresh choosers
        self.refresh_choosers()

        # Mapping theme types to page IDs
        theme_type_to_page = {
            "gtk-3.0": "applications",
            "icons": "icons",
            "cinnamon": "desktop",
            "cursors": "cursor"
        }

        def refresh_frame(theme_type, page_id):
            page = self.theme_stack.get_child_by_name(page_id)
            if page:
                frame = None
                for child in page.get_children():
                    if isinstance(child, Gtk.Frame):
                        frame = child
                        break
                
                if frame:
                    # Remove old content from frame
                    for child in frame.get_children():
                        frame.remove(child)
                    
                    # Create new ScrolledWindow
                    scrolled = Gtk.ScrolledWindow()
                    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
                    scrolled.set_shadow_type(Gtk.ShadowType.NONE)
                    scrolled.set_hexpand(True)
                    scrolled.set_vexpand(True)
                    frame.add(scrolled)
                    
                    # Main container for grid
                    main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                    main_box.set_hexpand(True)
                    main_box.set_vexpand(True)
                    main_box.set_spacing(0)
                    main_box.set_margin_start(20)
                    main_box.set_margin_end(20)
                    main_box.set_margin_top(20)
                    main_box.set_margin_bottom(20)
                    scrolled.add(main_box)
                    
                    # Get updated theme list
                    themes = {
                        "applications": self.gtk_themes,
                        "icons": self.icon_theme_names,
                        "desktop": self.cinnamon_themes,
                        "cursor": self.cursor_themes
                    }
                    
                    settings_keys = {
                        "applications": "gtk-theme",
                        "icons": "icon-theme",
                        "desktop": "name",
                        "cursor": "cursor-theme"
                    }
                    
                    # Reset button dictionary for this theme type
                    if theme_type not in self.theme_buttons:
                        self.theme_buttons[theme_type] = {}
                    else:
                        self.theme_buttons[theme_type].clear()
                    
                    # Get active theme
                    active_theme = self.get_active_theme(theme_type)
                    
                    # Add themes to grid
                    for i, theme in enumerate(themes[page_id]):
                        theme_name = theme[0] if isinstance(theme, tuple) else theme
                        theme_path = theme[1] if isinstance(theme, tuple) else None
                        
                        # Add separator before each line except the first
                        if i > 0:
                            separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                            separator.set_margin_top(5)
                            separator.set_margin_bottom(5)
                            main_box.pack_start(separator, False, False, 0)
                        
                        # Container for theme (full line)
                        theme_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
                        theme_box.set_hexpand(True)
                        theme_box.set_spacing(20)
                        theme_box.set_margin_top(5)
                        theme_box.set_margin_bottom(5)
                        
                        # Create theme button
                        theme_button = self.create_theme_button(theme_name, theme_type, theme_name == active_theme, settings_keys[page_id])
                        
                        # Store button in dictionary
                        self.theme_buttons[theme_type][theme_name] = theme_button
                        
                        theme_box.pack_start(theme_button, True, True, 0)
                        main_box.pack_start(theme_box, False, False, 0)
                    
                    # Show all widgets
                    frame.show_all()

        # Sequence updates of frames
        def refresh_next_frame(index=0):
            if index >= len(theme_type_to_page):
                GLib.timeout_add(200, refresh_complete)
                return False
            
            theme_type, page_id = list(theme_type_to_page.items())[index]
            refresh_frame(theme_type, page_id)
            GLib.timeout_add(200, refresh_next_frame, index + 1)
            return False

        # Start update sequence
        GLib.timeout_add(200, refresh_next_frame)

    def refresh_choosers(self):
        array = [(self.cursor_chooser, "cursors", self.cursor_themes, self._on_cursor_theme_selected),
                    (self.theme_chooser, "gtk-3.0", self.gtk_themes, self._on_gtk_theme_selected),
                    (self.cinnamon_chooser, "cinnamon", self.cinnamon_themes, self._on_cinnamon_theme_selected),
                    (self.icon_chooser, "icons", self.icon_theme_names, self._on_icon_theme_selected)]
        for element in array:
            chooser, path_suffix, themes, callback = element
            chooser.clear_menu()
            chooser.set_sensitive(False)
            chooser.progress = 0.0
            self.refresh_chooser(chooser, path_suffix, themes, callback)
        self.refreshing = False

    def refresh_chooser(self, chooser, path_suffix, themes, callback):
        inc = 1.0
        if len(themes) > 0:
            inc = 1.0 / len(themes)

        if path_suffix == 'icons':
            cache_folder, icon_cache_path = ThemePathManager.get_cache_paths()

            # Retrieve list of known themes/locations for faster loading (icon theme loading and lookup are very slow)
            if os.path.exists(icon_cache_path):
                read_path = icon_cache_path
            else:
                read_path = '/usr/share/cinnamon/cinnamon-settings/icons'

            icon_paths = {}
            with open(read_path, 'r') as cache_file:
                for line in cache_file:
                    theme_name, icon_path = line.strip().split(':')
                    icon_paths[theme_name] = icon_path

            dump = False
            for theme in themes:
                theme_path = None

                if theme in icon_paths:
                    # loop through all possible locations until we find a match
                    # (user folders should override system ones)
                    for theme_folder in ICON_FOLDERS:
                        possible_path = os.path.join(theme_folder, icon_paths[theme])
                        if os.path.exists(possible_path):
                            theme_path = possible_path
                            break

                if theme_path is None:
                    icon_theme = Gtk.IconTheme()
                    icon_theme.set_custom_theme(theme)
                    folder = icon_theme.lookup_icon('folder', ICON_SIZE, Gtk.IconLookupFlags.FORCE_SVG)
                    if folder:
                        theme_path = folder.get_filename()

                        # we need to get the relative path for storage
                        for theme_folder in ICON_FOLDERS:
                            if os.path.commonpath([theme_folder, theme_path]) == theme_folder:
                                icon_paths[theme] = os.path.relpath(theme_path, start=theme_folder)
                                break

                    dump = True

                if theme_path is None:
                    continue

                if os.path.exists(theme_path):
                    chooser.add_picture(theme_path, callback, title=theme, id=theme)
                GLib.timeout_add(5, self.increment_progress, (chooser, inc))

            if dump:
                if not os.path.exists(cache_folder):
                    os.mkdir(cache_folder)

                with open(icon_cache_path, 'w') as cache_file:
                    for theme_name, icon_path in icon_paths.items():
                        cache_file.write('%s:%s\n' % (theme_name, icon_path))

        else:
            if path_suffix == "cinnamon":
                chooser.add_picture("/usr/share/cinnamon/theme/thumbnail.png", callback, title="cinnamon", id="cinnamon")
            if path_suffix in ["gtk-3.0", "cinnamon"]:
                themes = sorted(themes, key=lambda t: (not t[1].startswith(GLib.get_home_dir())))

            for theme in themes:
                theme_name = theme[0]
                theme_path = theme[1]
                try:
                    for path in ["%s/%s/%s/thumbnail.png" % (theme_path, theme_name, path_suffix),
                                 "/usr/share/cinnamon/thumbnails/%s/%s.png" % (path_suffix, theme_name),
                                 "/usr/share/cinnamon/thumbnails/%s/unknown.png" % path_suffix]:
                        if os.path.exists(path):
                            chooser.add_picture(path, callback, title=theme_name, id=theme_name)
                            break
                except:
                    chooser.add_picture("/usr/share/cinnamon/thumbnails/%s/unknown.png" % path_suffix, callback, title=theme_name, id=theme_name)
                GLib.timeout_add(5, self.increment_progress, (chooser, inc))
        GLib.timeout_add(500, self.hide_progress, chooser)

    def increment_progress(self, payload):
        (chooser, inc) = payload
        chooser.increment_loading_progress(inc)

    def hide_progress(self, chooser):
        chooser.set_sensitive(True)
        chooser.reset_loading_progress()

    def _setParentRef(self, window):
        self.window = window

    def make_group(self, group_label, widget, add_widget_to_size_group=True):
        self.size_groups = getattr(self, "size_groups", [Gtk.SizeGroup.new(Gtk.SizeGroupMode.HORIZONTAL) for x in range(2)])
        box = SettingsWidget()
        label = Gtk.Label()
        label.set_markup(group_label)
        label.props.xalign = 0.0
        self.size_groups[0].add_widget(label)
        box.pack_start(label, False, False, 0)
        if add_widget_to_size_group:
            self.size_groups[1].add_widget(widget)
        box.pack_end(widget, False, False, 0)

        return box

    def create_button_chooser(self, settings, key, path_prefix, path_suffix, button_picture_width, menu_picture_width, num_cols, frame):
        chooser = PictureChooserButton(num_cols=num_cols, button_picture_width=button_picture_width, menu_picture_width=menu_picture_width, has_button_label=True, frame=frame)
        theme = settings.get_string(key)
        self.set_button_chooser(chooser, theme, path_prefix, path_suffix, button_picture_width)
        return chooser

    def set_button_chooser(self, chooser, theme, path_prefix, path_suffix, button_picture_width):
        self.set_button_chooser_text(chooser, theme)
        if path_suffix == "cinnamon" and theme == "cinnamon":
            chooser.set_picture_from_file("/usr/share/cinnamon/theme/thumbnail.png")
        elif path_suffix == "icons":
            current_theme = Gtk.IconTheme.get_default()
            folder = current_theme.lookup_icon_for_scale("folder", button_picture_width, self.window.get_scale_factor(), 0)
            if folder is not None:
                path = folder.get_filename()
                chooser.set_picture_from_file(path)
        else:
            try:
                for path in ([os.path.join(datadir, path_prefix, theme, path_suffix, "thumbnail.png") for datadir in GLib.get_system_data_dirs()]
                             + [os.path.expanduser("~/.%s/%s/%s/thumbnail.png" % (path_prefix, theme, path_suffix)),
                             "/usr/share/cinnamon/thumbnails/%s/%s.png" % (path_suffix, theme),
                             "/usr/share/cinnamon/thumbnails/%s/unknown.png" % path_suffix]):
                    if os.path.exists(path):
                        chooser.set_picture_from_file(path)
                        break
            except:
                chooser.set_picture_from_file("/usr/share/cinnamon/thumbnails/%s/unknown.png" % path_suffix)

    def set_button_chooser_text(self, chooser, theme):
        chooser.set_button_label(theme)
        chooser.set_tooltip_text(theme)

    def _on_icon_theme_selected(self, path, theme):
        try:
            self.settings.set_string("icon-theme", theme)
            self.set_button_chooser_text(self.icon_chooser, theme)
        except Exception as detail:
            print(detail)
        return True

    def _on_gtk_theme_selected(self, path, theme):
        try:
            self.settings.set_string("gtk-theme", theme)
            self.set_button_chooser_text(self.theme_chooser, theme)
        except Exception as detail:
            print(detail)
        return True

    def _on_cursor_theme_selected(self, path, theme):
        try:
            self.settings.set_string("cursor-theme", theme)
            self.set_button_chooser_text(self.cursor_chooser, theme)
        except Exception as detail:
            print(detail)

        self.update_cursor_theme_link(path, theme)
        return True

    def _on_cinnamon_theme_selected(self, path, theme):
        try:
            self.cinnamon_settings.set_string("name", theme)
            self.set_button_chooser_text(self.cinnamon_chooser, theme)
        except Exception as detail:
            print(detail)
        return True

    def filter_func_gtk_dir(self, directory):
        theme_dir = Path(directory)
        for gtk3_dir in theme_dir.glob("gtk-3.*"):
            # Skip gtk key themes
            if os.path.exists(os.path.join(gtk3_dir, "gtk.css")):
                return True
        return False

    def update_cursor_theme_link(self, path, name):
        contents = "[icon theme]\nInherits=%s\n" % name
        self._set_cursor_theme_at(ICON_FOLDERS[0], contents)
        self._set_cursor_theme_at(ICON_FOLDERS[1], contents)

    def _set_cursor_theme_at(self, directory, contents):
        default_dir = os.path.join(directory, "default")
        index_path = os.path.join(default_dir, "index.theme")

        try:
            os.makedirs(default_dir)
        except os.error as e:
            pass

        if os.path.exists(index_path):
            os.unlink(index_path)

        with open(index_path, "w") as f:
            f.write(contents)

    def get_theme_paths(self, theme_name, theme_type):
        """Gets possible paths for a given theme"""
        paths = []
        
        # System paths
        for datadir in GLib.get_system_data_dirs():
            if theme_type == "icons":
                paths.append(os.path.join(datadir, "icons", theme_name))
            else:
                paths.append(os.path.join(datadir, "themes", theme_name, theme_type))
        
        # User paths
        if theme_type == "icons":
            paths.append(os.path.expanduser(f"~/.icons/{theme_name}"))
            paths.append(os.path.join(GLib.get_user_data_dir(), "icons", theme_name))
        else:
            paths.append(os.path.expanduser(f"~/.themes/{theme_name}/{theme_type}"))
            paths.append(os.path.join(GLib.get_user_data_dir(), "themes", theme_name, theme_type))
        
        # Cinnamon thumbnails
        paths.append(f"/usr/share/cinnamon/thumbnails/{theme_type}/{theme_name}.png")
        paths.append(f"/usr/share/cinnamon/thumbnails/{theme_type}/unknown.png")
        
        return paths

    def _get_theme_preview(self, theme_name, theme_type):
        """Gets theme preview"""
        # List of possible paths for preview
        preview_paths = []
        
        # System paths
        for datadir in GLib.get_system_data_dirs():
            if theme_type == "icons":
                preview_paths.append(os.path.join(datadir, "icons", theme_name, "index.theme"))
            else:
                preview_paths.append(os.path.join(datadir, "themes", theme_name, theme_type, "thumbnail.png"))
        
        # User paths
        if theme_type == "icons":
            preview_paths.append(os.path.expanduser(f"~/.icons/{theme_name}/index.theme"))
            preview_paths.append(os.path.join(GLib.get_user_data_dir(), "icons", theme_name, "index.theme"))
        else:
            preview_paths.append(os.path.expanduser(f"~/.themes/{theme_name}/{theme_type}/thumbnail.png"))
            preview_paths.append(os.path.join(GLib.get_user_data_dir(), "themes", theme_name, theme_type, "thumbnail.png"))
        
        # Cinnamon thumbnails
        preview_paths.append(f"/usr/share/cinnamon/thumbnails/{theme_type}/{theme_name}.png")
        preview_paths.append(f"/usr/share/cinnamon/thumbnails/{theme_type}/unknown.png")
        
        # Special case for Cinnamon theme
        if theme_type == "cinnamon" and theme_name == "cinnamon":
            preview_paths.append("/usr/share/cinnamon/theme/thumbnail.png")
        
        # Search for first existing file
        for path in preview_paths:
            if os.path.exists(path) and os.path.isfile(path):
                return path
        
        return None

    def _get_icon_preview(self, theme_name):
        """Gets theme icon preview"""
        try:
            icon_theme = Gtk.IconTheme()
            icon_theme.set_custom_theme(theme_name)
            folder = icon_theme.lookup_icon('folder', ICON_SIZE, Gtk.IconLookupFlags.FORCE_SVG)
            if folder:
                return folder.get_filename()
        except Exception as e:
            print(f"Error getting preview for icon theme {theme_name}: {e}")
        return None

    def _get_cursor_preview(self, theme_name):
        """Gets theme cursor preview"""
        # List of possible paths for preview
        preview_paths = []
        
        # System paths
        for datadir in GLib.get_system_data_dirs():
            preview_paths.append(os.path.join(datadir, "icons", theme_name, "cursors", "left_ptr.png"))
        
        # User paths
        preview_paths.append(os.path.expanduser(f"~/.icons/{theme_name}/cursors/left_ptr.png"))
        preview_paths.append(os.path.join(GLib.get_user_data_dir(), "icons", theme_name, "cursors", "left_ptr.png"))
        
        # Cinnamon thumbnails
        preview_paths.append(f"/usr/share/cinnamon/thumbnails/cursors/{theme_name}.png")
        preview_paths.append("/usr/share/cinnamon/thumbnails/cursors/unknown.png")
        
        # Search for first existing file
        for path in preview_paths:
            if os.path.exists(path) and os.path.isfile(path):
                return path
        
        return None

    def get_active_themes(self):
        """Gets all active themes"""
        return {
            "cursors": self.settings.get_string("cursor-theme"),
            "gtk-3.0": self.settings.get_string("gtk-theme"),
            "icons": self.settings.get_string("icon-theme"),
            "cinnamon": self.cinnamon_settings.get_string("name")
        }

    def update_active_themes(self):
        """Updates active theme button state"""
        try:
            active_themes = self.get_active_themes()

            for theme_type, buttons in self.theme_buttons.items():
                active_theme = active_themes.get(theme_type)
                for theme_name, button in buttons.items():
                    self.update_theme_indicator(button, theme_name == active_theme)
        except Exception as e:
            print(f"Error updating active themes: {e}")

    def get_theme_settings_key(self, theme_type):
        """Gets theme parameter key for a given type"""
        settings_keys = {
            "cursors": "cursor-theme",
            "gtk-3.0": "gtk-theme",
            "icons": "icon-theme",
            "cinnamon": "name"
        }
        return settings_keys.get(theme_type)

    def get_theme_settings(self, theme_type):
        """Gets parameters for a given theme type"""
        if theme_type == "cinnamon":
            return self.cinnamon_settings
        return self.settings

    def set_theme(self, theme_type, theme_name):
        """Sets theme for a given type"""
        try:
            settings = self.get_theme_settings(theme_type)
            settings_key = self.get_theme_settings_key(theme_type)
            
            if settings and settings_key:
                settings.set_string(settings_key, theme_name)
                
                # Special case for cursors
                if theme_type == "cursors":
                    self.update_cursor_theme_link(None, theme_name)
                
                return True
            return False
        except Exception as e:
            print(f"Error setting theme {theme_name} of type {theme_type}: {e}")
            return False

    def _on_theme_selected(self, theme_type, theme_name, settings_key):
        """Handles theme selection"""
        try:
            if not self.settings or not self.cinnamon_settings:
                print("Settings are not initialized correctly")
                return

            print(f"Theme {theme_name} of type {theme_type} selected")  # Debug

            if self.set_theme(theme_type, theme_name):
                # Update theme button state
                self.update_active_themes()
                
                # Reset style interface if necessary
                if hasattr(self, 'reset_look_ui'):
                    GLib.idle_add(self.reset_look_ui)
        except Exception as e:
            print(f"Error selecting theme: {e}")

    def update_theme_indicator(self, theme_button, is_active):
        """Updates active theme indicator"""
        style_context = theme_button.get_style_context()
        if is_active:
            style_context.add_class('active-theme')
            # Update indicator
            box = theme_button.get_child()
            indicator_box = box.get_children()[0]
            # Remove old indicator if exists
            for child in indicator_box.get_children():
                indicator_box.remove(child)
            # Add new indicator
            indicator = Gtk.Label()
            indicator.set_markup("<span foreground='#3584e4' size='large'>●</span>")
            indicator.set_halign(Gtk.Align.CENTER)
            indicator.set_valign(Gtk.Align.CENTER)
            indicator_box.pack_start(indicator, True, True, 0)
            indicator_box.show_all()
        else:
            style_context.remove_class('active-theme')
            # Remove indicator
            box = theme_button.get_child()
            indicator_box = box.get_children()[0]
            for child in indicator_box.get_children():
                indicator_box.remove(child)
            indicator_box.show_all()

    def get_active_theme(self, theme_type):
        """Gets active theme for a given type"""
        if theme_type == "cursors":
            return self.settings.get_string("cursor-theme")
        elif theme_type == "gtk-3.0":
            return self.settings.get_string("gtk-theme")
        elif theme_type == "icons":
            return self.settings.get_string("icon-theme")
        elif theme_type == "cinnamon":
            return self.cinnamon_settings.get_string("name")
        return None

    def get_preview_size(self, theme_type):
        """Gets preview size for a given theme type"""
        return self.PREVIEW_SIZES.get(theme_type, 48)  # Default size if not specified

    def create_theme_button(self, theme_name, theme_type, is_active, settings_key):
        """Creates theme button"""
        # Create button
        theme_button = Gtk.Button()
        theme_button.set_relief(Gtk.ReliefStyle.NONE)
        theme_button.set_tooltip_text(theme_name)
        theme_button.set_hexpand(True)
        
        # Button style
        style_context = theme_button.get_style_context()
        style_context.add_class('theme-button')
        if is_active:
            style_context.add_class('active-theme')
        
        # Horizontal container for image and label
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.set_spacing(20)
        box.set_hexpand(True)
        theme_button.add(box)

        # Active theme indicator
        indicator_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        indicator_box.set_size_request(20, -1)
        if is_active:
            indicator = Gtk.Label()
            indicator.set_markup("<span foreground='#3584e4' size='large'>●</span>")
            indicator.set_halign(Gtk.Align.CENTER)
            indicator.set_valign(Gtk.Align.CENTER)
            indicator_box.pack_start(indicator, True, True, 0)
        box.pack_start(indicator_box, False, False, 0)

        # Theme image
        image = Gtk.Image()
        preview_size = self.get_preview_size(theme_type)
        
        try:
            if theme_type == "cursors":
                image_path = self._get_cursor_preview(theme_name)
            elif theme_type == "icons":
                image_path = self._get_icon_preview(theme_name)
            else:
                image_path = self._get_theme_preview(theme_name, theme_type)
            
            if image_path and os.path.exists(image_path) and os.path.isfile(image_path):
                try:
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
                    width = pixbuf.get_width()
                    height = pixbuf.get_height()
                    
                    if width > height:
                        new_width = preview_size
                        new_height = int(height * (preview_size / width))
                    else:
                        new_height = preview_size
                        new_width = int(width * (preview_size / height))
                        
                    pixbuf = pixbuf.scale_simple(new_width, new_height, GdkPixbuf.InterpType.BILINEAR)
                    image.set_from_pixbuf(pixbuf)
                except GLib.Error as e:
                    print(f"Error loading image {image_path}: {e}")
                    image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
                    image.set_pixel_size(preview_size)
            else:
                image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
                image.set_pixel_size(preview_size)
        except Exception as e:
            print(f"Error creating theme button {theme_name}: {e}")
            image.set_from_icon_name("image-missing", Gtk.IconSize.DIALOG)
            image.set_pixel_size(preview_size)
        
        image.set_halign(Gtk.Align.START)
        image.set_valign(Gtk.Align.CENTER)
        box.pack_start(image, False, False, 0)

        # Theme label
        label = Gtk.Label()
        label.set_text(theme_name)
        label.set_line_wrap(False)
        label.set_halign(Gtk.Align.START)
        label.set_valign(Gtk.Align.CENTER)
        label.set_margin_start(10)
        box.pack_start(label, True, True, 0)

        # Connection of click
        theme_button.connect('clicked', lambda b, t=theme_name, k=settings_key: self._on_theme_selected(theme_type, t, k))
        
        return theme_button

    def create_theme_grid(self, title, themes, theme_type, settings_key):
        """Creates theme grid with one line per theme"""
        # Get preview size
        preview_size = self.get_preview_size(theme_type)

        # Get active theme
        active_theme = self.get_active_theme(theme_type)

        theme_page = SettingsPage()
        theme_page.set_margin_start(20)
        theme_page.set_margin_end(20)
        theme_page.set_margin_top(20)
        theme_page.set_margin_bottom(20)

        # Container for title
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_hexpand(True)
        header_box.set_spacing(0)
        header_box.set_margin_bottom(0)
        theme_page.add(header_box)

        # Title
        title_label = Gtk.Label()
        title_label.set_markup(f"<span size='x-large' weight='bold'>{title}</span>")
        title_label.set_halign(Gtk.Align.START)
        title_label.set_margin_start(0)
        title_label.set_margin_end(0)
        title_label.set_margin_top(0)
        title_label.set_margin_bottom(0)
        header_box.pack_start(title_label, True, True, 0)

        # Search entry
        search_entry = Gtk.Entry(placeholder_text=_("Search themes..."))
        search_entry.set_width_chars(30)
        search_entry.connect("changed", self.on_search_changed, theme_type)
        header_box.pack_end(search_entry, False, False, 0)

        # Frame for grid
        frame = Gtk.Frame()
        frame.set_shadow_type(Gtk.ShadowType.IN)
        frame_style = frame.get_style_context()
        frame_style.add_class('view')
        frame.set_hexpand(True)
        frame.set_vexpand(True)
        theme_page.add(frame)

        # ScrolledWindow for grid
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_shadow_type(Gtk.ShadowType.NONE)
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        frame.add(scrolled)

        # Main container for grid
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_box.set_hexpand(True)
        main_box.set_vexpand(True)
        main_box.set_spacing(0)
        main_box.set_margin_start(20)
        main_box.set_margin_end(20)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(20)
        scrolled.add(main_box)

        # Initialize dictionary for this theme type
        if theme_type not in self.theme_buttons:
            self.theme_buttons[theme_type] = {}

        # Add themes to grid
        for i, theme in enumerate(themes):
            theme_name = theme[0] if isinstance(theme, tuple) else theme
            theme_path = theme[1] if isinstance(theme, tuple) else None

            # Add separator before each line except the first
            if i > 0:
                separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
                separator.set_margin_top(5)
                separator.set_margin_bottom(5)
                main_box.pack_start(separator, False, False, 0)

            # Container for theme (full line)
            theme_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            theme_box.set_hexpand(True)
            theme_box.set_spacing(20)
            theme_box.set_margin_top(5)
            theme_box.set_margin_bottom(5)

            # Create theme button
            theme_button = self.create_theme_button(theme_name, theme_type, theme_name == active_theme, settings_key)
            
            # Store button in dictionary
            self.theme_buttons[theme_type][theme_name] = theme_button
            
            theme_box.pack_start(theme_button, True, True, 0)
            main_box.pack_start(theme_box, False, False, 0)

        return theme_page

    def on_search_changed(self, entry, theme_type):
        """Filters themes based on search text"""
        search_text = entry.get_text().lower()
        
        # Get active theme
        active_theme = self.get_active_theme(theme_type)
        
        # Get all buttons for this type
        if theme_type in self.theme_buttons:
            # Get main container (main_box)
            main_box = None
            for theme_name, button in self.theme_buttons[theme_type].items():
                theme_box = button.get_parent()
                if theme_box:
                    main_box = theme_box.get_parent()
                    break

            if main_box:
                # Iterate through all widgets in main container
                visible_count = 0
                for child in main_box.get_children():
                    if isinstance(child, Gtk.Separator):
                        # Hide separator if previous theme is hidden
                        if visible_count == 0:
                            child.hide()
                        else:
                            child.show()
                    else:
                        # For theme containers
                        theme_button = None
                        for button in child.get_children():
                            if isinstance(button, Gtk.Button):
                                theme_button = button
                                break
                        
                        if theme_button:
                            theme_name = theme_button.get_tooltip_text()
                            if search_text in theme_name.lower():
                                child.show()
                                visible_count += 1
                                self.update_theme_indicator(theme_button, theme_name == active_theme)
                            else:
                                child.hide()
                                visible_count = 0

    def on_nav_button_toggled(self, button, page_id):
        """Handles navigation button state change"""
        # Prevent recursion by checking if change comes from user
        if not button.get_property("active") and button.get_active():
            return

        if button.get_active():
            # Disable all other buttons without triggering their signals
            for btn_id, btn in self.nav_buttons.items():
                if btn != button:
                    btn.handler_block_by_func(self.on_nav_button_toggled)
                    btn.set_active(False)
                    btn.handler_unblock_by_func(self.on_nav_button_toggled)
            # Show corresponding page
            self.theme_stack.set_visible_child_name(page_id)
        else:
            # Prevent active button from being disabled
            button.handler_block_by_func(self.on_nav_button_toggled)
            button.set_active(True)
            button.handler_unblock_by_func(self.on_nav_button_toggled)

    def apply_css_style(self, css):
        """Applies CSS style to the application"""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(css.encode())
        style_context = Gtk.StyleContext()
        style_context.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
