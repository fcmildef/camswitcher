#!/usr/bin/env python3
"""
Licensed under GPL-3.0 see LICENCSE

Simple Video Switcher (Debian 12 / Ubuntu 24 compatible)
- Two physical webcams as inputs
- One virtual webcam (v4l2loopback) as output
- GTK4 UI with live preview and one-click switching

Tested on: Debian 12 (Bookworm) and Ubuntu 24.04

Dependencies (Debian 12 / ubuntu 24):
Debian 12:
 sudo apt update && sudo apt install -y \
    python3-gi python3-gst-1.0 gir1.2-gtk-4.0 gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-gl \
    gstreamer1.0-gtk3 gstreamer1.0-gl v4l2loopback-dkms v4l2loopback-utils
   

Ubuntu 24:
sudo apt update && sudo apt install -y \
    python3-gi python3-gst-1.0 gir1.2-gtk-4.0 gir1.2-gstreamer-1.0 \
    gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad gstreamer1.0-plugins-ugly gstreamer1.0-gl \
    gstreamer1.0-gtk3 gstreamer1.0-gtk4 gstreamer1.0-gl v4l2loopback-dkms v4l2loopback-utils

(Recommended) give your user webcam access and re-login:
  sudo usermod -aG video "$USER"

Load v4l2loopback (once per boot or persist via modprobe.d):
  sudo modprobe v4l2loopback video_nr=10 card_label="VirtualCam" exclusive_caps=1
  # Your virtual camera will be /dev/video10 (change video_nr if you prefer)

Run:
  python3 video_switcher.py
"""

import sys
import os
import glob
import json
from pathlib import Path
from gi.repository import Gtk, Gio, GObject, Gst, Gdk  # Gdk added for CSS injection

APP_ID = "org.example.VideoSwitcher"
CONFIG_DIR = Path.home() / ".config" / "video-switcher"
CONFIG_FILE = CONFIG_DIR / "defaults.json"

def list_video_devices():
    # List /dev/video* devices
    devs = sorted(glob.glob("/dev/video*"))
    return devs

class SwitcherWindow(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app)
        self.set_title("Simple Video Switcher")
        self.set_resizable(True)
        self.set_default_size(360, 320)
        self.set_size_request(320, 280)
        self.set_auto_startup_notification(True)

        # GST init
        Gst.init(None)

        self.pipeline = None
        self.input_selector = None
        self.preview_sink = None
        self.pad_cam1 = None
        self.pad_cam2 = None
        self.active_cam = 1

        # UI
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        self.set_child(outer)

        self.cmb_cam1 = Gtk.DropDown.new_from_strings(list_video_devices())
        self.cmb_cam2 = Gtk.DropDown.new_from_strings(list_video_devices())
        self.cmb_out = Gtk.DropDown.new_from_strings(list_video_devices())
        self.settings_dialog = None

        # Preview area
        self.preview_box = Gtk.Box()
        self.preview_box.set_hexpand(True)
        self.preview_box.set_vexpand(True)
        outer.append(self.preview_box)

        # Status bar for errors (Debian 12 friendly, no fancy dialogs needed)
        self.status = Gtk.Label(label="")
        self.status.set_xalign(0.0)
        outer.append(self.status)

        # --- Control Buttons (modern, larger) ---
        # Create control row first so we can append later in one place
        ctrl = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, halign=Gtk.Align.CENTER)
        outer.append(ctrl)

        # Buttons with friendly icons
        self.btn_start = Gtk.Button(label="▶  Start")
        self.btn_stop = Gtk.Button(label="⏹  Stop")
        self.btn_cam1 = Gtk.Button(label="📷  Switch to Cam 1")
        self.btn_cam2 = Gtk.Button(label="📷  Switch to Cam 2")

        # Larger, unified styling via CSS
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(b"""
        button.control {
            font-size: 18px;
            padding: 12px 24px;
            margin: 4px;
            border-radius: 12px;
            min-width: 200px;
            background: #1e293b;
            color: white;
            transition: background 120ms ease-in-out;
        }
        button.control:hover {
            background: #334155;
        }
        button.control:active {
            background: #3b82f6;
        }
        button.control:disabled {
            opacity: 0.5;
        }
        .status-indicator {
            font-size: 18px;
            font-weight: bold;
        }
        .status-indicator.status-idle {
            color: #94a3b8;
        }
        .status-indicator.status-ok {
            color: #22c55e;
        }
        .status-indicator.status-error {
            color: #ef4444;
        }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_USER,
        )
        for b in (self.btn_start, self.btn_stop, self.btn_cam1, self.btn_cam2):
            b.get_style_context().add_class("control")

        # Append to control row
        ctrl.append(self.btn_start)
        ctrl.append(self.btn_stop)
        self.cam1_status = None
        self.cam2_status = None
        self.cam1_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.cam1_row.append(self.btn_cam1)
        self.cam2_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.cam2_row.append(self.btn_cam2)
        self._set_all_cam_status("idle")
        ctrl.append(self.cam1_row)
        ctrl.append(self.cam2_row)

        # Defaults & options row
        defaults_row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, halign=Gtk.Align.CENTER)
        outer.append(defaults_row)
        self.chk_preview = Gtk.CheckButton()
        self.chk_preview.set_active(False)
        self.chk_autoload = Gtk.CheckButton(label="Auto-load defaults on start")
        self.btn_settings = Gtk.Button(label="Settings…")
        self.btn_settings.connect("clicked", self.on_open_settings)
        self.btn_settings.get_style_context().add_class("control")
        self.btn_settings.set_hexpand(False)
        self.btn_settings.set_halign(Gtk.Align.CENTER)
        defaults_row.append(self.btn_settings)

        # initial sensitivity
        self.btn_stop.set_sensitive(False)
        self.btn_cam1.set_sensitive(False)
        self.btn_cam2.set_sensitive(False)

        # wire up signals
        self.btn_start.connect("clicked", self.on_start)
        self.btn_stop.connect("clicked", self.on_stop)
        self.btn_cam1.connect("clicked", lambda *_: self.switch_to(1))
        self.btn_cam2.connect("clicked", lambda *_: self.switch_to(2))

        # Try loading defaults
        self.load_defaults(autoload=True)

        self.connect("close-request", self.on_close)

    # --- UI helpers ---
    def _get_selected(self, cmb: Gtk.DropDown):
        model = cmb.get_model()
        idx = cmb.get_selected()
        if idx < 0:
            return None
        # Gtk.DropDown + Gtk.StringList returns a StringObject; fetch the plain str
        try:
            return model.get_string(idx)
        except Exception:
            # Fallback for other models
            item = model[idx]
            return str(getattr(item, "get_string", lambda: item)())

    def on_refresh(self, *_):
        devs = list_video_devices()
        for cmb in (self.cmb_cam1, self.cmb_cam2, self.cmb_out):
            cmb.set_model(Gtk.StringList.new(devs))
            # Don't auto-select blindly; keep current selection if present
            if cmb.get_selected() < 0 and len(devs):
                cmb.set_selected(0)

    def on_start(self, *_):
        cam1 = self._get_selected(self.cmb_cam1)
        cam2 = self._get_selected(self.cmb_cam2)
        out = self._get_selected(self.cmb_out)

        if not (cam1 and cam2 and out):
            self._error("Please select two input cameras and one virtual output device.")
            return
        if cam1 == out or cam2 == out:
            self._error("Virtual output must be a v4l2loopback device (e.g., /dev/video10), not one of the input webcams.")
            return
        if cam1 == cam2:
            self._error("Cam 1 and Cam 2 must be different devices.")
            return
        if not os.access(out, os.W_OK):
            self._error(f"No write access to {out}. Add your user to the 'video' group and re-login.")
            return

        ok, err = self.build_pipeline(cam1, cam2, out)
        if not ok:
            self._error(err or "Failed to create pipeline")
            self.teardown_pipeline()
            self._set_all_cam_status("error")
            return

        ret = self.pipeline.set_state(Gst.State.PLAYING)
        if ret == Gst.StateChangeReturn.FAILURE:
            self._error("Failed to start GStreamer pipeline.")
            self.teardown_pipeline()
            self._set_all_cam_status("error")
            return

        self.btn_start.set_sensitive(False)
        self.btn_stop.set_sensitive(True)
        self.btn_cam1.set_sensitive(True)
        self.btn_cam2.set_sensitive(True)
        self._set_all_cam_status("ok")
        self._error("")

    def on_stop(self, *_):
        self.teardown_pipeline()
        self.btn_start.set_sensitive(True)
        self.btn_stop.set_sensitive(False)
        self.btn_cam1.set_sensitive(False)
        self.btn_cam2.set_sensitive(False)
        self._set_all_cam_status("idle")

    def on_close(self, *_):
        self.teardown_pipeline()
        self._set_all_cam_status("idle")
        return False

    def _error(self, msg: str):
        self.status.set_text(msg)
        if msg:
            print("[Error]", msg, file=sys.stderr)

    # --- GStreamer ---
    # --- Defaults persistence ---
    def on_save_defaults(self, *_):
        data = {
            "cam1": self._get_selected(self.cmb_cam1),
            "cam2": self._get_selected(self.cmb_cam2),
            "out": self._get_selected(self.cmb_out),
            "preview": self.chk_preview.get_active(),
            "autoload": self.chk_autoload.get_active(),
        }
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            self._error("Defaults saved.")
        except Exception as e:
            self._error(f"Failed to save defaults: {e}")

    def on_clear_defaults(self, *_):
        try:
            if CONFIG_FILE.exists():
                CONFIG_FILE.unlink()
            self._error("Defaults cleared.")
        except Exception as e:
            self._error(f"Failed to clear defaults: {e}")

    def _select_value(self, cmb: Gtk.DropDown, value: str):
        if value is None:
            return
        model = cmb.get_model()
        # Gtk.StringList exposes get_n_items + get_string
        try:
            n = model.get_n_items()
            for i in range(n):
                if model.get_string(i) == value:
                    cmb.set_selected(i)
                    return
        except Exception:
            # Fallback for other models
            for i in range(len(model)):
                item = model[i]
                if str(getattr(item, "get_string", lambda: item)()) == value:
                    cmb.set_selected(i)
                    return

    def load_defaults(self, autoload=False):
        # Ensure current device list is fresh
        self.on_refresh()
        if not CONFIG_FILE.exists():
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._select_value(self.cmb_cam1, data.get("cam1"))
            self._select_value(self.cmb_cam2, data.get("cam2"))
            self._select_value(self.cmb_out, data.get("out"))
            self.chk_preview.set_active(bool(data.get("preview", True)))
            self.chk_autoload.set_active(bool(data.get("autoload", False)))
            if autoload and not data.get("autoload", False):
                return
            # Autoload enabled → selections already set
        except Exception as e:
            self._error(f"Failed to load defaults: {e}")

    def build_pipeline(self, dev1: str, dev2: str, out_dev: str):
        self.pipeline = Gst.Pipeline.new("switcher")

        self.input_selector = Gst.ElementFactory.make("input-selector", "isel")
        if not self.input_selector:
            return False, "Missing GStreamer 'input-selector' (install gstreamer1.0-plugins-bad)."

        preview_enabled = bool(self.chk_preview.get_active())
        preview_fallback_label = None
        self.preview_sink = None
        q_preview = None
        preview_convert = None
        if preview_enabled:
            # Preview sink: prefer embedded gtk4 sink, fallback to external sink if unavailable
            self.preview_sink = Gst.ElementFactory.make("gtk4paintablesink", "preview")
            if not self.preview_sink:
                self.preview_sink = Gst.ElementFactory.make("glimagesink", "preview")
                if not self.preview_sink:
                    self.preview_sink = Gst.ElementFactory.make("autovideosink", "preview")
                if not self.preview_sink:
                    return False, ("No preview sink available. Install gstreamer1.0-gtk4 "
                                   "for embedded preview or gstreamer1.0-gl for external preview.")
                preview_fallback_label = "Preview opens in a separate window (GTK4 sink missing)"

        # Output sink to v4l2loopback
        out_convert = Gst.ElementFactory.make("videoconvert", "outconvert")
        out_sink = Gst.ElementFactory.make("v4l2sink", "outsink")
        if not out_sink:
            return False, "Missing 'v4l2sink' (install base/good plugins)."
        out_sink.set_property("device", out_dev)

        # Tee to split to preview and virtual device
        tee = Gst.ElementFactory.make("tee", "tee")
        q_out = Gst.ElementFactory.make("queue", "qout")
        if preview_enabled:
            q_preview = Gst.ElementFactory.make("queue", "qprev")
            preview_convert = Gst.ElementFactory.make("videoconvert", "prevconvert")

        # Build two input branches with caps to ensure identical formats for the selector
        def make_input_branch(name: str, device: str):
            src = Gst.ElementFactory.make("v4l2src", f"src_{name}")
            if not src:
                raise RuntimeError("Missing 'v4l2src'.")
            src.set_property("device", device)
            conv = Gst.ElementFactory.make("videoconvert", f"conv_{name}")
            scale = Gst.ElementFactory.make("videoscale", f"scale_{name}")
            rate = Gst.ElementFactory.make("videorate", f"rate_{name}")
            caps = Gst.ElementFactory.make("capsfilter", f"caps_{name}")
            caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=YUY2,framerate=30/1,width=1280,height=720"))
            q = Gst.ElementFactory.make("queue", f"q_{name}")
            return [src, conv, scale, rate, caps, q]

        try:
            br1 = make_input_branch("cam1", dev1)
            br2 = make_input_branch("cam2", dev2)
        except RuntimeError as e:
            return False, str(e)

        # Add all elements to pipeline
        pipeline_elements = br1 + br2 + [self.input_selector, tee, q_out, out_convert, out_sink]
        if preview_enabled:
            pipeline_elements.extend([q_preview, preview_convert, self.preview_sink])
        for el in pipeline_elements:
            if el:
                self.pipeline.add(el)

        # Helper to link a simple chain
        def link_chain(elems):
            for i in range(len(elems) - 1):
                if not Gst.Element.link(elems[i], elems[i+1]):
                    return False
            return True

        # Link each input branch and request a sink pad on the selector
        def link_branch(branch):
            if not link_chain(branch):
                return None
            q = branch[-1]
            # request pad using modern API if available
            try:
                sinkpad = self.input_selector.request_pad_simple("sink_%u")
            except Exception:
                sinkpad = self.input_selector.get_request_pad("sink_%u")
            if not sinkpad:
                return None
            if q.get_static_pad("src").link(sinkpad) != Gst.PadLinkReturn.OK:
                return None
            return sinkpad

        self.pad_cam1 = link_branch(br1)
        self.pad_cam2 = link_branch(br2)
        if not self.pad_cam1 or not self.pad_cam2:
            return False, "Failed to link inputs to selector."

        # selector -> tee
        if not Gst.Element.link(self.input_selector, tee):
            return False, "Failed to link selector to tee."

        # Manually link tee to both branches via request pads
        def tee_link(tee_el, queue_el):
            try:
                srcpad = tee_el.request_pad_simple("src_%u")
            except Exception:
                srcpad = tee_el.get_request_pad("src_%u")
            if not srcpad:
                return False
            sinkpad = queue_el.get_static_pad("sink")
            if not sinkpad:
                return False
            return srcpad.link(sinkpad) == Gst.PadLinkReturn.OK

        if preview_enabled:
            if not tee_link(tee, q_preview):
                return False, "Failed to request/link tee pad for preview."
        if not tee_link(tee, q_out):
            return False, "Failed to request/link tee pad for output."

        # Finish each branch
        if preview_enabled:
            if not link_chain([q_preview, preview_convert, self.preview_sink]):
                return False, "Failed to link preview branch."
        if not link_chain([q_out, out_convert, out_sink]):
            return False, "Failed to link output branch."

        # Embed preview only for gtk4paintablesink (GTK4-safe)
        try:
            for c in self.preview_box.get_children():
                self.preview_box.remove(c)
            if not preview_enabled:
                self.preview_box.append(Gtk.Label(label="Preview disabled."))
            elif self.preview_sink and self.preview_sink.get_factory().get_name() == "gtk4paintablesink":
                paintable = self.preview_sink.get_property("paintable")
                if paintable:
                    picture = Gtk.Picture.new_for_paintable(paintable)
                    self.preview_box.append(picture)
            else:
                # Non-embedded sinks render their own window; keep UI area informative
                message = preview_fallback_label or "Preview opens in a separate window."
                self.preview_box.append(Gtk.Label(label=message))
        except Exception:
            pass

        # Set initial active pad
        self.input_selector.set_property("active-pad", self.pad_cam1)
        self.active_cam = 1
        return True, None

    def teardown_pipeline(self):
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.input_selector = None
            self.pad_cam1 = None
            self.pad_cam2 = None

    def switch_to(self, cam_idx: int):
        if not self.pipeline or not self.input_selector:
            return
        pad = self.pad_cam1 if cam_idx == 1 else self.pad_cam2
        if not pad:
            self._set_cam_status(cam_idx, "error")
            return
        self.input_selector.set_property("active-pad", pad)
        self.active_cam = cam_idx
        self._set_cam_status(cam_idx, "ok")
        print(f"Switched to Cam {cam_idx}")

    def _create_status_label(self, state: str):
        label = Gtk.Label(label="●")
        try:
            label.set_margin_start(6)
            label.set_margin_end(6)
            ctx = label.get_style_context()
            ctx.add_class("status-indicator")
            ctx.add_class(f"status-{state}")
        except Exception:
            pass
        return label

    def _set_cam_status(self, cam_idx: int, state: str):
        row_attr = "cam1_row" if cam_idx == 1 else "cam2_row"
        if not hasattr(self, row_attr):
            return
        label_attr = "cam1_status" if cam_idx == 1 else "cam2_status"
        row = getattr(self, row_attr)
        old_label = getattr(self, label_attr, None)
        if old_label:
            try:
                row.remove(old_label)
            except Exception:
                pass
        new_label = self._create_status_label(state)
        row.append(new_label)
        setattr(self, label_attr, new_label)

    def _set_all_cam_status(self, state: str):
        self._set_cam_status(1, state)
        self._set_cam_status(2, state)

    def _on_primary_button_size(self, widget, allocation):
        if not getattr(self, "btn_settings", None):
            return
        width = allocation.width
        if width > 0:
            self.btn_settings.set_size_request(width, -1)

    def on_open_settings(self, *_):
        if not self.settings_dialog:
            self.settings_dialog = self._create_settings_dialog()
        self.on_refresh()
        self.settings_dialog.present()

    def _create_settings_dialog(self):
        dialog = Gtk.Window()
        dialog.set_title("Device Settings")
        dialog.set_transient_for(self)
        dialog.set_modal(True)
        dialog.set_default_size(400, 220)

        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        dialog.set_child(outer)

        def add_row(label_text, widget):
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            row.append(Gtk.Label(label=label_text))
            row.append(widget)
            outer.append(row)

        add_row("Cam 1:", self.cmb_cam1)
        add_row("Cam 2:", self.cmb_cam2)
        add_row("Virtual Out:", self.cmb_out)
        add_row("Show preview:", self.chk_preview)

        autoload_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        autoload_row.append(self.chk_autoload)
        outer.append(autoload_row)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", self.on_refresh)
        save_btn = Gtk.Button(label="Save Defaults")
        save_btn.connect("clicked", self.on_save_defaults)
        clear_btn = Gtk.Button(label="Clear Defaults")
        clear_btn.connect("clicked", self.on_clear_defaults)
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda *_: dialog.hide())
        buttons.append(refresh_btn)
        buttons.append(save_btn)
        buttons.append(clear_btn)
        buttons.append(close_btn)
        outer.append(buttons)

        dialog.connect("close-request", self._on_settings_close)
        return dialog

    def _on_settings_close(self, *_):
        if self.settings_dialog:
            self.settings_dialog.hide()
            return True
        return False

class SwitcherApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_activate(self):
        if not self.props.active_window:
            win = SwitcherWindow(self)
            win.present()
        else:
            self.props.active_window.present()

if __name__ == "__main__":
    app = SwitcherApp()
    app.run(sys.argv)
