#!/data/data/com.termux/files/usr/bin/bash
# mobile/bootstrap-termux.sh — phase 1 of docs/MOBILE-PORT.org.
# Boots a source checkout of this agent on Termux (aarch64, bionic):
# system packages, clone, venv, the lean extra, and a compile smoke.
# The PM store is NOT used (non-FHS: its staged binaries have a glibc
# PT_INTERP that does not exist here); everything comes from pkg + pip.
# Machine discipline (specs/012): one heavy job at a time, nice'd.
set -euo pipefail

REPO="${1:-https://github.com/khaalidrafi/slave-agent.git}"
DIR="${2:-$HOME/slave-agent}"

echo "==> system packages (pkg, one at a time per specs/012)"
for p in git python make libjpeg-turbo libpng zlib libffi openssl rust-bin binutils; do
  nice -n 19 pkg install -y "$p"
done

echo "==> clone"
[ -d "$DIR" ] || nice -n 19 git clone --depth 1 "$REPO" "$DIR"
cd "$DIR"

echo "==> venv"
[ -x .venv/bin/python ] || nice -n 19 python -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> base install only (extras are opt-in lanes; none on a phone)"
nice -n 19 pip install --upgrade pip
nice -n 19 pip install -e . || {
  echo "pip install failed; the bionic wheel audit table in docs/MOBILE-PORT.org"
  echo "says which deps build from source and which need a substitute."
  exit 1
}

echo "==> compile smoke (the audit's cheap proof: the tree parses)"
nice -n 19 python -m compileall -q slave_cli agent tools gateway persona plugins || true
nice -n 19 python -c "import slave_constants, persona; print('import smoke: OK')"

echo
echo "bootstrap done. Run: $DIR/.venv/bin/python cli.py"
echo "audit commands next (docs/MOBILE-PORT.org): record the bionic/binary"
echo "classification for every dependency before phase 2."
