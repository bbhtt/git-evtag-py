# ruff: noqa: S101

import shutil
import subprocess
import tempfile
from os import environ
from pathlib import Path
from urllib.request import urlopen

import pytest


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *list(args)],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def clone_repo(
    url: str = "https://github.com/bbhtt/git-evtag-py.git",
) -> tuple[Path, str]:
    tmpdir = tempfile.mkdtemp()
    repo = Path(tmpdir) / "test_repo"
    run_git(Path(tmpdir), "clone", url, str(repo))
    return repo, tmpdir


def import_gpg_key() -> None:
    key_url = environ.get("KEY_URL")

    if key_url and key_url.startswith("https://"):
        with urlopen(key_url) as response:  # noqa: S310
            key_data = response.read().decode("utf-8")
    else:
        key_data = Path("pub_key.asc").read_text()

    subprocess.run(
        ["gpg", "--import"],
        input=key_data,
        text=True,
        check=True,
        capture_output=True,
    )


def test_flow() -> None:
    import_gpg_key()
    repo, tmpdir = clone_repo()
    try:
        assert (repo / ".git").is_dir()

        run_git(repo, "config", "user.name", "bbhtt")
        run_git(repo, "config", "user.email", "bbhtt.zn0i8@slmail.me")

        run_git(repo, "checkout", "v1.0.1")
        sha = run_git(repo, "rev-parse", "HEAD")
        assert sha == "295a273a2af003e57edd369f7f7e83155c36a074"

        expected_evtag = (
            "Git-EVTag-v0-SHA512: "
            "3973d3ad28248971e6c870936012f44c512df1700cde0cf80713aced9a134fff"
            "0f71eb99d87d45fd8b6c7a6fa32ec095b3bc529d09e7774ca07cefd53b1ee802"
        )

        assert run_git(repo, "evtag") == expected_evtag

        run_git(repo, "checkout", "main")
        for ref in ("v1.0.1", sha):
            assert run_git(repo, "evtag", "--rev", ref) == expected_evtag

        run_git(repo, "evtag", "--verify", "v1.0.8")
        with pytest.raises(subprocess.CalledProcessError):
            run_git(repo, "evtag", "--verify", "v1.0.1")

        run_git(repo, "checkout", "v1.0.1")
        run_git(repo, "evtag", "--sign", "v-test", "-m", "Testing evtag in automation")
        tag_msg = run_git(repo, "show", "v-test")
        lines: set[str] = {line.strip() for line in tag_msg.splitlines()}
        assert "Testing evtag in automation" in lines
        assert expected_evtag in lines

        expected_evtag = (
            "Git-EVTag-v0-SHA512: "
            "b078bd1616243c65346ff47370ddf1f2e99dda350c9093b079f24647d122d38"
            "5d8a5080a1645716dcec7530690f5537fc33f9c44e06ed3d265ff74fddf0cca74"
        )
        run_git(repo, "checkout", "v1.0.8")
        msg_file = repo / "tagmsg.txt"
        exp_msg = "Testing evtag tagging using tag message file"
        msg_file.write_text(exp_msg)
        run_git(repo, "evtag", "--sign", "v-test-2", "-F", str(msg_file))
        lines_t: set[str] = {
            line.strip() for line in run_git(repo, "show", "v-test-2").splitlines()
        }
        assert exp_msg in lines_t
        assert expected_evtag in lines_t
    finally:
        shutil.rmtree(tmpdir)
