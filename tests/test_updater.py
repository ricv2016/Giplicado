import hashlib
import io
import json
import unittest
from unittest import mock

from giplicado import updater

INSTALLER = b"MZ" + b"x" * 300_000
SHA = hashlib.sha256(INSTALLER).hexdigest()


def release(tag="v0.2.0", sha=SHA, **extra):
    return {
        "tag_name": tag, "draft": False, "prerelease": False,
        "body": "- Nueva función", "html_url": "https://github.com/u/r/releases/tag/" + tag,
        "assets": [
            {"name": f"Giplicado-{tag[1:]}-instalador.exe", "size": len(INSTALLER),
             "browser_download_url": "https://dl/inst.exe"},
            {"name": f"Giplicado-{tag[1:]}-instalador.exe.sha256", "size": 80,
             "browser_download_url": "https://dl/inst.sha256"},
        ], **extra,
    }


class FakeResp(io.BytesIO):
    def __init__(self, data: bytes):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def fake_get(rel, sha_text=None):
    def _get(url, timeout=15):
        if "api.github.com" in url:
            return FakeResp(json.dumps(rel).encode())
        if url.endswith(".sha256"):
            return FakeResp((sha_text or f"{SHA}  inst.exe").encode())
        return FakeResp(INSTALLER)
    return _get


class UpdaterTests(unittest.TestCase):
    def test_version_compare(self):
        self.assertTrue(updater.is_newer("v0.2.0", "0.1.0"))
        self.assertTrue(updater.is_newer("v0.10.0", "0.9.9"))
        self.assertFalse(updater.is_newer("v0.1.0", "0.1.0"))
        self.assertFalse(updater.is_newer("v0.0.9", "0.1.0"))

    def test_check_finds_newer(self):
        with mock.patch.object(updater, "_get", fake_get(release())):
            info = updater.check_for_update("u/r", "0.1.0")
        self.assertEqual(info.version, "0.2.0")
        self.assertTrue(info.sha256_url.endswith(".sha256"))

    def test_check_up_to_date_and_prerelease(self):
        with mock.patch.object(updater, "_get", fake_get(release("v0.1.0"))):
            self.assertIsNone(updater.check_for_update("u/r", "0.1.0"))
        with mock.patch.object(updater, "_get", fake_get(release("v0.3.0", prerelease=True))):
            self.assertIsNone(updater.check_for_update("u/r", "0.1.0"))

    def test_download_verifies_sha256(self):
        with mock.patch.object(updater, "_get", fake_get(release())):
            info = updater.check_for_update("u/r", "0.1.0")
            path = updater.download_installer(info)
        self.assertEqual(path.read_bytes(), INSTALLER)
        path.unlink()

    def test_download_rejects_corrupted(self):
        with mock.patch.object(updater, "_get", fake_get(release(), sha_text="00" * 32)):
            info = updater.check_for_update("u/r", "0.1.0")
            with self.assertRaises(ValueError):
                updater.download_installer(info)


if __name__ == "__main__":
    unittest.main()
