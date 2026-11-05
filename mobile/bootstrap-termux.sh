#!/data/data/com.termux/files/usr/bin/bash
# slave-agent — mobile bootstrap, phase 1 (Termux on Android).
# Installs the lean agent runtime ON the handset: model calls stay
# cloud-side; the agent core, shop tools and Org memory run locally.
# Usage (inside the Termux app):
#   bash bootstrap-termux.sh [repo-url] [target-dir]
set -euo pipefail

command -v pkg >/dev/null 2>&1 || {
  echo "ERROR: run inside Termux (F-Droid Termux app), not adb/sh" >&2
  exit 1
}

REPO=${1:-https://github.com/khaalidrafi/slave-agent.git}
DIR=${2:-$HOME/slave-agent}

echo "== 1/4 Termux packages (python + toolchain for aarch64 source builds)"
pkg update -y
pkg install -y python python-pip git clang make pkg-config libffi openssl rust binutils

echo "== 2/4 clone $REPO -> $DIR"
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" fetch origin
  git -C "$DIR" pull --rebase
else
  git clone "$REPO" "$DIR"
fi
CODE_BRANCH=$(git -C "$DIR" rev-parse --verify --quiet origin/ai/main >/dev/null 2>&1 && echo ai/main || echo "$(git -C "$DIR" branch -r --format='%(refname:short)' | grep -v HEAD | head -1)")
git -C "$DIR" checkout "$CODE_BRANCH"
echo "   code branch: $CODE_BRANCH"

echo "== 3/4 venv + lean install"
cd "$DIR"
python -m venv .venv
. .venv/bin/activate
python -m pip install -U pip wheel setuptools
# lean/mobile extra when it exists upstream; plain install otherwise.
python -m pip install -e '.[mobile]' 2>/dev/null || python -m pip install -e '.'

echo "== 4/4 smoke (syntax-load the tree; no model calls, no network)"
python -m compileall -q .
echo
echo "slave-agent installed on this handset (branch $CODE_BRANCH)."
echo "Next: configure your provider key as an env var NAME + value in"
echo "Termux (~/.bashrc export), then launch the agent TUI, or run"
echo "slave-acp for the ACP stdio server.  Keep long sessions alive"
echo "with: termux-wake-lock"
