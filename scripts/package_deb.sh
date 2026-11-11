#!/bin/bash
# package_deb.sh — build the cortexagent .deb (self-contained hardened fork).
# dpkg layout: /opt/cortex-agent = the frozen tree (launcher, compiled modules,
# tui dist, vendored runtime); /usr/local/bin/cortex-agent = symlink.
# The deb's postinst runs bin/verify_compiled.py so a broken install fails
# loudly at dpkg time, never silently at first boot.
# Local-only artifact; never uploaded to a repo (owner directive).
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
OUT="$ROOT/dist/deb"
PKGROOT="$OUT/cortexagent"
VERSION="$(python3 "$ROOT/bin/version.sh" 2>/dev/null || true)"
[ -n "$VERSION" ] || VERSION="$(node "$ROOT/tui/packages/coding-agent/dist/cli.js" --version 2>/dev/null | tail -1 | tr -dc '0-9.')"
[ -n "$VERSION" ] || VERSION="0.7.5.1"

echo "== packaging cortexagent $VERSION =="
rm -rf "$OUT"
mkdir -p "$PKGROOT/DEBIAN" "$PKGROOT/opt/cortex-agent" "$PKGROOT/usr/local/bin"
cat > "$PKGROOT/DEBIAN/control" <<EOF
Package: cortexagent
Version: $VERSION
Section: utils
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.13), nodejs (>= 22), libc6, libstdc++6, libgcc-s1, libnvidia-ml1 | libcuda1
Maintainer: grey <local>
Description: cortexagent — hardened offline fork of the cortex agent family
 Fully Cython-compiled agent core/tools/services; renamed private
 engine-server (cortexagent-server) on :7080 with its slimtoken lane on
 :7081 (both movable via CORTEXENGINE_PORT / CORTEXENGINE_LANE_PORT); Node TUI
 under the @cortexagent scope; frozen, hash-pinned artifacts
 (state/MANIFEST.json) and an on-demand, masked lifecycle. Port policy in
 ~/.cortexagent/agent/port_policy.json (:11600 untouched, :11434 dead).
EOF
# payload: everything, minus transient scratch
tar -C "$ROOT" \
    --exclude='__pycache__' --exclude='.pytest_cache' \
    --exclude='dist/deb' \
    --exclude='build/src/build' \
    --exclude='state/model-server.log' \
    -cf - bin core tools services build mcp scripts tests tui vendor pytest.ini config model ui state/MANIFEST.json \
    | tar -xf - -C "$PKGROOT/opt/cortex-agent"
ln -sf /opt/cortex-agent/bin/cortexagent "$PKGROOT/usr/local/bin/cortex-agent"
cat > "$PKGROOT/DEBIAN/postinst" <<'EOF'
#!/bin/bash
set -e
if ! python3 /opt/cortex-agent/bin/verify_compiled.py; then
  echo "cortexagent: frozen-tree verification FAILED after install" >&2
  exit 1
fi
echo "cortexagent: frozen tree verified. ~/.cortexagent/agent seeds on first launch."
EOF
chmod 755 "$PKGROOT/DEBIAN/postinst"
du -sh "$PKGROOT/opt/cortex-agent" | sed 's/^/payload: /'
dpkg-deb --build "$PKGROOT" "$OUT/cortexagent_${VERSION}_amd64.deb"
ls -la "$OUT" | grep deb