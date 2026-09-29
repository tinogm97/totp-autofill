"""Escáner de QR con la webcam (GStreamer + libzbar).

La imagen se muestra en un widget GTK y, en paralelo, cada ~150 ms se pasa un
fotograma en escala de grises a ``qr.decode_gray``. Cada texto nuevo se
entrega a ``on_codes`` en el hilo principal de GTK.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

import gi

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
from gi.repository import GLib, Gst, GstVideo  # noqa: E402

from . import qr  # noqa: E402

SCAN_INTERVAL_S = 0.15


class CameraError(RuntimeError):
    pass


def _init() -> None:
    if not Gst.is_initialized():
        Gst.init(None)


def list_cameras() -> list[tuple[str, Gst.Device]]:
    """Cámaras disponibles: ``(nombre, dispositivo)``, las V4L2 primero."""
    _init()
    monitor = Gst.DeviceMonitor.new()
    monitor.add_filter("Video/Source", None)
    monitor.start()
    devices = monitor.get_devices() or []
    monitor.stop()

    def api(device: Gst.Device) -> str:
        props = device.get_properties()
        return props.get_string("device.api") if props and props.has_field("device.api") else ""

    # PipeWire y V4L2 pueden listar la misma cámara: se prefieren las V4L2.
    v4l2 = [d for d in devices if api(d) == "v4l2"]
    chosen = v4l2 or devices

    def label(device: Gst.Device) -> str:
        # Portátiles con cámara normal + infrarroja: mismo nombre, distinta ruta.
        props = device.get_properties()
        path = props.get_string("api.v4l2.path") if props and props.has_field("api.v4l2.path") else ""
        return f"{device.get_display_name()} ({path})" if path else device.get_display_name()

    return [(label(d), d) for d in chosen]


class CameraScanner:
    """Muestra la cámara y lee QR. ``widget`` es el visor para meter en la ventana.

    ``source`` (para tests) sustituye a la cámara por cualquier descripción de
    GStreamer, p. ej. ``filesrc location=qr.png ! decodebin ! imagefreeze``.
    """

    def __init__(self, on_codes: Callable[[list[str]], None], *,
                 device: Gst.Device | None = None, source: str | None = None) -> None:
        _init()
        self._on_codes = on_codes
        self._seen: set[str] = set()
        self._last_scan = 0.0
        self._lock = threading.Lock()

        if source is not None:
            src = Gst.parse_bin_from_description(source, True)
        elif device is not None:
            src = device.create_element(None)
        else:
            src = Gst.ElementFactory.make("autovideosrc", None)
        if src is None:
            raise CameraError("No se pudo abrir la cámara")

        self.pipeline = Gst.Pipeline.new("qr-scanner")
        convert = Gst.ElementFactory.make("videoconvert", None)
        tee = Gst.ElementFactory.make("tee", None)
        view_queue = Gst.ElementFactory.make("queue", None)
        view_convert = Gst.ElementFactory.make("videoconvert", None)
        view = Gst.ElementFactory.make("gtksink", None)
        scan_queue = Gst.ElementFactory.make("queue", None)
        scan_convert = Gst.ElementFactory.make("videoconvert", None)
        caps = Gst.ElementFactory.make("capsfilter", None)
        sink = Gst.ElementFactory.make("appsink", None)
        elements = [src, convert, tee, view_queue, view_convert, view,
                    scan_queue, scan_convert, caps, sink]
        if any(e is None for e in elements):
            raise CameraError("Faltan componentes de GStreamer (gstreamer1.0-gtk3 y "
                              "gstreamer1.0-plugins-base)")

        scan_queue.set_property("leaky", 2)  # descarta fotogramas viejos
        scan_queue.set_property("max-size-buffers", 1)
        caps.set_property("caps", Gst.Caps.from_string("video/x-raw,format=GRAY8"))
        sink.set_property("emit-signals", True)
        sink.set_property("max-buffers", 1)
        sink.set_property("drop", True)
        sink.set_property("sync", False)
        sink.connect("new-sample", self._on_sample)

        for element in elements:
            self.pipeline.add(element)
        src.link(convert)
        convert.link(tee)
        tee.link(view_queue)
        view_queue.link(view_convert)
        view_convert.link(view)
        tee.link(scan_queue)
        scan_queue.link(scan_convert)
        scan_convert.link(caps)
        caps.link(sink)

        self.widget = view.get_property("widget")
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        self.error: str | None = None
        self.on_error: Callable[[str], None] = lambda message: None

    def start(self) -> None:
        if self.pipeline.set_state(Gst.State.PLAYING) == Gst.StateChangeReturn.FAILURE:
            raise CameraError("No se pudo iniciar la cámara (¿la está usando otra aplicación?)")

    def stop(self) -> None:
        self.pipeline.set_state(Gst.State.NULL)
        self.pipeline.get_bus().remove_signal_watch()

    def _on_error(self, _bus, message) -> None:
        error, _debug = message.parse_error()
        self.error = error.message
        self.on_error(error.message)

    def _on_sample(self, sink) -> Gst.FlowReturn:
        sample = sink.emit("pull-sample")
        now = time.monotonic()
        if sample is None or now - self._last_scan < SCAN_INTERVAL_S:
            return Gst.FlowReturn.OK
        self._last_scan = now
        info = GstVideo.VideoInfo.new_from_caps(sample.get_caps())
        buffer = sample.get_buffer()
        ok, mapped = buffer.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            width, height, stride = info.width, info.height, info.stride[0]
            data = bytes(mapped.data)
        finally:
            buffer.unmap(mapped)
        if stride != width:  # filas con relleno: se compactan
            data = b"".join(data[y * stride: y * stride + width] for y in range(height))
        codes = qr.decode_gray(width, height, data)
        with self._lock:
            new = [c for c in codes if c not in self._seen]
            self._seen.update(new)
        if new:
            GLib.idle_add(self._on_codes, new)
        return Gst.FlowReturn.OK
