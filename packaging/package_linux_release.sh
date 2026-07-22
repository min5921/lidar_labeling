#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release_name=""
executable="dist/LiDARLabelTool"
output_directory="release_packages"

usage() {
    cat <<'EOF'
Usage: packaging/package_linux_release.sh RELEASE_NAME [options]

Options:
  --executable PATH        One-file executable relative to repo root
  --output DIRECTORY       Release output relative to repo root
  -h, --help               Show this help
EOF
}

if (($#)); then
    release_name="$1"
    shift
fi
while (($#)); do
    case "$1" in
        --executable)
            executable="${2:?--executable requires a value}"
            shift 2
            ;;
        --output)
            output_directory="${2:?--output requires a value}"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [[ ! "$release_name" =~ ^[A-Za-z0-9._-]+$ ]]; then
    echo "RELEASE_NAME must use only letters, digits, '.', '_' and '-'." >&2
    exit 2
fi
if [[ "$(uname -s)" != "Linux" ]]; then
    echo "Linux release packaging must run on Linux." >&2
    exit 2
fi

source_path="$project_root/$executable"
output_root="$project_root/$output_directory"
release_root="$output_root/$release_name"
archive="$output_root/$release_name.tar.gz"
hash_path="$output_root/$release_name.tar.gz.sha256.txt"
dependency_record="$project_root/build/linux-build-dependencies.txt"

if [[ ! -x "$source_path" ]]; then
    echo "One-file executable does not exist or is not executable: $source_path" >&2
    exit 1
fi
if [[ ! -f "$dependency_record" ]]; then
    echo "Build dependency record is missing: $dependency_record" >&2
    exit 1
fi
if [[ -e "$release_root" || -e "$archive" || -e "$hash_path" ]]; then
    echo "Release output already exists: $release_name" >&2
    exit 1
fi

mkdir -p "$release_root"
install -m 0755 "$source_path" "$release_root/LiDARLabelTool"
install -m 0644 \
    "$project_root/packaging/linux_bundle/README_FIRST.md" \
    "$release_root/README_FIRST.md"
install -m 0644 \
    "$project_root/THIRD_PARTY_NOTICES.md" \
    "$release_root/THIRD_PARTY_NOTICES.md"
install -m 0644 \
    "$dependency_record" \
    "$release_root/BUILD_DEPENDENCIES.txt"

tar \
    --sort=name \
    --mtime="@${SOURCE_DATE_EPOCH:-0}" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    -czf "$archive" \
    -C "$output_root" \
    "$release_name"

archive_name="$(basename "$archive")"
(
    cd "$output_root"
    sha256sum "$archive_name" >"$(basename "$hash_path")"
)

echo "Linux release complete: $archive"
echo "SHA-256: $(cut -d' ' -f1 "$hash_path")"
