import os
import threading

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib, Gio

from . import devices as devices_mod
from . import writer
from . import iso_mode

MODE_DD = 0
MODE_ISO = 1


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="MUFUS", default_width=560, default_height=520)

        self.image_path: str | None = None
        self.selected_device: devices_mod.Device | None = None
        self.device_list: list[devices_mod.Device] = []

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle.new("MUFUS", "MUFUS is not Rufus"))

        about_btn = Gtk.Button(icon_name="help-about-symbolic")
        about_btn.set_tooltip_text("Acerca de MUFUS")
        about_btn.connect("clicked", self.on_about_clicked)
        header.pack_end(about_btn)

        toolbar_view.add_top_bar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16,
                        margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)

        group = Adw.PreferencesGroup(title="Imagen y dispositivo")
        root.append(group)

        # Image row
        self.image_row = Adw.ActionRow(title="Imagen ISO/IMG", subtitle="Ninguna seleccionada")
        browse_btn = Gtk.Button(label="Elegir...")
        browse_btn.set_valign(Gtk.Align.CENTER)
        browse_btn.connect("clicked", self.on_browse_clicked)
        self.image_row.add_suffix(browse_btn)
        group.add(self.image_row)

        # Mode row
        mode_model = Gtk.StringList()
        mode_model.append("DD Image — clonado directo (ISOs híbridas de Linux)")
        mode_model.append("ISO Image — extraer y reconstruir (instaladores de Windows, solo UEFI)")
        self.mode_dropdown = Gtk.DropDown(model=mode_model)
        self.mode_dropdown.set_valign(Gtk.Align.CENTER)
        self.mode_dropdown.connect("notify::selected", self.on_mode_changed)
        mode_row = Adw.ActionRow(title="Modo")
        mode_row.add_suffix(self.mode_dropdown)
        group.add(mode_row)

        # Volume label row (ISO mode only)
        self.label_row = Adw.EntryRow(title="Etiqueta de volumen (modo ISO)")
        self.label_row.set_text("USB")
        self.label_row.set_visible(False)
        group.add(self.label_row)

        # Device row
        self.device_dropdown = Gtk.DropDown()
        self.device_dropdown.set_valign(Gtk.Align.CENTER)
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_valign(Gtk.Align.CENTER)
        refresh_btn.connect("clicked", lambda *_: self.refresh_devices())

        device_row = Adw.ActionRow(title="Dispositivo USB")
        device_row.add_suffix(self.device_dropdown)
        device_row.add_suffix(refresh_btn)
        group.add(device_row)

        # Verify switch
        self.verify_row = Adw.SwitchRow(title="Verificar después de escribir",
                                         subtitle="Relee el dispositivo y compara sha256 (recomendado)")
        self.verify_row.set_active(True)
        group.add(self.verify_row)

        # Write button
        self.write_btn = Gtk.Button(label="Escribir")
        self.write_btn.add_css_class("suggested-action")
        self.write_btn.add_css_class("pill")
        self.write_btn.set_halign(Gtk.Align.CENTER)
        self.write_btn.connect("clicked", self.on_write_clicked)
        root.append(self.write_btn)

        # Progress
        self.progress = Gtk.ProgressBar(show_text=True)
        root.append(self.progress)

        self.status_label = Gtk.Label(label="Listo.", xalign=0)
        root.append(self.status_label)

        # Log
        log_frame = Gtk.ScrolledWindow(vexpand=True)
        log_frame.set_min_content_height(160)
        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer, editable=False,
                                      monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR)
        log_frame.set_child(self.log_view)
        root.append(log_frame)

        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(root)
        toolbar_view.set_content(self.toast_overlay)
        self.set_content(toolbar_view)

        self.refresh_devices()

    # ---------- helpers ----------

    def on_about_clicked(self, _btn) -> None:
        about = Adw.AboutDialog.new()
        about.set_application_name("MUFUS")
        about.set_application_icon("drive-removable-media")
        about.set_developer_name("tostada105")
        about.set_version("0.1")
        about.set_comments("MUFUS is not Rufus.\n\nCreador de USBs booteables nativo de Linux: "
                            "clonado directo (modo DD) o extracción/reconstrucción para "
                            "instaladores de Windows (modo ISO, arranque UEFI).")
        about.set_license_type(Gtk.License.MIT_X11)
        about.present(self)

    def notify_done(self, message: str, is_error: bool = False) -> None:
        toast = Adw.Toast.new(message)
        toast.set_timeout(0 if is_error else 6)
        self.toast_overlay.add_toast(toast)

        notif = Gio.Notification.new("MUFUS")
        notif.set_body(message)
        notif.set_priority(Gio.NotificationPriority.URGENT if is_error else Gio.NotificationPriority.NORMAL)
        self.get_application().send_notification("mufus-job", notif)

    def log(self, text: str) -> None:
        end = self.log_buffer.get_end_iter()
        self.log_buffer.insert(end, text + "\n")
        mark = self.log_buffer.create_mark(None, self.log_buffer.get_end_iter(), False)
        self.log_view.scroll_to_mark(mark, 0.0, False, 0, 0)

    def set_busy(self, busy: bool) -> None:
        self.write_btn.set_sensitive(not busy)
        self.device_dropdown.set_sensitive(not busy)

    def refresh_devices(self) -> None:
        self.device_list = devices_mod.list_removable_devices()
        model = Gtk.StringList()
        if not self.device_list:
            model.append("(no hay dispositivos USB removibles)")
        for d in self.device_list:
            model.append(d.label)
        self.device_dropdown.set_model(model)
        self.device_dropdown.set_sensitive(bool(self.device_list))

    def on_browse_clicked(self, _btn) -> None:
        dialog = Gtk.FileChooserNative.new(
            "Selecciona una imagen ISO o IMG", self, Gtk.FileChooserAction.OPEN,
            "Abrir", "Cancelar",
        )
        filt = Gtk.FileFilter()
        filt.set_name("Imágenes de disco (*.iso, *.img)")
        filt.add_pattern("*.iso")
        filt.add_pattern("*.img")
        dialog.add_filter(filt)
        dialog.connect("response", self.on_file_chosen)
        dialog.show()
        self._file_dialog = dialog  # keep alive

    def on_file_chosen(self, dialog, response) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            gfile = dialog.get_file()
            path = gfile.get_path()
            self.image_path = path
            size_mb = os.path.getsize(path) / (1024 * 1024)
            self.image_row.set_subtitle(f"{path} ({size_mb:.0f} MB)")
            base = os.path.splitext(os.path.basename(path))[0]
            self.label_row.set_text(iso_mode.sanitize_fat_label(base))
        self._file_dialog = None

    def on_mode_changed(self, *_args) -> None:
        is_iso_mode = self.mode_dropdown.get_selected() == MODE_ISO
        self.label_row.set_visible(is_iso_mode)
        self.verify_row.set_visible(not is_iso_mode)

    def selected_device_obj(self) -> devices_mod.Device | None:
        idx = self.device_dropdown.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self.device_list):
            return None
        return self.device_list[idx]

    # ---------- write flow ----------

    def on_write_clicked(self, _btn) -> None:
        if not self.image_path:
            self.status_label.set_text("Selecciona primero una imagen ISO/IMG.")
            return
        device = self.selected_device_obj()
        if device is None:
            self.status_label.set_text("Selecciona un dispositivo USB.")
            return

        mode = self.mode_dropdown.get_selected()
        image_size = os.path.getsize(self.image_path)
        if mode == MODE_DD and image_size > device.size_bytes:
            self.status_label.set_text("La imagen es más grande que el dispositivo seleccionado.")
            return

        self.confirm_and_write(device, image_size, mode)

    def confirm_and_write(self, device: devices_mod.Device, image_size: int, mode: int) -> None:
        dialog = Adw.MessageDialog.new(
            self,
            "¿Borrar todo en este dispositivo?",
            f"Se escribirá:\n{self.image_path}\n\nen:\n{device.label}\n\n"
            "TODOS los datos en ese dispositivo se perderán permanentemente.",
        )
        dialog.add_response("cancel", "Cancelar")
        dialog.add_response("write", "Escribir")
        dialog.set_response_appearance("write", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_d, response):
            if response == "write":
                if mode == MODE_DD:
                    self.start_dd_write_thread(device, image_size)
                else:
                    self.start_iso_write_thread(device)
        dialog.connect("response", on_response)
        dialog.present()

    def start_dd_write_thread(self, device: devices_mod.Device, image_size: int) -> None:
        self.set_busy(True)
        self.log_buffer.set_text("")
        do_verify = self.verify_row.get_active()
        image_path = self.image_path

        def worker():
            try:
                GLib.idle_add(self.status_label.set_text, "Calculando checksum de la imagen...")
                expected_sha = writer.sha256_file(
                    image_path,
                    progress_cb=lambda p: GLib.idle_add(self.update_progress, p.fraction, "Leyendo imagen"),
                ) if do_verify else None

                GLib.idle_add(self.status_label.set_text, "Desmontando particiones...")
                writer.unmount_partitions(device, log_cb=lambda m: GLib.idle_add(self.log, m))

                GLib.idle_add(self.status_label.set_text, "Escribiendo...")
                writer.write_image(
                    image_path, device.path,
                    progress_cb=lambda p: GLib.idle_add(self.update_progress, p.fraction, "Escribiendo"),
                    log_cb=lambda m: GLib.idle_add(self.log, m),
                )

                if do_verify:
                    GLib.idle_add(self.status_label.set_text, "Verificando...")
                    GLib.idle_add(self.update_progress, 1.0, "Verificando (puede tardar)")
                    ok = writer.verify_device(
                        device.path, image_size, expected_sha,
                        log_cb=lambda m: GLib.idle_add(self.log, m),
                    )
                    if ok:
                        GLib.idle_add(self.status_label.set_text, "Listo — verificación OK.")
                        GLib.idle_add(self.notify_done, "USB creado y verificado correctamente.", False)
                    else:
                        msg = "¡ADVERTENCIA! La verificación no coincide. El USB puede estar dañado."
                        GLib.idle_add(self.status_label.set_text, msg)
                        GLib.idle_add(self.notify_done, msg, True)
                else:
                    GLib.idle_add(self.status_label.set_text, "Listo.")
                    GLib.idle_add(self.notify_done, "USB creado correctamente.", False)
            except writer.WriterError as e:
                GLib.idle_add(self.status_label.set_text, f"Error: {e}")
                GLib.idle_add(self.log, f"ERROR: {e}")
                GLib.idle_add(self.notify_done, f"Falló la escritura del USB: {e}", True)
            finally:
                GLib.idle_add(self.set_busy, False)

        threading.Thread(target=worker, daemon=True).start()

    def start_iso_write_thread(self, device: devices_mod.Device) -> None:
        self.set_busy(True)
        self.log_buffer.set_text("")
        image_path = self.image_path
        label = self.label_row.get_text() or "USB"

        def worker():
            try:
                GLib.idle_add(self.status_label.set_text, "Preparando USB (modo ISO)...")
                iso_mode.write_iso_image(
                    image_path, device.path, label,
                    progress_cb=lambda p: GLib.idle_add(self.update_progress, p.fraction, "Copiando archivos"),
                    log_cb=lambda m: GLib.idle_add(self.log, m),
                )
                GLib.idle_add(self.status_label.set_text, "Listo — USB de arranque UEFI creado.")
                GLib.idle_add(self.notify_done, "USB de arranque UEFI creado correctamente.", False)
            except writer.WriterError as e:
                GLib.idle_add(self.status_label.set_text, f"Error: {e}")
                GLib.idle_add(self.log, f"ERROR: {e}")
                GLib.idle_add(self.notify_done, f"Falló la escritura del USB: {e}", True)
            finally:
                GLib.idle_add(self.set_busy, False)

        threading.Thread(target=worker, daemon=True).start()

    def update_progress(self, fraction: float, label: str) -> None:
        self.progress.set_fraction(fraction)
        self.progress.set_text(f"{label} — {fraction * 100:.0f}%")


class MufusApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="mx.tostada105.mufus")

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = MainWindow(self)
        win.present()


def main():
    app = MufusApp()
    app.run()


if __name__ == "__main__":
    main()
