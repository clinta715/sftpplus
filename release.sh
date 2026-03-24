#!/bin/bash
# Create a release by pushing a tag
# Usage: ./release.sh [version]
# Example: ./release.sh 2.1.0

set -e

# Get version from argument or read from user
if [ -z "$1" ]; then
    read -p "Enter version number (e.g., 2.1.0): " VERSION
else
    VERSION="$1"
fi

# Remove 'v' prefix if present
VERSION="${VERSION#v}"

# Validate version format
if [[ ! "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: Version must be in format X.Y.Z (e.g., 2.1.0)"
    exit 1
fi

TAG="v${VERSION}"

echo "Creating release $TAG..."

# Check for uncommitted changes
if ! git diff-index --quiet HEAD -- 2>/dev/null; then
    echo "Warning: You have uncommitted changes."
    read -p "Continue anyway? (y/N): " CONTINUE
    if [[ "$CONTINUE" != "y" && "$CONTINUE" != "Y" ]]; then
        echo "Aborted."
        exit 1
    fi
fi

# Create and push tag
echo "Creating tag $TAG..."
git tag -a "$TAG" -m "Release $TAG"

echo "Pushing tag to remote..."
git push origin "$TAG"

echo ""
echo "Release workflow triggered!"
echo "GitHub Actions will build executables and create a release."
echo ""
echo "Monitor progress at:"
echo "https://github.com/clinta715/sftpplus/actions"
echo ""
echo "Release will be available at:"
echo "https://github.com/clinta715/sftpplus/releases/tag/$TAG"