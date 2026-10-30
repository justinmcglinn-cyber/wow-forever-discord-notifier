import hashlib
import io
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from forever_notify import updater

PREFIX = updater.DOWNLOAD_PREFIX
NEW_EXE_BYTES = b"MZ new ForeverNotify build"
NEW_SHA = hashlib.sha256(NEW_EXE_BYTES).hexdigest()


def api_reply(tag="v0.1.13", exe=True, digest=True, notes_hash=False, zip_sha=None, **extra):
    assets = []
    if exe:
        asset = {"name": "ForeverNotify.exe", "browser_download_url": f"{PREFIX}{tag}/ForeverNotify.exe"}
        if digest:
            asset["digest"] = "sha256:" + NEW_SHA
        assets.append(asset)
    if zip_sha is not None:
        assets.append({"name": f"ForeverNotify-{tag}.zip", "browser_download_url": f"{PREFIX}{tag}/ForeverNotify-{tag}.zip",
                       "digest": "sha256:" + zip_sha})
    body = f"SHA-256 of `ForeverNotify.exe` (attached, and inside the zip): `{NEW_SHA.upper()}`" if notes_hash else ""
    return {"tag_name": tag, "assets": assets, "body": body, "html_url": f"https://github.com/x/releases/tag/{tag}",
            **extra}


class FakeResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.headers = {"Content-Length": str(len(data))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def opener_for(data):
    return lambda request, timeout=None: FakeResponse(data)


class ReadingReleases(unittest.TestCase):
    def test_versions(self):
        self.assertEqual(updater.parse_version("v0.1.13"), (0, 1, 13))
        self.assertEqual(updater.parse_version("0.2"), (0, 2))
        self.assertIsNone(updater.parse_version("latest"))
        self.assertGreater((0, 1, 13), (0, 1, 9), "compared as numbers, not text")

    def test_exe_asset_with_github_digest(self):
        release = updater.latest_release(lambda url: api_reply())
        self.assertEqual((release.tag, release.version, release.is_zip, release.sha256), ("v0.1.13", (0, 1, 13), False, NEW_SHA))

    def test_falls_back_to_the_hash_in_the_release_notes(self):
        release = updater.latest_release(lambda url: api_reply(digest=False, notes_hash=True))
        self.assertEqual(release.sha256, NEW_SHA)

    def test_no_checksum_means_nothing_to_verify(self):
        self.assertEqual(updater.latest_release(lambda url: api_reply(digest=False)).sha256, "")

    def test_older_releases_with_only_a_zip(self):
        release = updater.latest_release(lambda url: api_reply(exe=False, zip_sha="ab" * 32))
        self.assertTrue(release.is_zip)
        self.assertEqual(release.sha256, "ab" * 32)

    def test_ignores_drafts_prereleases_and_foreign_downloads(self):
        self.assertIsNone(updater.latest_release(lambda url: api_reply(prerelease=True)))
        evil = api_reply()
        evil["assets"][0]["browser_download_url"] = "https://example.com/ForeverNotify.exe"
        self.assertIsNone(updater.latest_release(lambda url: evil))


class Installing(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.exe = self.dir / "ForeverNotify.exe"
        self.exe.write_bytes(b"MZ old build")

    def release(self, **kwargs):
        return updater.latest_release(lambda url: api_reply(**kwargs))

    def test_download_verify_and_swap(self):
        updater.install(self.release(), self.exe, report=lambda *_: None, opener=opener_for(NEW_EXE_BYTES))
        self.assertEqual(self.exe.read_bytes(), NEW_EXE_BYTES)
        self.assertEqual((self.dir / updater.OLD_EXE).read_bytes(), b"MZ old build")
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), [updater.EXE_NAME, updater.OLD_EXE])

    def test_wrong_checksum_changes_nothing(self):
        with self.assertRaises(updater.UpdateError):
            updater.install(self.release(), self.exe, report=lambda *_: None, opener=opener_for(b"tampered"))
        self.assertEqual(self.exe.read_bytes(), b"MZ old build")
        self.assertEqual([p.name for p in self.dir.iterdir()], [updater.EXE_NAME], "no files left behind")

    def test_zip_release(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("ForeverNotify.exe", NEW_EXE_BYTES)
            z.writestr("config.example.toml", "x")
        data = buf.getvalue()
        release = self.release(exe=False, zip_sha=hashlib.sha256(data).hexdigest())
        updater.install(release, self.exe, report=lambda *_: None, opener=opener_for(data))
        self.assertEqual(self.exe.read_bytes(), NEW_EXE_BYTES)

    def test_failed_swap_puts_the_old_exe_back(self):
        new = self.dir / updater.NEW_EXE
        new.write_bytes(NEW_EXE_BYTES)
        real_replace = Path.replace

        def replace(path, target):
            if path == new:
                raise PermissionError("locked by antivirus")
            return real_replace(path, target)

        with mock.patch.object(Path, "replace", replace), mock.patch.object(updater.time, "sleep"):
            with self.assertRaises(OSError):
                updater.replace_exe(new, self.exe)
        self.assertEqual(self.exe.read_bytes(), b"MZ old build")

    def test_leftovers_removed_on_next_start(self):
        for name in (updater.OLD_EXE, updater.NEW_EXE, updater.DOWNLOAD):
            (self.dir / name).write_bytes(b"x")
        updater.cleanup_leftovers(self.exe)
        self.assertEqual([p.name for p in self.dir.iterdir()], [updater.EXE_NAME])

    def test_relaunch_starts_a_fresh_copy(self):
        popen = mock.Mock()
        updater.relaunch(self.exe, ["run"], popen=popen)
        args, kwargs = popen.call_args
        self.assertEqual(args[0], [str(self.exe), "run"])
        self.assertEqual(kwargs["env"]["PYINSTALLER_RESET_ENVIRONMENT"], "1")


class Offering(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.exe = self.dir / "ForeverNotify.exe"
        self.exe.write_bytes(b"MZ old build")
        self.out = []
        patcher = mock.patch.object(updater, "current_version", return_value=(0, 1, 12))
        patcher.start()
        self.addCleanup(patcher.stop)

    def offer(self, answer, reply=None, frozen=True, **kwargs):
        restart = mock.Mock()
        result = updater.offer_update(self.dir, frozen, exe=self.exe, argv=["run"],
                                      ask=lambda prompt, seconds: answer, fetch=lambda url: reply or api_reply(),
                                      opener=opener_for(NEW_EXE_BYTES), restart=restart,
                                      report=self.out.append, **kwargs)
        return result, restart

    def test_yes_updates_and_restarts(self):
        result, restart = self.offer("")
        self.assertTrue(result)
        restart.assert_called_once_with(self.exe, ["run"])
        self.assertEqual(self.exe.read_bytes(), NEW_EXE_BYTES)

    def test_no_and_timeout_leave_it_alone(self):
        for answer in ("n", None):
            result, restart = self.offer(answer)
            self.assertFalse(result)
            restart.assert_not_called()
            self.assertEqual(self.exe.read_bytes(), b"MZ old build")

    def test_skip_remembers_the_version_until_asked_with_update(self):
        self.offer("s")
        asked = []
        updater.offer_update(self.dir, True, exe=self.exe, ask=lambda p, s: asked.append(p),
                             fetch=lambda url: api_reply(), report=self.out.append)
        self.assertEqual(asked, [], "a skipped version isn't offered again at start-up")
        updater.offer_update(self.dir, True, exe=self.exe, ask=lambda p, s: asked.append(p) or "n",
                             fetch=lambda url: api_reply(), report=self.out.append, force=True)
        self.assertEqual(len(asked), 1, "'update' offers it anyway")
        result, _ = self.offer("", reply=api_reply(tag="v0.1.14"))
        self.assertTrue(result, "a newer release is offered again")

    def test_up_to_date_or_offline_asks_nothing(self):
        for reply in (api_reply(tag="v0.1.12"), api_reply(tag="v0.1.11")):
            result, _ = self.offer("y", reply=reply)
            self.assertFalse(result)

        def offline(url):
            raise OSError("no network")

        self.assertFalse(updater.offer_update(self.dir, True, exe=self.exe, ask=lambda p, s: "y", fetch=offline,
                                              report=self.out.append))

    def test_running_from_source_only_tells_you(self):
        result, restart = self.offer("y", frozen=False)
        self.assertFalse(result)
        self.assertIn("git pull", self.out[-1])
        self.assertEqual(self.exe.read_bytes(), b"MZ old build")

    def test_no_console_means_no_prompt(self):
        result, restart = self.offer("y", interactive=False)
        self.assertFalse(result)
        self.assertEqual(self.exe.read_bytes(), b"MZ old build")

    def test_unverifiable_release_is_not_installed(self):
        result, _ = self.offer("y", reply=api_reply(digest=False))
        self.assertFalse(result)
        self.assertIn("download it yourself", self.out[-1])

    def test_failed_download_carries_on(self):
        result, restart = updater.offer_update(self.dir, True, exe=self.exe, ask=lambda p, s: "y",
                                               fetch=lambda url: api_reply(), opener=opener_for(b"tampered"),
                                               restart=mock.Mock(), report=self.out.append), None
        self.assertFalse(result)
        self.assertIn("Update failed", self.out[-1])
        self.assertEqual(self.exe.read_bytes(), b"MZ old build")


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "wow").mkdir()
        self.config = self.dir / "config.toml"

    def write(self, extra=""):
        self.config.write_text(f"wow_dir = '{self.dir / 'wow'}'\n{extra}\n[webhooks]\n"
                               "default = 'https://discord.com/api/webhooks/1/x'\n", encoding="utf-8")

    def main(self, *args):
        from contextlib import redirect_stdout
        from forever_notify import cli
        with mock.patch.object(cli.updater, "offer_update", return_value=False) as offer, \
                mock.patch.object(cli.app, "run") as run, mock.patch.object(cli.addon_install, "sync_and_report"), \
                redirect_stdout(io.StringIO()):
            code = cli.main(["-c", str(self.config), *args])
        return code, offer, run

    def test_start_up_checks_before_running(self):
        self.write()
        code, offer, run = self.main("run")
        self.assertEqual(code, 0)
        offer.assert_called_once()
        self.assertEqual(offer.call_args.kwargs["argv"], ["-c", str(self.config), "run"])
        run.assert_called_once()

    def test_check_can_be_turned_off(self):
        self.write("check_for_updates = false")
        code, offer, run = self.main("run")
        offer.assert_not_called()
        run.assert_called_once()

    def test_update_command_asks_and_does_not_start_watching(self):
        self.write("check_for_updates = false")
        code, offer, run = self.main("update")
        self.assertEqual(code, 0)
        self.assertTrue(offer.call_args.kwargs["force"])
        run.assert_not_called()

    def test_restart_after_update_ends_this_copy(self):
        from contextlib import redirect_stdout
        from forever_notify import cli
        self.write()
        with mock.patch.object(cli.updater, "offer_update", return_value=True), \
                mock.patch.object(cli.app, "run") as run, mock.patch.object(cli.addon_install, "sync_and_report"), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["-c", str(self.config), "run"]), 0)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
