import os
import tempfile
import unittest
from pathlib import Path

from giplicado.core.renamer import RenameRules, apply_renames, build_name, find_conflicts
from giplicado.core.scanner import PARTIAL_CHUNK, find_duplicates


class ScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, rel, data: bytes):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return p

    def test_same_content_different_names(self):
        data = os.urandom(5000)
        self.write("a/foto.jpg", data)
        self.write("b/copia de foto.JPG", data)
        self.write("b/otra.png", os.urandom(5000))      # mismo tamaño, otro contenido
        groups = find_duplicates([self.root])
        self.assertEqual(len(groups), 1)
        names = sorted(f.path.name for f in groups[0].files)
        self.assertEqual(names, ["copia de foto.JPG", "foto.jpg"])

    def test_differs_only_in_middle(self):
        size = PARTIAL_CHUNK * 4
        a = bytearray(os.urandom(size))
        b = bytearray(a)
        b[size // 2] ^= 0xFF                              # mismo inicio y final
        self.write("x.mp4", bytes(a))
        self.write("y.mp4", bytes(b))
        self.assertEqual(find_duplicates([self.root]), [])

    def test_categories_filter_and_non_media(self):
        data = os.urandom(3000)
        self.write("s1.mp3", data)
        self.write("s2.flac", data)
        self.write("doc1.txt", data)
        self.write("doc2.txt", data)
        self.assertEqual(len(find_duplicates([self.root], {"audio"})), 1)
        self.assertEqual(find_duplicates([self.root], {"video"}), [])

    def test_overlapping_roots_not_counted_twice(self):
        self.write("sub/v.mkv", b"x" * 100)
        self.assertEqual(find_duplicates([self.root, self.root / "sub"]), [])


class RenamerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_template_tokens(self):
        p = self.root / "IMG 01.JPG"
        p.write_bytes(b"x")
        r = RenameRules(template="Viaje_{n}_{nombre}", start=5, digits=3, ext_lower=True)
        self.assertEqual(build_name(p, 2, r), "Viaje_007_IMG 01.jpg")

    def test_find_replace_case_and_invalid_chars(self):
        p = self.root / "mi cancion.mp3"
        p.write_bytes(b"x")
        r = RenameRules(template="{nombre}", find=" ", replace="?", case="mayusculas")
        self.assertEqual(build_name(p, 0, r), "MI_CANCION.mp3")

    def test_swap_names_and_undo(self):
        a = self.root / "a.jpg"; a.write_bytes(b"A")
        b = self.root / "b.jpg"; b.write_bytes(b"B")
        pairs = [(a, "b.jpg"), (b, "a.jpg")]
        self.assertEqual(find_conflicts(pairs), set())
        undo, errs = apply_renames(pairs)
        self.assertFalse(errs)
        self.assertEqual((self.root / "a.jpg").read_bytes(), b"B")
        apply_renames([(new, orig.name) for new, orig in undo])
        self.assertEqual((self.root / "a.jpg").read_bytes(), b"A")

    def test_conflicts(self):
        a = self.root / "a.jpg"; a.write_bytes(b"A")
        b = self.root / "b.jpg"; b.write_bytes(b"B")
        (self.root / "existe.jpg").write_bytes(b"E")
        self.assertEqual(find_conflicts([(a, "x.jpg"), (b, "x.jpg")]), {0, 1})
        self.assertEqual(find_conflicts([(a, "existe.jpg")]), {0})


if __name__ == "__main__":
    unittest.main()
