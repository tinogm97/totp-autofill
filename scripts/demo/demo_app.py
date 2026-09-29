"""La app de TOTP Autofill para la demo: ventanas centradas y cámara simulada.

La «cámara» es una foto fija de un móvil mostrando el QR de exportación
(camera-frame.jpg, cuentas y secretos falsos): nunca se abre la webcam real.
"""
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from totp_autofill import camera, chrome_setup, gui, import_dialog  # noqa: E402

FRAME = HERE / "camera-frame.jpg"


class FakeCamera(camera.CameraScanner):
    """Enseña la foto como vídeo y no «lee» el QR hasta pasados 2 s."""

    def __init__(self, on_codes, **_kwargs):
        self._start = time.monotonic()
        super().__init__(on_codes, source=f"filesrc location={FRAME} ! jpegdec ! "
                                          "videoconvert ! imagefreeze")

    def _on_sample(self, sink):
        if time.monotonic() - self._start < 2.2:
            sink.emit("pull-sample")
            return camera.Gst.FlowReturn.OK
        return super()._on_sample(sink)


camera.list_cameras = lambda: [("Cámara integrada (/dev/video0)", None)]
# La barra de estado como en un equipo ya configurado (atajo y Chrome listos).
gui.keybinding.current = lambda: "<Control><Alt>2"
gui.chrome_setup.running_browsers = lambda: [
    chrome_setup.BrowserProcess(1, "/opt/google/chrome/chrome", "", True)]
camera.CameraScanner = FakeCamera

_main_init = gui.MainWindow.__init__
_import_init = import_dialog.ImportDialog.__init__


def main_init(self, *args, **kwargs):
    _main_init(self, *args, **kwargs)
    self.set_default_size(720, 450)
    self.move(280, 120)


def import_init(self, *args, **kwargs):
    _import_init(self, *args, **kwargs)
    self.move(320, 12)


gui.MainWindow.__init__ = main_init
import_dialog.ImportDialog.__init__ = import_init
sys.exit(gui.run())
