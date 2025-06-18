### git_evtag_py

A python script version of [git-evtag](https://github.com/cgwalters/git-evtag/),
inspired by the [upstream Python implementation](https://github.com/cgwalters/git-evtag/blob/7c58b2021a066f1e552deeb37431bc70b6215d62/src/git-evtag-compute-py) but more feature complete and faster.

This can,

- Calculate and show checksum
- Verify checksum of a tag against the one in the tag message
- Sign a tag with the checksum


### Usage

Install `git`.

Symlink `git-evtag` to `~/.local/bin/git-evtag` or somewhere else that
is in `$PATH`. Then,

```
# Show tree checksum of HEAD
git evtag

# Show tree checksum of tag TAG
git evtag --rev TAG

# Show tree checksum of commit COMMIT
git evtag --rev COMMIT

# Verify checksum obtained from tag message of tag TAG against the
# one calculated. Also verifies signature of TAG
git evtag --verify TAG

# Add tree checksum to the tag TAG. Preserves the message of the
# original tag TAG, creates a new tag TAG with the previous message and
# the checksum appended to it
git evtag --sign TAG

# Produces 'Git-EVTag-v0-SHA512' prefixed output
git evtag --compat
git evtag --compat --sign TAG
```

```sh
$ git evtag -h
usage: git-evtag [-h] [--rev REV] [--repo REPO] [--verify VERIFY] [--sign SIGN] [--compat]

Tree checksum of a git repository

options:
  -h, --help       show this help message and exit
  --rev REV        Git revision (default: HEAD)
  --repo REPO      Path to the git repository (default: current dir)
  --verify VERIFY  Verify the tree checksum from the input tag message
  --sign SIGN      Sign the input tag with the tree checksum
  --compat         Produce 'Git-EVTag-v0-SHA512' prefixed output
```

### Development

```sh
uv run ruff format
uv run ruff check --fix --exit-non-zero-on-fix
uv run mypy .
```
