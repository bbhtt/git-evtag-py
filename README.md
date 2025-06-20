### git_evtag_py

A Python implementation of [git-evtag](https://github.com/cgwalters/git-evtag/),
inspired by the [upstream Python implementation](https://github.com/cgwalters/git-evtag/blob/7c58b2021a066f1e552deeb37431bc70b6215d62/src/git-evtag-compute-py) but more feature complete and faster.

This can,

- Calculate and show the EVTag checksum of tags and commits
- Verify the signature and the EVTag checksum of a tag
- Sign a tag with the EVTag checksum

### Usage

Install `git`.

Install `git_evtag_py`

```sh
pip install --user git+https://github.com/bbhtt/git-evtag-py.git@v1.0.4#egg=git_evtag_py
```

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

# Add the EVTag checksum to the tag 'TAG'. Preserves the message of the
# original tag 'TAG', creates a new tag 'TAG' with the previous message
# and the EVTag checksum appended to it
git evtag --sign TAG

# Produces 'Git-EVTag-v0-SHA512' prefixed output
git evtag --compat
git evtag --compat --sign TAG
```

```sh
$ git evtag -h
usage: git-evtag [-h] [--rev REV] [--repo REPO] [--verify VERIFY] [--sign SIGN] [--compat]

EVTag checksum of a git repository

options:
  -h, --help       show this help message and exit
  --rev REV        Git revision (default: HEAD)
  --repo REPO      Path to the git repository (default: PWD)
  --verify VERIFY  Verify the EVTag checksum of the input tag
  --sign SIGN      Sign the input tag with the EVTag checksum
  --compat         Produce 'Git-EVTag-v0-SHA512' prefixed output
```

### Development

```sh
uv run ruff format
uv run ruff check --fix --exit-non-zero-on-fix
uv run mypy .
```
