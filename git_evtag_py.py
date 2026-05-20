#!/usr/bin/env python3

# SPDX-License-Identifier: LGPL-2.0-or-later
# Original: https://github.com/cgwalters/git-evtag/blob/main/src/git-evtag-compute-py
# Copyright (C) 2026 bbhtt <bbhtt@bbhtt.in>
# Copyright (C) 2015 Colin Walters <walters@verbum.org>

import argparse
import hashlib
import logging
import re
import subprocess
import tempfile
import types
from os import environ, unlink
from pathlib import Path
from subprocess import CompletedProcess
from typing import IO, Self

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

MIN_GIT_VERSION = (2, 9, 0)

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG": "''",
    "LC_ALL": "C",
    "LANG": "C",
    "LANGUAGE": "C",
}

__version__ = "2.0.0"


def run_command(
    command: list[str],
    check: bool = True,
    capture_output: bool = False,
    cwd: Path | None = None,
    message: str | None = None,
    warn: bool = False,
    env: dict[str, str] | None = None,
) -> CompletedProcess[str] | None:
    try:
        return subprocess.run(
            command,
            check=check,
            stdout=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            stderr=subprocess.PIPE if capture_output else subprocess.DEVNULL,
            text=True,
            cwd=cwd,
            env=env,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.strip() if e.stderr else ""
        log_func = logging.warning if warn else logging.error
        if message:
            log_func("%s: %s", message, stderr) if stderr else log_func("%s", message)
        elif stderr:
            logging.error("Command failed: %s\nError: %s", " ".join(command), stderr)
        else:
            logging.error("Command failed: %s", " ".join(command))
        return None


def run_git(
    args: list[str],
    repo: Path | None = None,
    capture_output: bool = False,
    message: str | None = None,
    warn: bool = False,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> CompletedProcess[str] | None:
    command = ["git", *args]
    return run_command(
        command,
        check=check,
        capture_output=capture_output,
        cwd=repo,
        message=message,
        warn=warn,
        env=env,
    )


def check_git_version() -> bool:
    result = run_git(
        ["--version"],
        capture_output=True,
        env=GIT_ENV,
        message="Failed to run 'git --version'",
    )
    if result is None:
        return False

    parts = result.stdout.strip().split()
    if len(parts) < 3:
        logging.error("Unexpected 'git --version' output: %s", result.stdout.strip())
        return False

    try:
        version_tuple = tuple(int(x) for x in parts[2].split(".")[:3])
    except ValueError:
        logging.error("Failed to parse git version from: %s", parts[2])
        return False

    if version_tuple < MIN_GIT_VERSION:
        logging.error(
            "git %s is required, found %s",
            ".".join(str(x) for x in MIN_GIT_VERSION),
            parts[2],
        )
        return False

    return True


def is_git_directory(path: Path) -> bool:
    if not path.exists():
        return False
    result = run_git(
        ["rev-parse"],
        repo=path,
        env=GIT_ENV,
        warn=True,
    )
    if not result:
        logging.error("The path is not a git repository: '%s'", path)
    return result is not None


def ensure_submodules_init(repo: Path) -> bool:
    result = run_git(
        [
            "-c",
            "credential.interactive=false",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
            "--recursive",
        ],
        repo=repo,
        message="Failed to initialize submodules",
    )
    return result is not None


def ensure_git_rev(tag: str, path: Path) -> str | None:
    result = run_git(
        ["rev-list", "-n", "1", tag],
        repo=path,
        env=GIT_ENV,
        capture_output=True,
        message=f"Failed to resolve revision '{tag}'",
    )
    if result is None:
        return None
    return result.stdout.strip()


def extract_checksum_from_tag(repo: Path, tag: str) -> str | None:
    result = run_git(
        ["tag", "-l", "--format=%(contents)", tag],
        repo=repo,
        env=GIT_ENV,
        capture_output=True,
        message=f"Failed to read tag '{tag}'",
    )
    if result is None:
        return None

    for line in result.stdout.splitlines():
        for prefix in ("Git-EVTag-v0-SHA512: ", "Git-EVTag-Py-v0-SHA512: "):
            if line.strip().startswith(prefix):
                return line.split(prefix, 1)[1].strip()

    return None


def sign_tree_checksum(
    repo: Path,
    tag: str,
    in_csum: str,
    tag_msg: str | None = None,
) -> bool:
    check_result = run_git(
        ["show-ref", "--verify", "--quiet", f"refs/tags/{tag}"],
        repo=repo,
        env=GIT_ENV,
        check=False,
        warn=False,
    )

    if check_result is not None and check_result.returncode == 0:
        logging.error("Tag '%s' already exists", tag)
        return False

    head_result = run_git(
        ["rev-parse", "HEAD"],
        repo=repo,
        env=GIT_ENV,
        capture_output=True,
        message="Failed to resolve HEAD",
    )
    if head_result is None:
        return False
    commit = head_result.stdout.strip()

    message = ""

    if tag_msg:
        p = Path(tag_msg)

        if tag_msg.startswith(("/", "./")):
            if not p.is_file():
                logging.error("Failed to find tag message file: %s", p)
                return False
            try:
                message = p.read_text()
            except OSError as e:
                logging.error("Failed to read tag message file: %s", e)
                return False
        else:
            message = tag_msg
    else:
        editor = environ.get("EDITOR", "vi")
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+", delete=False, suffix=".tmp"
            ) as tmp:
                tmp.write("")
                tmp.flush()

                editor_result = run_command(
                    [editor, tmp.name],
                    message=f"Editor '{editor}' failed",
                )
                if editor_result is None:
                    unlink(tmp.name)
                    return False

                tmp.seek(0)
                message = tmp.read()

            unlink(tmp.name)
        except OSError as e:
            logging.error(
                "Failed to open temporary file for editor: %s",
                e,
            )
            return False

    pattern = r"\n?Git-EVTag-v0-SHA512: .*\n?"
    cleaned_msg = re.sub(pattern, "", message, flags=re.DOTALL).rstrip()
    footer = f"\n\nGit-EVTag-v0-SHA512: {in_csum}\n"
    final_msg = cleaned_msg + footer

    tag_args = ["tag", "-a"]

    if environ.get("EVTAG_NO_GPG_SIGN") != "true":
        tag_args.append("-s")

    tag_args.extend([tag, commit, "-m", final_msg])

    result = run_git(
        tag_args,
        repo=repo,
        message=f"Failed to create tag '{tag}'",
    )
    return result is not None


def is_tag_signature_valid(repo: Path, tag: str) -> bool:
    result = run_git(
        ["tag", "-v", tag],
        repo=repo,
        warn=True,
    )
    return result is not None


def prepare_clone(
    src_repo: Path,
    rev: str,
    in_place: bool,
) -> tuple[tempfile.TemporaryDirectory[str] | None, Path] | None:
    if in_place:
        logging.warning("Running in-place checksum computation for '%s'", rev)
        return None, src_repo

    tmp: tempfile.TemporaryDirectory[str] = tempfile.TemporaryDirectory(
        prefix="git-evtag-"
    )
    clone_path = Path(tmp.name) / "repo"

    logging.info("Cloning repository to a temporary directory to checkout '%s'", rev)

    result = run_git(
        ["clone", "--local", "--no-hardlinks", str(src_repo), str(clone_path)],
        message="Failed to clone repository",
    )
    if result is None:
        tmp.cleanup()
        return None

    remote_url = run_git(
        ["remote", "get-url", "origin"],
        repo=src_repo,
        capture_output=True,
        warn=True,
    )
    if remote_url is not None:
        upstream = remote_url.stdout.strip()
        run_git(
            ["remote", "set-url", "origin", upstream],
            repo=clone_path,
            message="Failed to set remote URL on clone",
        )
        run_git(
            ["submodule", "sync", "--recursive"],
            repo=clone_path,
            capture_output=True,
            message="Failed to sync submodule URLs",
        )

    result = run_git(
        ["checkout", rev],
        repo=clone_path,
        message=f"Failed to checkout '{rev}'",
    )
    if result is None:
        tmp.cleanup()
        return None

    if not ensure_submodules_init(clone_path):
        tmp.cleanup()
        return None

    return tmp, clone_path


def parse_tree_content(content: bytes) -> list[tuple[str, str, str]]:
    entries = []
    i = 0
    while i < len(content):
        null = content.index(b"\0", i)
        header = content[i:null].decode("ascii")
        mode, fname = header.split(" ", 1)
        sha = content[null + 1 : null + 21].hex()
        obj_type = (
            "commit" if mode == "160000" else "tree" if mode == "40000" else "blob"
        )
        entries.append((obj_type, sha, fname))
        i = null + 21
    return entries


class ChecksumProcessor:
    def __init__(self) -> None:
        self.stats = {
            "commit": 0,
            "tree": 0,
            "blob": 0,
            "commitbytes": 0,
            "treebytes": 0,
            "blobbytes": 0,
        }
        self.csum = hashlib.sha512()

    def update(self, kind: str, data: bytes) -> int:
        data_len = len(data)
        self.csum.update(data)
        self.stats[kind + "bytes"] += data_len
        return data_len

    def increment(self, kind: str) -> None:
        self.stats[kind] += 1

    def get_digest(self) -> str:
        return self.csum.hexdigest()


class GitBatchProcessor:
    def __init__(self, repo: Path) -> None:
        self.repo = repo
        self._process: None | subprocess.Popen[bytes] = None
        self._stdin: None | IO[bytes] = None
        self._stdout: None | IO[bytes] = None

    def __enter__(self) -> Self:
        try:
            self._process = subprocess.Popen(
                ["git", "cat-file", "--batch"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                cwd=self.repo,
                env=GIT_ENV,
            )
        except OSError as e:
            logging.error("Failed to start 'git cat-file --batch': %s", e)
            raise

        if not (self._process.stdin and self._process.stdout):
            logging.error("Failed to open subprocess streams for git cat-file")
            raise RuntimeError("Failed to open subprocess streams")

        self._stdin = self._process.stdin
        self._stdout = self._process.stdout
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        if self._stdin:
            self._stdin.close()
        if self._process:
            self._process.wait()
            if self._process.returncode != 0 and exc_type is None:
                logging.error(
                    "git cat-file --batch exited with code %d",
                    self._process.returncode,
                )
                raise subprocess.CalledProcessError(
                    self._process.returncode, "git cat-file --batch"
                )

    def get_object(self, obj_id: str) -> tuple[str, int, bytes] | None:
        if not (self._stdin and self._stdout):
            logging.error("Batch process not initialized")
            return None

        try:
            self._stdin.write(obj_id.encode("ascii") + b"\n")
            self._stdin.flush()
            header = self._stdout.readline().decode("ascii").strip()
        except OSError as e:
            logging.error("Failed to communicate with git cat-file: %s", e)
            return None

        if " missing" in header:
            logging.error("Object not found: %s", obj_id)
            return None

        parts = header.split(None, 2)
        if len(parts) != 3:
            logging.error("Malformed git cat-file header: %r", header)
            return None

        _obj_id_returned, obj_type, str_len = parts
        obj_len = int(str_len)

        try:
            content = self._stdout.read(obj_len)
        except OSError as e:
            logging.error("Failed to read object content: %s", e)
            return None

        if len(content) != obj_len:
            logging.error(
                "Object content length mismatch: expected %d, got %d",
                obj_len,
                len(content),
            )
            return None

        self._stdout.read(1)

        return obj_type, obj_len, content


class GitProcessor:
    def __init__(self, repo: Path, checksum: ChecksumProcessor) -> None:
        self.repo = repo
        self.checksum = checksum

    def checksum_object(self, batch_proc: GitBatchProcessor, obj_id: str) -> str | None:
        if not obj_id:
            logging.error("Object ID must not be empty")
            return None

        result = batch_proc.get_object(obj_id)
        if result is None:
            return None

        obj_type, obj_len, content = result

        buf = f"{obj_type} {obj_len}\0".encode("ascii")
        self.checksum.update(obj_type, buf)
        self.checksum.increment(obj_type)

        tree_obj_id: str | None = None

        if obj_type == "commit":
            lines = content.decode("ascii").split("\n")
            if lines and lines[0].startswith("tree "):
                tree_obj_id = lines[0].split(None, 1)[1].strip()
            else:
                logging.error(
                    "Malformed commit object '%s': expected 'tree <sha>' as first line",
                    obj_id,
                )
                return None

        self.checksum.update(obj_type, content)

        return tree_obj_id if obj_type == "commit" else ""

    def checksum_tree(
        self, batch_proc: GitBatchProcessor, path: Path, obj_id: str
    ) -> bool:
        result = batch_proc.get_object(obj_id)
        if result is None:
            return False

        obj_type, obj_len, content = result
        buf = f"{obj_type} {obj_len}\0".encode("ascii")
        self.checksum.update(obj_type, buf)
        self.checksum.update(obj_type, content)

        for entry_type, subid, fname in parse_tree_content(content):
            if entry_type == "blob":
                if self.checksum_object(batch_proc, subid) is None:
                    return False
            elif entry_type == "tree":
                if not self.checksum_tree(batch_proc, path / fname, subid):
                    return False
            elif entry_type == "commit":
                subrepo = self.repo / path / fname
                subproc = GitProcessor(subrepo, self.checksum)
                try:
                    with GitBatchProcessor(subrepo) as sub_batch_proc:
                        if not subproc.checksum_repo(
                            sub_batch_proc, subid, path / fname
                        ):
                            return False
                except (OSError, subprocess.CalledProcessError) as e:
                    logging.error("Failed to process submodule at '%s': %s", subrepo, e)
                    return False
            else:
                logging.error("Unknown object type '%s' for id %s", entry_type, subid)
                return False

        return True

    def checksum_repo(
        self,
        batch_proc: GitBatchProcessor,
        obj_id: str,
        path: Path = Path("."),
    ) -> bool:
        tree_id = self.checksum_object(batch_proc, obj_id)
        if tree_id is None:
            return False
        return not tree_id or self.checksum_tree(batch_proc, path, tree_id)


def verify_tag(repo: Path, tag: str, tag_evtag_csum: str, calc_evtag_csum: str) -> bool:
    matched = tag_evtag_csum == calc_evtag_csum
    tag_sig = is_tag_signature_valid(repo, tag)

    if matched and tag_sig:
        logging.info(
            "EVTag checksum and the tag signature were successfully "
            "verified for the tag '%s'",
            tag,
        )
        return True

    if matched and not tag_sig:
        logging.error(
            "EVTag checksum was verified but failed to verify the "
            "tag signature for the tag '%s'",
            tag,
        )
    elif tag_sig and not matched:
        logging.error(
            "The tag signature for the tag '%s' was verified but failed "
            "to verify the EVTag checksum.\n"
            "Checksum from the tag message: %s\n"
            "Calculated checksum: %s",
            tag,
            tag_evtag_csum,
            calc_evtag_csum,
        )
    else:
        logging.error(
            "Failed to verify both the EVTag checksum and the tag signature "
            "for the tag '%s'.\n"
            "Checksum from the tag message: %s\n"
            "Calculated checksum: %s",
            tag,
            tag_evtag_csum,
            calc_evtag_csum,
        )

    return False


def validate_args(args: argparse.Namespace) -> bool:
    if sum(bool(x) for x in (args.verify, args.sign)) > 1:
        logging.error("Cannot use '--verify' and '--sign' simultaneously")
        return False
    if args.rev and (args.verify or args.sign):
        logging.error("'--rev' cannot be used with '--verify' or '--sign'")
        return False
    if args.tag_msg and not args.sign:
        logging.error("'--tag-msg' can only be used with '--sign'")
        return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="git_evtag_py EVTag checksum of a git repository",
        formatter_class=argparse.RawTextHelpFormatter,
        usage=argparse.SUPPRESS,
        add_help=False,
    )
    parser.add_argument(
        "-h",
        "--help",
        action="help",
        help="Show this help message and exit",
    )
    parser.add_argument(
        "--version",
        action="version",
        help="Show the version number and exit",
        version=f"git_evtag_py {__version__}",
    )
    parser.add_argument(
        "--rev",
        metavar="",
        help="Git revision (default: HEAD)",
    )
    parser.add_argument(
        "--repo",
        default=".",
        metavar="",
        help="Path to the git repository (default: PWD)",
    )
    parser.add_argument(
        "--verify",
        metavar="",
        help="Verify the EVTag checksum of the input tag",
    )
    parser.add_argument(
        "--sign",
        metavar="",
        help=(
            "Create a signed and annotated tag from HEAD and append the EVTag checksum"
        ),
    )
    parser.add_argument(
        "--tag-msg",
        metavar="",
        help=("Use the input as the tag message, or read from a file path"),
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    return parser.parse_args()


def compute_checksum(work_repo: Path, rev: str) -> str | None:
    resolved_commit = ensure_git_rev(rev, work_repo)
    if resolved_commit is None:
        return None

    checksum = ChecksumProcessor()
    processor = GitProcessor(work_repo, checksum)

    try:
        with GitBatchProcessor(work_repo) as batch_proc:
            if not processor.checksum_repo(batch_proc, resolved_commit, work_repo):
                logging.error("Failed to compute EVTag checksum")
                return None
    except (OSError, subprocess.CalledProcessError) as e:
        logging.error("Fatal error during checksum computation: %s", e)
        return None

    return checksum.get_digest()


def run_verify(repo: Path, tag: str, in_place: bool) -> int:
    tag_evtag_csum = extract_checksum_from_tag(repo, tag)
    if not tag_evtag_csum:
        logging.error(
            "'--verify' was passed but did not find the EVTag "
            "checksum from the tag '%s'",
            tag,
        )
        return 1

    clone_result = prepare_clone(repo, tag, in_place)
    if clone_result is None:
        return 1

    tmpdir, work_repo = clone_result
    try:
        calc_evtag_csum = compute_checksum(work_repo, tag)
        if calc_evtag_csum is None:
            return 1
        if not verify_tag(repo, tag, tag_evtag_csum, calc_evtag_csum):
            return 1
    finally:
        if tmpdir:
            tmpdir.cleanup()

    return 0


def run_sign(repo: Path, tag: str, tag_msg: str | None) -> int:
    if not ensure_submodules_init(repo):
        return 1

    calc_evtag_csum = compute_checksum(repo, "HEAD")
    if calc_evtag_csum is None:
        return 1

    if not sign_tree_checksum(repo, tag, calc_evtag_csum, tag_msg=tag_msg):
        logging.error("Failed to create signed tag '%s'", tag)
        return 1

    return 0


def run_compute(repo: Path, rev: str, in_place: bool) -> int:
    clone_result = prepare_clone(repo, rev, in_place)
    if clone_result is None:
        return 1

    tmpdir, work_repo = clone_result
    try:
        calc_evtag_csum = compute_checksum(work_repo, rev)
        if calc_evtag_csum is None:
            return 1
        print(f"Git-EVTag-v0-SHA512: {calc_evtag_csum}")  # noqa: T201
    finally:
        if tmpdir:
            tmpdir.cleanup()

    return 0


def main() -> int:
    args = parse_args()
    if not validate_args(args):
        return 1

    if not check_git_version():
        return 1

    repo = Path(args.repo).resolve()
    if not is_git_directory(repo):
        return 1

    if args.verify:
        return run_verify(repo, args.verify, args.in_place)

    if args.sign:
        return run_sign(repo, args.sign, args.tag_msg)

    rev = args.rev or "HEAD"
    return run_compute(repo, rev, args.in_place)


if __name__ == "__main__":
    raise SystemExit(main())
