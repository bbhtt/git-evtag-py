#!/usr/bin/env python3

# SPDX-License-Identifier: LGPL-2.0-or-later
# Original: https://github.com/cgwalters/git-evtag/blob/main/src/git-evtag-compute-py
# Copyright (C) 2025 bbhtt <bbhtt@bbhtt.space>
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
from typing import IO, Self

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG": "''",
}


def is_git_directory(path: Path) -> bool:
    if not path.exists():
        return False
    return (
        subprocess.run(
            ["git", "rev-parse"],
            cwd=path,
            env=GIT_ENV,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def ensure_submodules_init(repo: Path) -> None:
    subprocess.run(
        [
            "git",
            "-c",
            "credential.interactive=false",
            "submodule",
            "update",
            "--init",
            "--recursive",
            "--depth",
            "1",
        ],
        cwd=repo,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def ensure_git_rev(tag: str, path: Path) -> str:
    sha: str = (
        subprocess.check_output(
            ["git", "rev-list", "-n", "1", tag],
            cwd=path,
            env=GIT_ENV,
        )
        .decode()
        .strip()
    )
    return sha


def extract_checksum_from_tag(repo: Path, tag: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "tag", "-l", "--format=%(contents)", tag],
            cwd=repo,
            env=GIT_ENV,
            capture_output=True,
            text=True,
            check=True,
        )

        for line in result.stdout.splitlines():
            if line.strip().startswith("Git-EVTag-v0-SHA512: "):
                return line.split("Git-EVTag-v0-SHA512: ", 1)[1].strip()
        return None
    except subprocess.CalledProcessError as err:
        raise RuntimeError(f"Failed to read tag: {err}") from None


def sign_tree_checksum(
    repo: Path,
    tag: str,
    in_csum: str,
    tag_msg: str | None = None,
    tag_msg_file: Path | None = None,
) -> None:
    ret = subprocess.run(
        ["git", "rev-parse", f"refs/tags/{tag}"],
        check=False,
        cwd=repo,
        env=GIT_ENV,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ret.returncode == 0:
        raise RuntimeError(f"Tag '{tag}' already exists")

    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        text=True,
        cwd=repo,
        env=GIT_ENV,
    ).strip()

    if tag_msg:
        message = tag_msg
    elif tag_msg_file:
        message = Path(tag_msg_file).read_text()
    else:
        editor = environ.get("EDITOR", "vi")
        with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".tmp") as tmp:
            tmp.write("")
            tmp.flush()
            subprocess.run([editor, tmp.name], check=True)
            tmp.seek(0)
            message = tmp.read()
        unlink(tmp.name)

    pattern = r"\n?Git-EVTag-v0-SHA512: .*\n?"
    cleaned_msg = re.sub(pattern, "", message, flags=re.DOTALL).rstrip()
    footer = f"\n\nGit-EVTag-v0-SHA512: {in_csum}\n"
    final_msg = cleaned_msg + footer

    tag_args = ["git", "tag", "-a"]
    if environ.get("EVTAG_NO_GPG_SIGN") != "true":
        tag_args.append("-s")

    tag_args.extend([tag, commit, "-m", final_msg])
    subprocess.run(tag_args, check=True, cwd=repo)


def is_tag_signature_valid(repo: Path, tag: str) -> bool:
    try:
        subprocess.run(
            ["git", "tag", "-v", tag],
            cwd=repo,
            check=True,
            capture_output=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


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
        self._process = subprocess.Popen(
            ["git", "cat-file", "--batch"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            cwd=self.repo,
            env=GIT_ENV,
        )
        if not (self._process.stdin and self._process.stdout):
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
            if self._process.returncode != 0:
                raise subprocess.CalledProcessError(
                    self._process.returncode, "git cat-file --batch"
                )

    def get_object(self, obj_id: str) -> tuple[str, int, bytes]:
        if not (self._stdin and self._stdout):
            raise RuntimeError("Batch process not initialized")

        self._stdin.write(obj_id.encode("ascii") + b"\n")
        self._stdin.flush()

        header = self._stdout.readline().decode("ascii").strip()
        if " missing" in header:
            raise ValueError(f"Object {obj_id} not found")

        parts = header.split(None, 2)
        if len(parts) != 3:
            raise ValueError(f"Malformed header: {header}")

        obj_id_returned, obj_type, str_len = parts
        obj_len = int(str_len)

        content = self._stdout.read(obj_len)
        if len(content) != obj_len:
            raise ValueError(f"Expected {obj_len} bytes, got {len(content)}")

        self._stdout.read(1)

        return obj_type, obj_len, content


class GitProcessor:
    def __init__(self, repo: Path, checksum: ChecksumProcessor) -> None:
        self.repo = repo
        self.checksum = checksum

    def checksum_object(self, batch_proc: GitBatchProcessor, obj_id: str) -> None | str:
        if not obj_id:
            raise ValueError("Object ID must not be None")

        obj_type, obj_len, content = batch_proc.get_object(obj_id)

        buf = f"{obj_type} {obj_len}\0".encode("ascii")
        self.checksum.update(obj_type, buf)
        self.checksum.increment(obj_type)

        tree_obj_id: str | None = None

        if obj_type == "commit":
            lines = content.decode("ascii").split("\n")
            if lines and lines[0].startswith("tree "):
                tree_obj_id = lines[0].split(None, 1)[1].strip()
            else:
                raise ValueError("Malformed commit object, expected 'tree <sha>' line")

        self.checksum.update(obj_type, content)

        return tree_obj_id

    def checksum_tree(
        self, batch_proc: GitBatchProcessor, path: Path, obj_id: str
    ) -> None:
        self.checksum_object(batch_proc, obj_id)

        ret = subprocess.Popen(
            ["git", "ls-tree", obj_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            cwd=self.repo,
            env=GIT_ENV,
        )

        if not ret.stdout:
            raise RuntimeError("Failed to open stdout for ls-tree")

        for line in ret.stdout:
            mode, obj_type, subid, fname = line.decode("ascii").split(None, 3)
            fname = fname.strip()

            if obj_type == "blob":
                self.checksum_object(batch_proc, subid)
            elif obj_type == "tree":
                self.checksum_tree(batch_proc, path / fname, subid)
            elif obj_type == "commit":
                subrepo = self.repo / path / fname
                subproc = GitProcessor(subrepo, self.checksum)
                with GitBatchProcessor(subrepo) as sub_batch_proc:
                    subproc.checksum_repo(sub_batch_proc, subid, path / fname)
            else:
                raise ValueError(f"Unknown object type: {obj_type}")

        ret.wait()
        if ret.returncode != 0:
            raise subprocess.CalledProcessError(ret.returncode, "git ls-tree")

    def checksum_repo(
        self, batch_proc: GitBatchProcessor, obj_id: str, path: Path = Path(".")
    ) -> None:
        tree_id = self.checksum_object(batch_proc, obj_id)
        if tree_id:
            self.checksum_tree(batch_proc, path, tree_id)


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
    if (args.tag_message or args.tag_message_file) and not args.sign:
        logging.error(
            "'--tag-message' and '--tag-message-file' can only be used with '--sign'"
        )
        return False
    if args.tag_message_file and not args.tag_message_file.exists():
        logging.error("The tag message file does not exist '%s'", args.tag_message_file)
        return False
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="EVTag checksum of a git repository")
    parser.add_argument("--rev", help="Git revision (default: HEAD)")
    parser.add_argument(
        "--repo", default=".", help="Path to the git repository (default: PWD)"
    )
    parser.add_argument("--verify", help="Verify the EVTag checksum of the input tag")
    parser.add_argument(
        "--sign",
        help=(
            "Create a signed and annotated tag from HEAD and append the EVTag checksum"
        ),
    )
    tag_msg = parser.add_mutually_exclusive_group()
    tag_msg.add_argument(
        "-m", "--tag-message", help="Use the input message as the tag message"
    )
    tag_msg.add_argument(
        "-F",
        "--tag-message-file",
        type=Path,
        help="Use the message from the input file as the tag message",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not validate_args(args):
        return 1

    repo = Path(args.repo).resolve()
    if not is_git_directory(repo):
        logging.error("The path is not a git repository: '%s'", repo)
        return 1

    resolved_commit: str | None = None
    in_tag: str | None = None
    tag_evtag_csum: str | None = None
    if not args.rev:
        resolved_commit = ensure_git_rev("HEAD", repo)
    if args.rev:
        resolved_commit = ensure_git_rev(args.rev, repo)
    if args.sign or args.verify:
        in_tag = args.sign or args.verify
    if (args.verify or args.sign) and not in_tag:
        logging.error("Failed to get the input tag")
        return 1
    if args.verify and in_tag:
        resolved_commit = ensure_git_rev(in_tag, repo)
        tag_evtag_csum = extract_checksum_from_tag(repo, in_tag)
        if not tag_evtag_csum:
            logging.error(
                "'--verify' was passed but did not find the EVTag "
                "checksum from the tag '%s'",
                in_tag,
            )
            return 1
    if not resolved_commit:
        logging.error("Failed to calculate the resolved commit from the input")
        return 1

    if resolved_commit:
        checksum = ChecksumProcessor()
        ensure_submodules_init(repo)
        processor = GitProcessor(repo, checksum)
        with GitBatchProcessor(repo) as batch_proc:
            processor.checksum_repo(batch_proc, resolved_commit, repo)
    else:
        logging.error("Failed to calculate the resolved commit from the input")
        return 1

    calc_evtag_csum = checksum.get_digest()

    if not (args.verify or args.sign):
        print(f"Git-EVTag-v0-SHA512: {calc_evtag_csum}")  # noqa: T201
    elif args.sign and in_tag:
        if args.tag_message:
            sign_tree_checksum(repo, in_tag, calc_evtag_csum, tag_msg=args.tag_message)
        elif args.tag_message_file:
            sign_tree_checksum(
                repo,
                in_tag,
                calc_evtag_csum,
                tag_msg_file=args.tag_message_file,
            )
        else:
            sign_tree_checksum(repo, in_tag, calc_evtag_csum)
    elif (
        args.verify
        and in_tag
        and tag_evtag_csum
        and not verify_tag(repo, in_tag, tag_evtag_csum, calc_evtag_csum)
    ):
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
