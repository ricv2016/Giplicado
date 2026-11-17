"""Pruebas de la versión 0.3.0: caché de huellas y videos parecidos."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import av
import numpy as np

from giplicado.core import similar_images, similar_videos
from giplicado.core.cache import FingerprintCache
from giplicado.core.scanner import collect_files, find_duplicates
from tests.test_similar import scene


def make_video(path: Path, seed: int, size=(640, 360), seconds=10, fps=10, codec="mpeg4"):
    """Video con una escena distinta cada segundo (simula cortes de cámara)."""
    with av.open(str(path), "w") as out:
        st = out.add_stream(codec, rate=fps)
        st.width, st.height = size
        st.pix_fmt = "yuv420p"
        st.bit_rate = 800_000
        for sec in range(seconds):
            img = scene(seed * 100 + sec, (640, 360)).resize(size)   # misma escena, otro tamaño
            arr = np.asarray(img)
            for k in range(fps):
                shifted = np.roll(arr, k * 2, axis=1)          # leve movimiento
                frame = av.VideoFrame.from_ndarray(shifted, format="rgb24")
                for pkt in st.encode(frame):
                    out.mux(pkt)
        for pkt in st.encode():
            out.mux(pkt)


class SimilarVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        make_video(root / "boda_original.mp4", 1)
        make_video(root / "boda_whatsapp.avi", 1, size=(320, 180))
        make_video(root / "cumpleaños.mp4", 2)
        cls.root = root

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_same_video_other_resolution_and_format(self):
        files = collect_files([self.root], {"video"})
        groups = similar_videos.find_similar_videos(files)
        self.assertEqual(len(groups), 1)
        names = [f.path.name for f in groups[0].files]
        self.assertEqual(names, ["boda_original.mp4", "boda_whatsapp.avi"])   # mejor resolución primero
        self.assertIn("640×360", groups[0].files[0].note)

    def test_signature_shape(self):
        fi = next(f for f in collect_files([self.root], {"video"}) if f.path.name == "boda_original.mp4")
        dur, w, h, hashes = similar_videos.video_signature(fi)
        self.assertAlmostEqual(dur, 10, delta=0.5)
        self.assertEqual(len(hashes), 9)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "fotos"
        self.root.mkdir()
        self.cache = FingerprintCache(Path(self.tmp.name) / "cache.db")

    def tearDown(self):
        self.cache.close()
        self.tmp.cleanup()

    def test_second_scan_uses_cache(self):
        scene(1).save(self.root / "a.jpg")
        scene(1).resize((400, 300)).save(self.root / "b.png")
        files = collect_files([self.root], {"foto"})
        g1 = similar_images.find_similar_images(files, cache=self.cache)
        self.assertEqual(self.cache.stats()[0], 2)
        # segunda vez: si intentara recalcular, fallaría
        with mock.patch.object(similar_images, "image_phash", side_effect=AssertionError("sin caché")):
            files = collect_files([self.root], {"foto"})
            errors = []
            g2 = similar_images.find_similar_images(files, cache=self.cache, errors=errors)
        self.assertEqual(errors, [])
        self.assertEqual(len(g1), len(g2), 1)

    def test_modified_file_is_recomputed(self):
        p = self.root / "a.jpg"
        scene(1).save(p)
        fi = collect_files([self.root], {"foto"})[0]
        self.cache.put_many("phash", [(fi.path, fi.size, fi.mtime, (1, 2, 3))])
        self.assertEqual(self.cache.get(fi.path, "phash", fi.size, fi.mtime), (1, 2, 3))
        scene(2).save(p)                                   # el archivo cambia
        os.utime(p, (fi.mtime + 10, fi.mtime + 10))
        fi2 = collect_files([self.root], {"foto"})[0]
        self.assertIsNone(self.cache.get(fi2.path, "phash", fi2.size, fi2.mtime))

    def test_exact_scan_with_cache(self):
        data = os.urandom(5000)
        (self.root / "x.jpg").write_bytes(data)
        (self.root / "copia.jpg").write_bytes(data)
        self.assertEqual(len(find_duplicates([self.root], cache=self.cache)), 1)
        self.assertEqual(len(find_duplicates([self.root], cache=self.cache)), 1)
        self.assertEqual(self.cache.stats()[0], 2)
        self.cache.clear()
        self.assertEqual(self.cache.stats()[0], 0)


if __name__ == "__main__":
    unittest.main()
