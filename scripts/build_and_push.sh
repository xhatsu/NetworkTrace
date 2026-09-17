#!/bin/sh
# ==============================================================================
# TraceScope - 2-Image Multi-Stage Build & Push Script
#
# Builds the 2 production application images from deploy/docker/Dockerfile:
#   1. Main App (API, UI, Worker sidecar, Migrations) -> Target: api
#   2. Ingest   (High-throughput trace receiver)      -> Target: ingest
#
# Supports tag-differentiated single repository naming (e.g. xhatsu101/tracescope):
#   - Main App : xhatsu101/tracescope:app-<version>
#   - Ingest   : xhatsu101/tracescope:ingest-<version>
#
# Also supports explicit patterns with {image} and {tag}, e.g.:
#   - xhatsu101/tracescope:{image}-{tag}
#   - registry.example.com/{image}:{tag}
#
# 100% POSIX /bin/sh compliant.
# ==============================================================================
set -eu

IMAGE_PATTERN=""
VERSION=""
PLATFORM=""
DRY_RUN=0
NO_PUSH=0
UNIFIED_ONLY=0
INGEST_ONLY=0

show_help() {
    cat << 'HELP_EOF'
Usage:
  sh deploy/docker/build_and_push.sh <IMAGE_REPO_OR_PATTERN> <VERSION> [OPTIONS]

Arguments:
  IMAGE_REPO_OR_PATTERN
      Repository name or image pattern template.
      Examples:
        - "xhatsu101/tracescope"
          -> Builds and pushes:
               xhatsu101/tracescope:<version>     (Global unified image for Helm)
               xhatsu101/tracescope:app-<version> (Main App alias)
               xhatsu101/tracescope:ingest-<version> (Standalone Ingest)
        - "xhatsu101/tracescope:{image}-{tag}"
          -> Replaces {image} with app / ingest, and {tag} with version
        - "registry.example.com/team/{image}:{tag}"

  VERSION
      Version tag string (e.g. "0.3.3", "v1.0.0", "latest").

Options:
  -u, --unified-only  Build & push only the unified application image (:0.3.3)
      --ingest-only   Build & push only the standalone ingest image (:ingest-0.3.3)
  -p, --platform      Target platform(s), e.g. "linux/amd64" or "linux/amd64,linux/arm64"
  -n, --no-push       Build images only; do not push to remote registry
  -d, --dry-run       Print the commands and tags without executing them
  -h, --help          Show this help message and exit

Examples:
  # Standard build and push with global tag 0.3.3 (matches Helm global.image.tag):
  sh deploy/docker/build_and_push.sh xhatsu101/tracescope 0.3.3

  # Multi-arch build and push (x86_64 + ARM64):
  sh deploy/docker/build_and_push.sh xhatsu101/tracescope 0.3.3 --platform linux/amd64,linux/arm64

  # Build only the unified image:
  sh deploy/docker/build_and_push.sh xhatsu101/tracescope 0.3.3 --unified-only

  # Dry run to preview commands and tags:
  sh deploy/docker/build_and_push.sh xhatsu101/tracescope 0.3.3 --dry-run
HELP_EOF
    exit 0
}

# Parse options and positional arguments
while [ $# -gt 0 ]; do
    case "$1" in
        -h|--help)
            show_help
            ;;
        -d|--dry-run)
            DRY_RUN=1
            shift
            ;;
        -u|--unified-only)
            UNIFIED_ONLY=1
            shift
            ;;
        --ingest-only)
            INGEST_ONLY=1
            shift
            ;;
        -n|--no-push)
            NO_PUSH=1
            shift
            ;;
        -p|--platform)
            shift
            if [ $# -eq 0 ]; then
                echo "Error: --platform requires an argument." >&2
                exit 1
            fi
            PLATFORM="$1"
            shift
            ;;
        -*)
            echo "Error: Unknown option '$1'" >&2
            echo "Run 'sh scripts/build_and_push.sh --help' for usage." >&2
            exit 1
            ;;
        *)
            if [ -z "$IMAGE_PATTERN" ]; then
                IMAGE_PATTERN="$1"
            elif [ -z "$VERSION" ]; then
                VERSION="$1"
            else
                echo "Error: Unexpected argument '$1'" >&2
                echo "Run 'sh scripts/build_and_push.sh --help' for usage." >&2
                exit 1
            fi
            shift
            ;;
    esac
done

if [ -z "$IMAGE_PATTERN" ] || [ -z "$VERSION" ]; then
    echo "Error: Missing required arguments." >&2
    echo "Usage: sh scripts/build_and_push.sh <IMAGE_REPO_OR_PATTERN> <VERSION> [OPTIONS]" >&2
    echo "Run 'sh scripts/build_and_push.sh --help' for details." >&2
    exit 1
fi

# Locate repository root and Dockerfile by walking up directory tree
REPO_ROOT=""
_start_dir=$(cd "$(dirname "$0")" 2>/dev/null && pwd || pwd)
_check_dir="$_start_dir"
while [ "$_check_dir" != "/" ] && [ -n "$_check_dir" ]; do
    if [ -f "$_check_dir/deploy/docker/Dockerfile" ]; then
        REPO_ROOT="$_check_dir"
        break
    fi
    _check_dir=$(dirname "$_check_dir")
done

if [ -z "$REPO_ROOT" ]; then
    _check_dir=$(pwd)
    while [ "$_check_dir" != "/" ] && [ -n "$_check_dir" ]; do
        if [ -f "$_check_dir/deploy/docker/Dockerfile" ]; then
            REPO_ROOT="$_check_dir"
            break
        fi
        _check_dir=$(dirname "$_check_dir")
    done
fi

if [ -z "$REPO_ROOT" ] || [ ! -f "$REPO_ROOT/deploy/docker/Dockerfile" ]; then
    echo "Error: Could not locate repository root containing 'deploy/docker/Dockerfile'." >&2
    exit 1
fi

DOCKERFILE="$REPO_ROOT/deploy/docker/Dockerfile"

# Function to resolve the final image tag for a component
# Args: <pattern> <component_name> <version>
format_tag() {
    _raw="$1"
    _comp="$2"
    _ver="$3"

    case "$_raw" in
        *"{image}"*)
            _res=$(printf '%s\n' "$_raw" | sed "s/{image}/$_comp/g")
            case "$_res" in
                *"{tag}"*)
                    _res=$(printf '%s\n' "$_res" | sed "s/{tag}/$_ver/g")
                    ;;
                *:*)
                    # Has a colon, check if it ends with dash or colon
                    case "$_res" in
                        *-|*:) _res="${_res}${_ver}" ;;
                    esac
                    ;;
                *)
                    _res="${_res}:${_ver}"
                    ;;
            esac
            ;;
        *)
            # No {image} placeholder
            # Extract last segment (after last slash, if any)
            _last_segment="${_raw##*/}"
            case "$_last_segment" in
                *:*)
                    # Colon is in the last segment (e.g. repo:tag-prefix or repo:{tag})
                    _prefix="${_raw%/*}"
                    if [ "$_prefix" = "$_raw" ]; then
                        _repo="${_raw%%:*}"
                        _tag_part="${_raw#*:}"
                    else
                        _repo="${_prefix}/${_last_segment%%:*}"
                        _tag_part="${_last_segment#*:}"
                    fi
                    case "$_tag_part" in
                        *"{tag}"*)
                            _t=$(printf '%s\n' "$_tag_part" | sed "s/{tag}/$_ver/g")
                            _res="${_repo}:${_comp}-${_t}"
                            ;;
                        "")
                            _res="${_repo}:${_comp}-${_ver}"
                            ;;
                        *)
                            _res="${_repo}:${_comp}-${_tag_part}"
                            ;;
                    esac
                    ;;
                *)
                    # Standard repository name without colon (e.g. "xhatsu101/tracescope")
                    # Differentiate via tag: :app-<ver> and :ingest-<ver>
                    _res="${_raw}:${_comp}-${_ver}"
                    ;;
            esac
            ;;
    esac

    printf '%s\n' "$_res"
}

APP_IMAGE=$(format_tag "$IMAGE_PATTERN" "app" "$VERSION")
INGEST_IMAGE=$(format_tag "$IMAGE_PATTERN" "ingest" "$VERSION")

GLOBAL_IMAGE=""
case "$IMAGE_PATTERN" in
    *"{image}"*)
        GLOBAL_IMAGE=""
        ;;
    *:*)
        GLOBAL_IMAGE="${IMAGE_PATTERN%%:*}:${VERSION}"
        ;;
    *)
        GLOBAL_IMAGE="${IMAGE_PATTERN}:${VERSION}"
        ;;
esac

echo "================================================================="
echo " TraceScope Multi-Stage Build & Push"
echo "================================================================="
echo " Repository root : $REPO_ROOT"
echo " Dockerfile      : $DOCKERFILE"
echo " Target Version  : $VERSION"
if [ -n "$PLATFORM" ]; then
    echo " Platform(s)     : $PLATFORM"
else
    echo " Platform(s)     : default (host architecture)"
fi
if [ -n "$GLOBAL_IMAGE" ]; then
    echo " Global Tag      : $GLOBAL_IMAGE (matches Helm global.image.tag)"
fi
if [ "$INGEST_ONLY" -eq 0 ]; then
    echo " Main App Image  : $APP_IMAGE"
fi
if [ "$UNIFIED_ONLY" -eq 0 ]; then
    echo " Ingest Image    : $INGEST_IMAGE"
fi
if [ "$NO_PUSH" -eq 1 ]; then
    echo " Push to remote  : DISABLED (--no-push)"
else
    echo " Push to remote  : ENABLED"
fi
if [ "$DRY_RUN" -eq 1 ]; then
    echo " Mode            : DRY RUN (commands will not execute)"
fi
echo "================================================================="

if [ "$DRY_RUN" -eq 1 ]; then
    echo ""
    echo "[DRY RUN] Would execute:"
    if [ -n "$PLATFORM" ]; then
        if [ "$INGEST_ONLY" -eq 0 ]; then
            if [ -n "$GLOBAL_IMAGE" ] && [ "$GLOBAL_IMAGE" != "$APP_IMAGE" ]; then
                _app_flags="-t $GLOBAL_IMAGE -t $APP_IMAGE"
            else
                _app_flags="-t $APP_IMAGE"
            fi
            if [ "$NO_PUSH" -eq 1 ]; then
                echo "  docker buildx build --platform $PLATFORM -f $DOCKERFILE --target api $_app_flags $REPO_ROOT"
            else
                echo "  docker buildx build --platform $PLATFORM -f $DOCKERFILE --target api $_app_flags --push $REPO_ROOT"
            fi
        fi
        if [ "$UNIFIED_ONLY" -eq 0 ]; then
            if [ "$NO_PUSH" -eq 1 ]; then
                echo "  docker buildx build --platform $PLATFORM -f $DOCKERFILE --target ingest -t $INGEST_IMAGE $REPO_ROOT"
            else
                echo "  docker buildx build --platform $PLATFORM -f $DOCKERFILE --target ingest -t $INGEST_IMAGE --push $REPO_ROOT"
            fi
        fi
    else
        if [ "$INGEST_ONLY" -eq 0 ]; then
            if [ -n "$GLOBAL_IMAGE" ] && [ "$GLOBAL_IMAGE" != "$APP_IMAGE" ]; then
                _app_flags="-t $GLOBAL_IMAGE -t $APP_IMAGE"
            else
                _app_flags="-t $APP_IMAGE"
            fi
            echo "  docker build -f $DOCKERFILE --target api $_app_flags $REPO_ROOT"
        fi
        if [ "$UNIFIED_ONLY" -eq 0 ]; then
            echo "  docker build -f $DOCKERFILE --target ingest -t $INGEST_IMAGE $REPO_ROOT"
        fi
        if [ "$NO_PUSH" -eq 0 ]; then
            if [ "$INGEST_ONLY" -eq 0 ]; then
                if [ -n "$GLOBAL_IMAGE" ] && [ "$GLOBAL_IMAGE" != "$APP_IMAGE" ]; then
                    echo "  docker push $GLOBAL_IMAGE"
                fi
                echo "  docker push $APP_IMAGE"
            fi
            if [ "$UNIFIED_ONLY" -eq 0 ]; then
                echo "  docker push $INGEST_IMAGE"
            fi
        fi
    fi
    echo ""
    echo "Dry run complete."
    exit 0
fi

# Verify docker CLI availability
if ! command -v docker > /dev/null 2>&1; then
    echo "Error: 'docker' command not found in PATH." >&2
    exit 1
fi

if [ -n "$GLOBAL_IMAGE" ] && [ "$GLOBAL_IMAGE" != "$APP_IMAGE" ]; then
    APP_TAG_CMD="-t $GLOBAL_IMAGE -t $APP_IMAGE"
else
    APP_TAG_CMD="-t $APP_IMAGE"
fi

if [ -n "$PLATFORM" ]; then
    if [ "$NO_PUSH" -eq 1 ]; then
        if [ "$INGEST_ONLY" -eq 0 ]; then
            echo ""
            echo "==> Building Main App Image ($PLATFORM, Target: api): $GLOBAL_IMAGE $APP_IMAGE..."
            # shellcheck disable=SC2086
            docker buildx build --platform "$PLATFORM" -f "$DOCKERFILE" --target api $APP_TAG_CMD "$REPO_ROOT"
        fi

        if [ "$UNIFIED_ONLY" -eq 0 ]; then
            echo ""
            echo "==> Building Ingest Image ($PLATFORM, Target: ingest): $INGEST_IMAGE..."
            docker buildx build --platform "$PLATFORM" -f "$DOCKERFILE" --target ingest -t "$INGEST_IMAGE" "$REPO_ROOT"
        fi

        echo ""
        echo "================================================================="
        echo " Build successful! (--no-push was specified; skipping push)"
        echo " Images built for platform(s): $PLATFORM"
        if [ "$INGEST_ONLY" -eq 0 ]; then
            if [ -n "$GLOBAL_IMAGE" ]; then
                echo "   - Global Unified: $GLOBAL_IMAGE"
            fi
            echo "   - Main App:       $APP_IMAGE"
        fi
        if [ "$UNIFIED_ONLY" -eq 0 ]; then
            echo "   - Ingest:         $INGEST_IMAGE"
        fi
        echo "================================================================="
        exit 0
    else
        if [ "$INGEST_ONLY" -eq 0 ]; then
            echo ""
            echo "==> Building and pushing Main App Image ($PLATFORM, Target: api): $GLOBAL_IMAGE $APP_IMAGE..."
            # shellcheck disable=SC2086
            docker buildx build --platform "$PLATFORM" -f "$DOCKERFILE" --target api $APP_TAG_CMD --push "$REPO_ROOT"
        fi

        if [ "$UNIFIED_ONLY" -eq 0 ]; then
            echo ""
            echo "==> Building and pushing Ingest Image ($PLATFORM, Target: ingest): $INGEST_IMAGE..."
            docker buildx build --platform "$PLATFORM" -f "$DOCKERFILE" --target ingest -t "$INGEST_IMAGE" --push "$REPO_ROOT"
        fi

        echo ""
        echo "================================================================="
        echo " Successfully built and pushed TraceScope images!"
        echo " Platform(s): $PLATFORM"
        if [ "$INGEST_ONLY" -eq 0 ]; then
            if [ -n "$GLOBAL_IMAGE" ]; then
                echo "   - Global Unified: $GLOBAL_IMAGE"
            fi
            echo "   - Main App:       $APP_IMAGE"
        fi
        if [ "$UNIFIED_ONLY" -eq 0 ]; then
            echo "   - Ingest:         $INGEST_IMAGE"
        fi
        echo "================================================================="
        exit 0
    fi
fi

if [ "$INGEST_ONLY" -eq 0 ]; then
    echo ""
    echo "==> Building Main App Image (Target: api): $GLOBAL_IMAGE $APP_IMAGE..."
    # shellcheck disable=SC2086
    docker build -f "$DOCKERFILE" --target api $APP_TAG_CMD "$REPO_ROOT"
fi

if [ "$UNIFIED_ONLY" -eq 0 ]; then
    echo ""
    echo "==> Building Ingest Image (Target: ingest): $INGEST_IMAGE..."
    docker build -f "$DOCKERFILE" --target ingest -t "$INGEST_IMAGE" "$REPO_ROOT"
fi

if [ "$NO_PUSH" -eq 1 ]; then
    echo ""
    echo "================================================================="
    echo " Build successful! (--no-push was specified; skipping push)"
    echo " Images built locally:"
    if [ "$INGEST_ONLY" -eq 0 ]; then
        if [ -n "$GLOBAL_IMAGE" ]; then
            echo "   - Global Unified: $GLOBAL_IMAGE"
        fi
        echo "   - Main App:       $APP_IMAGE"
    fi
    if [ "$UNIFIED_ONLY" -eq 0 ]; then
        echo "   - Ingest:         $INGEST_IMAGE"
    fi
    echo "================================================================="
    exit 0
fi

if [ "$INGEST_ONLY" -eq 0 ]; then
    if [ -n "$GLOBAL_IMAGE" ] && [ "$GLOBAL_IMAGE" != "$APP_IMAGE" ]; then
        echo ""
        echo "==> Pushing Global Unified Image: $GLOBAL_IMAGE..."
        docker push "$GLOBAL_IMAGE"
    fi

    echo ""
    echo "==> Pushing Main App Image: $APP_IMAGE..."
    docker push "$APP_IMAGE"
fi

if [ "$UNIFIED_ONLY" -eq 0 ]; then
    echo ""
    echo "==> Pushing Ingest Image: $INGEST_IMAGE..."
    docker push "$INGEST_IMAGE"
fi

echo ""
echo "================================================================="
echo " Successfully built and pushed TraceScope images!"
if [ "$INGEST_ONLY" -eq 0 ]; then
    if [ -n "$GLOBAL_IMAGE" ]; then
        echo "   - Global Unified: $GLOBAL_IMAGE"
    fi
    echo "   - Main App:       $APP_IMAGE"
fi
if [ "$UNIFIED_ONLY" -eq 0 ]; then
    echo "   - Ingest:         $INGEST_IMAGE"
fi
echo "================================================================="
