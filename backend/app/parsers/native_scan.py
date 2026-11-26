"""Bounded Annex B marker scanning for the Windows portable build."""
import ctypes
from pathlib import Path
import sys


class Marker(ctypes.Structure):
    _fields_ = [('offset', ctypes.c_size_t), ('prefix', ctypes.c_size_t)]


def load_scan(path):
    scan = ctypes.CDLL(str(path)).gb_scan_annex_b
    scan.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_size_t,
                     ctypes.POINTER(Marker), ctypes.c_size_t]
    scan.restype = ctypes.c_size_t
    return scan


def iter_markers(data, scan):
    batch = (Marker * 256)()
    start = 0
    while start < len(data):
        count = scan(data, len(data), start, batch, len(batch))
        for i in range(count):
            yield batch[i].offset, batch[i].prefix
        if count < len(batch):
            break
        last = batch[count - 1]
        start = last.offset + last.prefix


scan = None
if sys.platform == 'win32' and hasattr(sys, '_MEIPASS'):
    library = Path(sys._MEIPASS) / 'gb28181_scan.dll'
    if library.is_file():
        scan = load_scan(library)
