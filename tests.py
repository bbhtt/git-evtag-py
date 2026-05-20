# ruff: noqa: S101

import argparse
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Generator
from os import environ
from pathlib import Path
from urllib.request import urlopen

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import git_evtag_py as evtag

V101_CSUM = (
    "3973d3ad28248971e6c870936012f44c512df1700cde0cf80713aced9a134fff"
    "0f71eb99d87d45fd8b6c7a6fa32ec095b3bc529d09e7774ca07cefd53b1ee802"
)
V108_CSUM = (
    "b078bd1616243c65346ff47370ddf1f2e99dda350c9093b079f24647d122d38"
    "5d8a5080a1645716dcec7530690f5537fc33f9c44e06ed3d265ff74fddf0cca74"
)

V101_TAG_LINE = f"Git-EVTag-Py-v0-SHA512: {V101_CSUM}"
V108_TAG_LINE = f"Git-EVTag-v0-SHA512: {V108_CSUM}"

V101_SHA = "295a273a2af003e57edd369f7f7e83155c36a074"
REPO_URL = "https://github.com/bbhtt/git-evtag-py.git"


def _run_git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _make_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    _run_git(tmp, "init", str(repo))
    _run_git(repo, "config", "user.name", "Test User")
    _run_git(repo, "config", "user.email", "test@example.com")
    (repo / "file.txt").write_text("hello\n")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "init")
    return repo


def _build_tree_entry(mode: str, name: str, sha_hex: str) -> bytes:
    return f"{mode} {name}\0".encode() + bytes.fromhex(sha_hex)


_GPG_KEY_URL = (
    "https://keyserver.ubuntu.com/pks/lookup"
    "?op=get&search=0xd26d753395009db2b3b260940c3251a24745e484"
)


def _import_gpg_key() -> None:
    local = Path(__file__).parent / "pub_key.asc"
    key_url = environ.get("KEY_URL", _GPG_KEY_URL)
    if local.exists():
        key_data = local.read_text()
    else:
        with urlopen(key_url) as response:  # noqa: S310
            key_data = response.read().decode("utf-8")
    subprocess.run(
        ["gpg", "--import"],
        input=key_data,
        text=True,
        check=True,
        capture_output=True,
    )


def _make_args(**kwargs: object) -> argparse.Namespace:
    defaults: dict[str, object] = {
        "rev": None,
        "verify": None,
        "sign": None,
        "tag_msg": None,
        "in_place": False,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestCheckGitVersion:
    def _make_result(self, stdout: str) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout)

    def test_sufficient_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            evtag, "run_git", lambda *_, **__: self._make_result("git version 2.9.0\n")
        )
        assert evtag.check_git_version()

    def test_newer_version(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            evtag, "run_git", lambda *_, **__: self._make_result("git version 2.47.1\n")
        )
        assert evtag.check_git_version()

    def test_too_old(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            evtag, "run_git", lambda *_, **__: self._make_result("git version 1.8.3\n")
        )
        assert not evtag.check_git_version()


class TestParseTreeContent:
    def test_single_blob(self) -> None:
        sha = "a" * 40
        assert evtag.parse_tree_content(
            _build_tree_entry("100644", "README.md", sha)
        ) == [("blob", sha, "README.md")]

    def test_single_tree(self) -> None:
        sha = "b" * 40
        assert evtag.parse_tree_content(_build_tree_entry("40000", "src", sha)) == [
            ("tree", sha, "src")
        ]

    def test_submodule_commit(self) -> None:
        sha = "c" * 40
        assert evtag.parse_tree_content(_build_tree_entry("160000", "sub", sha)) == [
            ("commit", sha, "sub")
        ]

    def test_executable_blob(self) -> None:
        sha = "d" * 40
        assert evtag.parse_tree_content(_build_tree_entry("100755", "run.sh", sha)) == [
            ("blob", sha, "run.sh")
        ]

    def test_symlink_blob(self) -> None:
        sha = "e" * 40
        assert evtag.parse_tree_content(_build_tree_entry("120000", "link", sha)) == [
            ("blob", sha, "link")
        ]

    def test_multiple_entries(self) -> None:
        sha1, sha2 = "a" * 40, "b" * 40
        content = _build_tree_entry("100644", "a.txt", sha1) + _build_tree_entry(
            "40000", "dir", sha2
        )
        assert evtag.parse_tree_content(content) == [
            ("blob", sha1, "a.txt"),
            ("tree", sha2, "dir"),
        ]


class TestRunCommand:
    def test_success_capture(self) -> None:
        result = evtag.run_command(["echo", "hi"], capture_output=True)
        assert result is not None
        assert result.stdout.strip() == "hi"

    def test_failure_returns_none(self) -> None:
        assert evtag.run_command(["false"]) is None

    def test_cwd_respected(self, tmp_path: Path) -> None:
        result = evtag.run_command(["pwd"], capture_output=True, cwd=tmp_path)
        assert result is not None
        assert result.stdout.strip() == str(tmp_path)

    def test_warn_does_not_raise(self) -> None:
        assert evtag.run_command(["false"], warn=True) is None

    def test_no_capture_returns_result(self) -> None:
        assert evtag.run_command(["true"]) is not None


class TestRunGit:
    def test_run_git(self) -> None:
        result = evtag.run_git(["--version"], capture_output=True)
        assert result is not None
        assert "git version " in result.stdout

    def test_invalid_subcommand(self, tmp_path: Path) -> None:
        assert evtag.run_git(["not-a-real-subcommand"], repo=tmp_path) is None

    def test_repo_arg_sets_cwd(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = evtag.run_git(["rev-parse", "HEAD"], repo=repo, capture_output=True)
        assert result is not None
        assert len(result.stdout.strip()) == 40


class TestIsGitDirectory:
    def test_nonexistent(self, tmp_path: Path) -> None:
        assert not evtag.is_git_directory(tmp_path / "nope")

    def test_plain_directory(self, tmp_path: Path) -> None:
        assert not evtag.is_git_directory(tmp_path)

    def test_git_repo(self, tmp_path: Path) -> None:
        assert evtag.is_git_directory(_make_repo(tmp_path))


class TestValidateArgs:
    def test_no_args(self) -> None:
        assert evtag.validate_args(_make_args())

    def test_verify_and_sign_invalid(self) -> None:
        assert not evtag.validate_args(_make_args(verify="v1", sign="v2"))

    def test_rev_with_verify_invalid(self) -> None:
        assert not evtag.validate_args(_make_args(rev="HEAD", verify="v1"))

    def test_rev_with_sign_invalid(self) -> None:
        assert not evtag.validate_args(_make_args(rev="HEAD", sign="v1"))

    def test_tag_msg_without_sign_invalid(self) -> None:
        assert not evtag.validate_args(_make_args(tag_msg="msg"))

    def test_tag_msg_with_sign_valid(self) -> None:
        assert evtag.validate_args(_make_args(sign="v1", tag_msg="msg"))

    def test_sign_alone(self) -> None:
        assert evtag.validate_args(_make_args(sign="v1"))

    def test_verify_alone(self) -> None:
        assert evtag.validate_args(_make_args(verify="v1"))

    def test_rev_alone(self) -> None:
        assert evtag.validate_args(_make_args(rev="HEAD"))

    def test_in_place_alone(self) -> None:
        assert evtag.validate_args(_make_args(in_place=True))


class TestEnsureGitRev:
    def test_head(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        sha = evtag.ensure_git_rev("HEAD", repo)
        assert sha is not None
        assert len(sha) == 40

    def test_invalid_rev(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        assert evtag.ensure_git_rev("refs/tags/nonexistent", repo) is None


class TestComputeChecksum:
    def test_returns_sha512_hex(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        csum = evtag.compute_checksum(repo, "HEAD")
        assert csum is not None
        assert len(csum) == 128
        assert all(c in "0123456789abcdef" for c in csum)

    def test_deterministic(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        assert evtag.compute_checksum(repo, "HEAD") == evtag.compute_checksum(
            repo, "HEAD"
        )

    def test_invalid_rev_returns_none(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        assert evtag.compute_checksum(repo, "refs/tags/nonexistent") is None

    def test_changes_between_commits(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        csum1 = evtag.compute_checksum(repo, "HEAD")
        (repo / "extra.txt").write_text("more\n")
        _run_git(repo, "add", ".")
        _run_git(repo, "commit", "-m", "second")
        assert evtag.compute_checksum(repo, "HEAD") != csum1


class TestPrepareClone:
    def test_in_place_returns_src(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = evtag.prepare_clone(repo, "HEAD", in_place=True)
        assert result is not None
        tmpdir, work_repo = result
        assert tmpdir is None
        assert work_repo == repo

    def test_clone_creates_repo(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        result = evtag.prepare_clone(repo, "HEAD", in_place=False)
        assert result is not None
        tmpdir, work_repo = result
        assert tmpdir is not None
        assert work_repo != repo
        assert (work_repo / ".git").is_dir()
        tmpdir.cleanup()

    def test_invalid_rev_returns_none(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        assert (
            evtag.prepare_clone(repo, "refs/tags/nonexistent", in_place=False) is None
        )


class TestExtractChecksumFromTag:
    def test_missing_tag_returns_none(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        assert evtag.extract_checksum_from_tag(repo, "nonexistent") is None

    def test_tag_without_evtag_returns_none(self, tmp_path: Path) -> None:
        repo = _make_repo(tmp_path)
        subprocess.run(
            ["git", "tag", "-a", "v-plain", "-m", "no evtag here"],
            cwd=repo,
            check=True,
            capture_output=True,
            env={**environ, "EVTAG_NO_GPG_SIGN": "true"},
        )
        assert evtag.extract_checksum_from_tag(repo, "v-plain") is None


def _find_repo() -> Path | None:
    candidate = Path(__file__).parent.resolve()
    while candidate != candidate.parent:
        if (candidate / ".git").is_dir():
            result = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=candidate,
                capture_output=True,
                text=True,
                check=False,
            )
            if "git-evtag-py" in result.stdout:
                return candidate
        candidate = candidate.parent
    return None


@pytest.fixture(scope="module")
def remote_repo() -> Generator[tuple[Path, str], None, None]:
    self_repo = _find_repo()
    if self_repo is not None:
        tmpdir = tempfile.mkdtemp()
        repo = Path(tmpdir) / "test_repo"
        _run_git(Path(tmpdir), "clone", "--no-local", str(self_repo), str(repo))
        _run_git(repo, "config", "user.name", "bbhtt")
        _run_git(repo, "config", "user.email", "bbhtt.zn0i8@slmail.me")
        yield repo, tmpdir
        shutil.rmtree(tmpdir)
        return

    tmpdir = tempfile.mkdtemp()
    repo = Path(tmpdir) / "test_repo"
    _run_git(Path(tmpdir), "clone", REPO_URL, str(repo))
    _run_git(repo, "config", "user.name", "bbhtt")
    _run_git(repo, "config", "user.email", "bbhtt.zn0i8@slmail.me")
    yield repo, tmpdir
    shutil.rmtree(tmpdir)


@pytest.fixture(scope="module")
def gpg_key() -> None:
    _import_gpg_key()


@pytest.mark.integration
class TestIntegrationCompute:
    def test_at_v101(self, remote_repo: tuple[Path, str]) -> None:
        repo, _ = remote_repo
        _run_git(repo, "checkout", "v1.0.1")
        assert _run_git(repo, "rev-parse", "HEAD") == V101_SHA
        assert evtag.compute_checksum(repo, "HEAD") == V101_CSUM

    def test_rev_tag(self, remote_repo: tuple[Path, str]) -> None:
        repo, _ = remote_repo
        _run_git(repo, "checkout", "main")
        assert evtag.compute_checksum(repo, "v1.0.1") == V101_CSUM

    def test_rev_sha(self, remote_repo: tuple[Path, str]) -> None:
        repo, _ = remote_repo
        _run_git(repo, "checkout", "main")
        assert evtag.compute_checksum(repo, V101_SHA) == V101_CSUM

    def test_in_place(self, remote_repo: tuple[Path, str]) -> None:
        repo, _ = remote_repo
        _run_git(repo, "checkout", "v1.0.1")
        result = evtag.prepare_clone(repo, "HEAD", in_place=True)
        assert result is not None
        _, work_repo = result
        assert evtag.compute_checksum(work_repo, "HEAD") == V101_CSUM

    def test_at_v108(self, remote_repo: tuple[Path, str]) -> None:
        repo, _ = remote_repo
        _run_git(repo, "checkout", "v1.0.8")
        assert evtag.compute_checksum(repo, "HEAD") == V108_CSUM


@pytest.mark.integration
class TestIntegrationVerify:
    def test_signed_tag_passes(
        self,
        remote_repo: tuple[Path, str],
        gpg_key: None,  # noqa: ARG002
    ) -> None:
        repo, _ = remote_repo
        tag_csum = evtag.extract_checksum_from_tag(repo, "v1.0.8")
        assert tag_csum is not None
        result = evtag.prepare_clone(repo, "v1.0.8", in_place=True)
        assert result is not None
        _, work_repo = result
        calc = evtag.compute_checksum(work_repo, "v1.0.8")
        assert evtag.verify_tag(repo, "v1.0.8", tag_csum, calc or "")

    def test_mismatched_checksum_fails(
        self,
        remote_repo: tuple[Path, str],
        gpg_key: None,  # noqa: ARG002
    ) -> None:
        repo, _ = remote_repo
        tag_csum = evtag.extract_checksum_from_tag(repo, "v1.0.8")
        assert tag_csum is not None
        assert not evtag.verify_tag(repo, "v1.0.8", tag_csum, "deadbeef" * 16)


@pytest.mark.integration
class TestIntegrationRelativeSubmodule:
    def test_relative_submodule_url_resolves(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "protocol.file.allow")
        monkeypatch.setenv("GIT_CONFIG_VALUE_0", "always")

        sub_remote = tmp_path / "sub_remote"
        sub_remote.mkdir()
        _run_git(sub_remote, "init", "--bare", str(sub_remote))

        sub_work = tmp_path / "sub_work"
        sub_work.mkdir()
        _run_git(tmp_path, "clone", str(sub_remote), str(sub_work))
        _run_git(sub_work, "config", "user.name", "Test User")
        _run_git(sub_work, "config", "user.email", "test@example.com")

        (sub_work / "sub.txt").write_text("sub\n")

        _run_git(sub_work, "add", ".")
        _run_git(sub_work, "commit", "-m", "sub init")
        _run_git(sub_work, "push", "origin", "HEAD:main")

        _run_git(sub_remote, "symbolic-ref", "HEAD", "refs/heads/main")

        sub_sha = _run_git(sub_work, "rev-parse", "HEAD")

        super_remote = tmp_path / "super_remote"
        super_remote.mkdir()
        _run_git(super_remote, "init", "--bare", str(super_remote))

        super_work = tmp_path / "super_work"
        super_work.mkdir()

        _run_git(tmp_path, "clone", str(super_remote), str(super_work))

        _run_git(super_work, "config", "user.name", "Test User")
        _run_git(super_work, "config", "user.email", "test@example.com")

        (super_work / "README").write_text("init\n")

        _run_git(super_work, "add", "README")
        _run_git(super_work, "commit", "-m", "initial")
        _run_git(super_work, "push", "origin", "HEAD:main")

        _run_git(super_remote, "symbolic-ref", "HEAD", "refs/heads/main")

        subprocess.run(
            [
                "git",
                "-c",
                "protocol.file.allow=always",
                "submodule",
                "add",
                str(sub_remote),
                "sub",
            ],
            cwd=super_work,
            check=True,
            capture_output=True,
        )

        gitmodules = super_work / ".gitmodules"

        gitmodules.write_text(
            gitmodules.read_text().replace(
                str(sub_remote),
                "../sub_remote",
            )
        )

        _run_git(super_work, "add", ".")
        _run_git(super_work, "commit", "-m", "add submodule")
        _run_git(super_work, "push", "origin", "HEAD:main")

        local_clone = tmp_path / "local_clone"

        _run_git(tmp_path, "clone", str(super_remote), str(local_clone))

        _run_git(local_clone, "config", "user.name", "Test User")
        _run_git(local_clone, "config", "user.email", "test@example.com")

        result = evtag.prepare_clone(
            local_clone,
            "HEAD",
            in_place=False,
        )

        assert result is not None

        tmpdir, work_repo = result

        try:
            sub_dir = work_repo / "sub"

            assert sub_dir.is_dir()
            assert (sub_dir / "sub.txt").is_file()

            assert _run_git(sub_dir, "rev-parse", "HEAD") == sub_sha

        finally:
            if tmpdir:
                tmpdir.cleanup()


@pytest.mark.integration
class TestIntegrationSign:
    def test_sign_with_message(self, remote_repo: tuple[Path, str]) -> None:
        repo, _ = remote_repo
        _run_git(repo, "checkout", "v1.0.1")
        csum = evtag.compute_checksum(repo, "HEAD")
        assert csum is not None
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setenv("EVTAG_NO_GPG_SIGN", "true")
                assert evtag.sign_tree_checksum(
                    repo, "v-test-unit", csum, tag_msg="Test sign message"
                )
            lines = {
                line.strip()
                for line in _run_git(repo, "show", "v-test-unit").splitlines()
            }
            assert "Test sign message" in lines
            assert any(line.endswith(V101_CSUM) for line in lines)
        finally:
            subprocess.run(
                ["git", "tag", "-d", "v-test-unit"],
                check=False,
                cwd=repo,
                capture_output=True,
            )

    def test_sign_with_file_path(
        self, remote_repo: tuple[Path, str], tmp_path: Path
    ) -> None:
        repo, _ = remote_repo
        _run_git(repo, "checkout", "v1.0.8")
        csum = evtag.compute_checksum(repo, "HEAD")
        assert csum is not None
        msg_file = tmp_path / "tagmsg.txt"
        exp_msg = "Test sign from file"
        msg_file.write_text(exp_msg)
        try:
            with pytest.MonkeyPatch.context() as mp:
                mp.setenv("EVTAG_NO_GPG_SIGN", "true")
                assert evtag.sign_tree_checksum(
                    repo, "v-test-file", csum, tag_msg=str(msg_file)
                )
            lines = {
                line.strip()
                for line in _run_git(repo, "show", "v-test-file").splitlines()
            }
            assert exp_msg in lines
            assert any(line.endswith(V108_CSUM) for line in lines)
        finally:
            subprocess.run(
                ["git", "tag", "-d", "v-test-file"],
                check=False,
                cwd=repo,
                capture_output=True,
            )

    def test_sign_existing_tag_fails(self, remote_repo: tuple[Path, str]) -> None:
        repo, _ = remote_repo
        csum = evtag.compute_checksum(repo, "HEAD")
        assert csum is not None
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("EVTAG_NO_GPG_SIGN", "true")
            assert not evtag.sign_tree_checksum(repo, "v1.0.8", csum, tag_msg="fail")

    def test_sign_with_local_gpg_key(
        self,
        remote_repo: tuple[Path, str],
        gpg_key: None,  # noqa: ARG002
    ) -> None:
        repo, _ = remote_repo
        _run_git(repo, "checkout", "v1.0.1")

        result = subprocess.run(
            ["gpg", "--list-secret-keys", "--with-colons"],
            capture_output=True,
            text=True,
            check=True,
        )
        key_id: str | None = None
        for line in result.stdout.splitlines():
            if line.startswith("sec"):
                parts = line.split(":")
                if len(parts) > 4 and parts[4]:
                    key_id = parts[4]
                    break

        if not key_id:
            pytest.skip("No local GPG secret key available")

        _run_git(repo, "config", "user.signingkey", key_id)
        csum = evtag.compute_checksum(repo, "HEAD")
        assert csum is not None
        try:
            assert evtag.sign_tree_checksum(
                repo, "v-test-gpg", csum, tag_msg="GPG sign test"
            )
            verify = subprocess.run(
                ["git", "tag", "-v", "v-test-gpg"],
                check=False,
                cwd=repo,
                capture_output=True,
                text=True,
            )
            assert verify.returncode == 0
            lines = {
                line.strip()
                for line in _run_git(repo, "show", "v-test-gpg").splitlines()
            }
            assert "GPG sign test" in lines
            assert any(line.endswith(V101_CSUM) for line in lines)
        finally:
            subprocess.run(
                ["git", "tag", "-d", "v-test-gpg"],
                check=False,
                cwd=repo,
                capture_output=True,
            )
