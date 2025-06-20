### git_evtag_py

A Python implementation of [git-evtag](https://github.com/cgwalters/git-evtag/),
inspired by the [upstream Python implementation](https://github.com/cgwalters/git-evtag/blob/7c58b2021a066f1e552deeb37431bc70b6215d62/src/git-evtag-compute-py)
but more feature complete and [faster](#performance).

This can,

- Calculate and show the EVTag checksum of tags and commits
- Verify the signature and the EVTag checksum of a tag
- Sign a tag with the EVTag checksum

### Install

Install `git`, then install `git_evtag_py`:

```sh
pip install --user git+https://github.com/bbhtt/git-evtag-py.git@v1.0.8#egg=git_evtag_py
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
# checksum to it. Uses the message from the file 'FILE' as the tag
# message
git evtag --sign TAG -F FILE
```

```sh
$ git evtag -h
usage: git-evtag [-h] [--rev REV] [--repo REPO] [--verify VERIFY] [--sign SIGN] [-m TAG_MESSAGE | -F TAG_MESSAGE_FILE]

EVTag checksum of a git repository

options:
  -h, --help            show this help message and exit
  --rev REV             Git revision (default: HEAD)
  --repo REPO           Path to the git repository (default: PWD)
  --verify VERIFY       Verify the EVTag checksum of the input tag
  --sign SIGN           Create a signed and annotated tag from HEAD and append the EVTag checksum
  -m, --tag-message TAG_MESSAGE
                        Use the input message as the tag message
  -F, --tag-message-file TAG_MESSAGE_FILE
                        Use the message from the input file as the tag message
```

### Development

```sh
uv run ruff format
uv run ruff check --fix --exit-non-zero-on-fix
uv run mypy .
```

### Performance

_Compared to the upstream Python implementation._

On `torvalds/linux.git` at the `v6.15` tag:

```sh
# git_evtag_py

/bin/time -p git evtag
Git-EVTag-v0-SHA512: e7e3045a3f5b8f9cc538cc37a56143918306282f7200b9c860703bc839e0a7f4c59f36313d34e6ae9b825c2f77081dfe8e2d5f50f70030271ea17161e2e2fe83
real 14.19
user 8.60
sys 7.21

# git-evtag-compute-py

/bin/time -p git-evtag-compute-py HEAD
# git-evtag comment: submodules=0 commits=1 (262) trees=5895 (3908050) blobs=88843 (1510695775)
Git-EVTag-v0-SHA512: e7e3045a3f5b8f9cc538cc37a56143918306282f7200b9c860703bc839e0a7f4c59f36313d34e6ae9b825c2f77081dfe8e2d5f50f70030271ea17161e2e2fe83
real 152.06
user 46.40
sys 111.18
```

On `mesa/mesa.git` at the `mesa-25.0.0` tag:

```sh
# git_evtag_py

/bin/time -p git evtag
Git-EVTag-v0-SHA512: b7a88cbca3c1257855404ab6f16b9efaf1e9b9304f46ad45a5d1a283808e40a96011e9321f0c6a8aacfe3a1be9c3cb971b9169ba21bd1d2ccfeb52041da0475b
real 1.93
user 1.02
sys 1.06

# git-evtag-compute-py

/bin/time -p git-evtag-compute-py HEAD
# git-evtag comment: submodules=0 commits=1 (252) trees=714 (510170) blobs=10970 (283895423)
Git-EVTag-v0-SHA512: b7a88cbca3c1257855404ab6f16b9efaf1e9b9304f46ad45a5d1a283808e40a96011e9321f0c6a8aacfe3a1be9c3cb971b9169ba21bd1d2ccfeb52041da0475b
real 18.55
user 5.83
sys 13.45
```
