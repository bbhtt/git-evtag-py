### git_evtag_py

A Python implementation of [git-evtag](https://github.com/cgwalters/git-evtag/),
inspired by the [upstream Python implementation](https://github.com/cgwalters/git-evtag/blob/7c58b2021a066f1e552deeb37431bc70b6215d62/src/git-evtag-compute-py)
but [more feature complete and faster](#performance).

This can,

- Calculate and show the EVTag checksum of tags and commits
- Verify the signature and the EVTag checksum of a tag
- Sign a tag with the EVTag checksum

### Install

Install `git >= 2.9.0`, then install `git_evtag_py`:

```sh
pip install --user git+https://github.com/bbhtt/git-evtag-py.git@v2.0.0#egg=git_evtag_py
```

### Usage

```sh
# Show the EVTag checksum of HEAD
git evtag

# Show the EVTag checksum of the tag 'TAG'
git evtag --rev TAG

# Show the EVTag checksum of the commit 'COMMIT'
git evtag --rev COMMIT

# Verify the signature and the EVTag checksum obtained from the tag
# message of the tag 'TAG' against the one calculated
git evtag --verify TAG

# Create a signed and annotated tag 'TAG' from HEAD and append the EVTag
# checksum to it. Opens EDITOR for the tag message
git evtag --sign TAG

# Create a signed and annotated tag 'TAG' from HEAD and append the EVTag
# checksum to it. Uses 'Tag Message' as the tag message
git evtag --sign TAG -m "Tag Message"

# Create a signed and annotated tag 'TAG' from HEAD and append the EVTag
# checksum to it. Opens './TAG-FILE' for the tag message
git evtag --sign TAG -m "./TAG-FILE"
```

```sh
git_evtag_py EVTag checksum of a git repository

options:
  -h, --help  Show this help message and exit
  --version   Show the version number and exit
  --rev       Git revision (default: HEAD)
  --repo      Path to the git repository (default: PWD)
  --verify    Verify the EVTag checksum of the input tag
  --sign      Create a signed and annotated tag from HEAD and append the EVTag checksum
  --tag-msg   Use the input as the tag message, or read from a file path
```

### Development

```sh
uv run ruff format
uv run ruff check --fix --exit-non-zero-on-fix
uv run mypy .
uv run pytest -vvvs
```

### Performance

_Compared to the upstream Python and C implementation(s)._

On `torvalds/linux.git` at the `v6.15` tag:

```sh
# git_evtag_py

/bin/time -p git-evtag --in-place
WARNING: Running in-place checksum computation for 'HEAD'
Git-EVTag-v0-SHA512: e7e3045a3f5b8f9cc538cc37a56143918306282f7200b9c860703bc839e0a7f4c59f36313d34e6ae9b825c2f77081dfe8e2d5f50f70030271ea17161e2e2fe83
real 7.68
user 6.65
sys 1.71

## Average for 10 runs

real 7.78
user 6.72
sys  1.76

/bin/time -p git-evtag
INFO: Cloning repository to a temporary directory to checkout 'HEAD'
Git-EVTag-v0-SHA512: e7e3045a3f5b8f9cc538cc37a56143918306282f7200b9c860703bc839e0a7f4c59f36313d34e6ae9b825c2f77081dfe8e2d5f50f70030271ea17161e2e2fe83
real 26.19
user 11.94
sys 10.09

# git-evtag-compute-py (Upstream Python implementation)

/bin/time -p git-evtag-compute-py HEAD
# git-evtag comment: submodules=0 commits=1 (262) trees=5895 (3908050) blobs=88843 (1510695775)
Git-EVTag-v0-SHA512: e7e3045a3f5b8f9cc538cc37a56143918306282f7200b9c860703bc839e0a7f4c59f36313d34e6ae9b825c2f77081dfe8e2d5f50f70030271ea17161e2e2fe83
real 152.06
user 46.40
sys 111.18

# git-evtag (Upstream C implementation)

/bin/time -p git-evtag sign --print-only v6.15
# git-evtag comment: submodules=0 commits=1 (262) trees=5895 (3908050) blobs=88843 (1510695775)
Git-EVTag-v0-SHA512: e7e3045a3f5b8f9cc538cc37a56143918306282f7200b9c860703bc839e0a7f4c59f36313d34e6ae9b825c2f77081dfe8e2d5f50f70030271ea17161e2e2fe83
real 8.65
user 8.22
sys 0.39

## Average for 10 runs

real 8.73
user 8.28
sys  0.40
```
