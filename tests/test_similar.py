import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

from giplicado.core import audio_match
from giplicado.core.scanner import FileInfo, collect_files
from giplicado.core.similar_images import find_similar_images


def scene(seed: int, size=(800, 600)) -> Image.Image:
    rng = np.random.default_rng(seed)
    img = Image.new("RGB", size, tuple(int(c) for c in rng.integers(0, 255, 3)))
    d = ImageDraw.Draw(img)
    for _ in range(12):
        x0, y0 = rng.integers(0, size[0]), rng.integers(0, size[1])
        x1, y1 = x0 + rng.integers(50, 300), y0 + rng.integers(50, 300)
        d.ellipse((x0, y0, x1, y1), fill=tuple(int(c) for c in rng.integers(0, 255, 3)))
    return img


class SimilarImageTests(unittest.TestCase):
    def test_resized_and_reformatted_match_but_other_scene_does_not(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            a = scene(1)
            a.save(root / "original.jpg", quality=95)
            a.resize((400, 300)).save(root / "chica.png")
            a.save(root / "comprimida.webp", quality=40)
            scene(2).save(root / "otra.jpg")
            scene(3).save(root / "otra2.jpg")
            files = collect_files([root], {"foto"})
            groups = find_similar_images(files, max_distance=6)
            self.assertEqual(len(groups), 1)
            names = [f.path.name for f in groups[0].files]
            self.assertEqual(sorted(names), ["chica.png", "comprimida.webp", "original.jpg"])
            self.assertIn(names[0], ("original.jpg", "comprimida.webp"))   # mayor resolución primero
            self.assertIn("800×600", groups[0].files[0].note)


class AudioMatchTests(unittest.TestCase):
    def test_similarity_with_offset_and_noise(self):
        rng = np.random.default_rng(0)
        a = rng.integers(0, 2**32, 900, dtype=np.uint64).astype(np.uint32)
        b = a[7:].copy()                                     # 7 elementos de desfase
        flip = rng.integers(0, 2**32, len(b), dtype=np.uint64).astype(np.uint32)
        b ^= flip & rng.integers(0, 2**32, len(b), dtype=np.uint64).astype(np.uint32) \
            & rng.integers(0, 2**32, len(b), dtype=np.uint64).astype(np.uint32)  # ~12% de bits
        other = rng.integers(0, 2**32, 900, dtype=np.uint64).astype(np.uint32)
        self.assertGreater(audio_match.fp_similarity(a, b), 0.85)
        self.assertLess(audio_match.fp_similarity(a, other), 0.6)

    def test_grouping_with_fake_fpcalc(self):
        rng = np.random.default_rng(1)
        song = rng.integers(0, 2**32, 900, dtype=np.uint64).astype(np.uint32)
        other = rng.integers(0, 2**32, 900, dtype=np.uint64).astype(np.uint32)
        fps = {"cancion.mp3": (200.0, song), "cancion.flac": (200.4, song[3:]),
               "distinta.mp3": (201.0, other)}
        now = time.time()
        files = [FileInfo(Path(n), 5_000_000 if n.endswith("flac") else 3_000_000, now, "audio")
                 for n in fps]
        with mock.patch.object(audio_match, "fingerprint", lambda p, _f: fps[p.name]):
            groups = audio_match.find_same_audio(files, fpcalc="fake")
        self.assertEqual(len(groups), 1)
        self.assertEqual([f.path.name for f in groups[0].files], ["cancion.flac", "cancion.mp3"])
        self.assertIn("100% igual", groups[0].files[1].note)

    def test_missing_fpcalc_raises(self):
        with mock.patch.object(audio_match, "find_fpcalc", lambda: None):
            with self.assertRaises(FileNotFoundError):
                audio_match.find_same_audio([], fpcalc=None)


if __name__ == "__main__":
    unittest.main()
