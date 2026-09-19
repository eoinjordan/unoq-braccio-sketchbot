#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
VERSION=$(node -p "require('$ROOT/web/package.json').version")
SDK="${ANDROID_HOME:-${ANDROID_SDK_ROOT:-$HOME/Library/Android/sdk}}"
BUILD_TOOLS="${ANDROID_BUILD_TOOLS:-35.0.0}"
PLATFORM="${ANDROID_PLATFORM:-android-35}"
TOOLS="$SDK/build-tools/$BUILD_TOOLS"
ANDROID_JAR="$SDK/platforms/$PLATFORM/android.jar"
OUTPUT="$ROOT/output/packages"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUTPUT" "$WORK/res/drawable" "$WORK/generated" "$WORK/classes" "$WORK/dex"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { printf 'Invalid package version\n' >&2; exit 1; }
[[ -f "$ANDROID_JAR" && -x "$TOOLS/aapt2" && -x "$TOOLS/d8" ]] || { printf 'Install Android SDK platform 35 and build tools 35.0.0, or set ANDROID_HOME.\n' >&2; exit 1; }
cp "$ROOT/site/assets/icon-192.png" "$WORK/res/drawable/icon.png"
"$TOOLS/aapt2" compile --dir "$WORK/res" -o "$WORK/resources.zip"
"$TOOLS/aapt2" link -o "$WORK/resources.apk" --manifest "$ROOT/packaging/android/AndroidManifest.xml" \
  -I "$ANDROID_JAR" --java "$WORK/generated" --min-sdk-version 24 --target-sdk-version 35 \
  --version-code 3 --version-name "$VERSION" "$WORK/resources.zip"
find "$ROOT/packaging/android/src" "$WORK/generated" -name '*.java' -print0 | \
  xargs -0 javac -source 8 -target 8 -classpath "$ANDROID_JAR" -d "$WORK/classes"
find "$WORK/classes" -name '*.class' -print0 | xargs -0 "$TOOLS/d8" --release --min-api 24 \
  --lib "$ANDROID_JAR" --output "$WORK/dex"
cp "$WORK/resources.apk" "$WORK/unsigned.apk"
zip -j -q "$WORK/unsigned.apk" "$WORK/dex/classes.dex"
"$TOOLS/zipalign" -f 4 "$WORK/unsigned.apk" "$WORK/aligned.apk"

SIGNING_DIR="${SKETCHBOT_SIGNING_DIR:-$HOME/.local/share/sketchbot-release-signing}"
mkdir -p "$SIGNING_DIR"
chmod 700 "$SIGNING_DIR"
KEYSTORE="$SIGNING_DIR/android-release.p12"
PASSWORD="$SIGNING_DIR/android-release.password"
if [[ ! -f "$KEYSTORE" ]]; then
  umask 077
  openssl rand -hex 32 > "$PASSWORD"
  keytool -genkeypair -keystore "$KEYSTORE" -storetype PKCS12 -storepass:file "$PASSWORD" \
    -keypass:file "$PASSWORD" -alias sketchbot -keyalg RSA -keysize 3072 -validity 10000 \
    -dname 'CN=Sketchbot Studio,OU=Release,O=Sketchbot Studio,C=IE' -noprompt
fi
[[ -f "$PASSWORD" ]] || { printf 'Signing password file missing; existing key was not changed.\n' >&2; exit 1; }
APK="$OUTPUT/Sketchbot-Tablet-$VERSION.apk"
"$TOOLS/apksigner" sign --ks "$KEYSTORE" --ks-pass "file:$PASSWORD" \
  --out "$APK" "$WORK/aligned.apk"
"$TOOLS/apksigner" verify --verbose "$APK"
"$TOOLS/aapt2" dump badging "$APK" | sed -n '1,12p'

pushd "$ROOT/packaging/windows" >/dev/null
wixl -D "Version=$VERSION" -o "$OUTPUT/Sketchbot-Launcher-$VERSION.msi" launcher.wxs
popd >/dev/null
msiinfo suminfo "$OUTPUT/Sketchbot-Launcher-$VERSION.msi"
printf '\nBuilt packages in %s\nAndroid signing material remains private in %s\n' "$OUTPUT" "$SIGNING_DIR"