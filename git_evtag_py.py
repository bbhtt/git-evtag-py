#!/usr/bin/env python3

# SPDX-License-Identifier: LGPL-2.0-or-later
# Original: https://github.com/cgwalters/git-evtag/blob/main/src/git-evtag-compute-py

import argparse
import hashlib
import os
import re
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from typing import IO, Self

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
            if line.strip().startswith("Git-EVTag-Py-v0-SHA512: "):
                return line.split("Git-EVTag-Py-v0-SHA512: ", 1)[1].strip()
            if line.strip().startswith("Git-EVTag-v0-SHA512: "):
                return line.split("Git-EVTag-v0-SHA512: ", 1)[1].strip()
        return None
    except subprocess.CalledProcessError as err:
        raise RuntimeError(f"Failed to read tag: {err}") from None


def sign_tree_checksum(
    repo: Path, tag: str, in_csum: str, compat: bool = False
) -> None:
    commit = subprocess.check_output(
        ["git", "rev-parse", f"{tag}^{{}}"],
        text=True,
        cwd=repo,
        env=GIT_ENV,
    ).strip()

    tag_msg = subprocess.check_output(
        ["git", "for-each-ref", f"refs/tags/{tag}", "--format=%(contents)"],
        text=True,
        cwd=repo,
        env=GIT_ENV,
    )

    pattern = (
        r"(?:\n?Git-EVTag-Py-v0-SHA512: .*\n?|"
        r"\n?-----BEGIN PGP SIGNATURE-----.*?-----END PGP SIGNATURE-----\n?)"
    )

    if compat:
        pattern = pattern[:-1] + r"|\n?Git-EVTag-v0-SHA512: .*\n?)"

    cleaned_msg = re.sub(pattern, "", tag_msg, flags=re.DOTALL)

    editor = os.environ.get("EDITOR", "vi")
    with tempfile.NamedTemporaryFile(mode="w+", delete=False, suffix=".tmp") as tmp:
        tmp.write(cleaned_msg)
        tmp.flush()
        subprocess.run([editor, tmp.name], check=True)
        tmp.seek(0)
        edited_msg = tmp.read()

    if compat:
        footer = f"\n\nGit-EVTag-v0-SHA512: {in_csum}\n"
    else:
        footer = f"\n\nGit-EVTag-Py-v0-SHA512: {in_csum}\n"

    final_msg = edited_msg.rstrip() + footer

    subprocess.run(
        ["git", "tag", tag, commit, "-f", "-m", final_msg],
        check=True,
        cwd=repo,
    )
    os.unlink(tmp.name)


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Tree checksum of a git repository")
    parser.add_argument("--rev", default="HEAD", help="Git revision (default: HEAD)")
    parser.add_argument(
        "--repo", default=".", help="Path to the git repository (default: current dir)"
    )
    parser.add_argument(
        "--verify", help="Verify the tree checksum from the input tag message"
    )
    parser.add_argument("--sign", help="Sign the input tag with the tree checksum")
    parser.add_argument(
        "--compat",
        action="store_true",
        help="Produce 'Git-EVTag-v0-SHA512' prefixed output",
    )
    args = parser.parse_args()

    if args.verify and args.sign:
        raise Exception("'--verify' and '--sign' cannot be used simultaneously")

    checksum = ChecksumProcessor()
    repo = Path(args.repo).resolve()
    if not is_git_directory(repo):
        raise Exception(f"{repo} is not a git repository")
    ensure_submodules_init(repo)
    processor = GitProcessor(repo, checksum)

    args.rev = ensure_git_rev(args.rev, repo)

    if args.verify or args.sign:
        tag = args.verify or args.sign
        args.rev = ensure_git_rev(tag, repo)

    if args.verify:
        tag_msg_checksum = extract_checksum_from_tag(repo, tag)

    with GitBatchProcessor(repo) as batch_proc:
        processor.checksum_repo(batch_proc, args.rev, repo)

    calculated_digest = checksum.get_digest()

    if not (args.verify or args.sign):
        if args.compat:
            print(f"Git-EVTag-v0-SHA512: {calculated_digest}")  # noqa: T201
        else:
            print(f"Git-EVTag-Py-v0-SHA512: {calculated_digest}")  # noqa: T201
    elif args.sign:
        sign_tree_checksum(repo, args.sign, calculated_digest, args.compat)
    elif args.verify:
        if not tag_msg_checksum:
            print(  # noqa: T201
                "Checksum was not found from tag but '--verify' was passed",
                file=sys.stderr,
            )
            sys.exit(1)
        matched = tag_msg_checksum == calculated_digest
        tag_sig = is_tag_signature_valid(repo, args.verify)
        if matched and tag_sig:
            print("Checksum and signature are successfully verified")  # noqa: T201
        elif matched and not tag_sig:
            print("Checksum was verified but not signature", file=sys.stderr)  # noqa: T201
            sys.exit(1)
        elif tag_sig and not matched:
            print(  # noqa: T201
                (
                    "Signature was verified but not checksum"
                    f"\nChecksum from tag message {tag_msg_checksum}"
                    f"\nCalculated checksum of {args.verify} is {calculated_digest}"
                ),
                file=sys.stderr,
            )
            sys.exit(1)
        else:
            print(  # noqa: T201
                (
                    "Checksums and signature verification failed"
                    f"\nChecksum from tag message {tag_msg_checksum}"
                    f"\nCalculated checksum of {args.verify} is {calculated_digest}"
                ),
                file=sys.stderr,
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
