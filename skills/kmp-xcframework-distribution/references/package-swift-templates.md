# Package.swift templates and a publish script

Contents

1. Remote binary, no system libraries
2. Remote binary plus a wrapper target for linker settings
3. Local path binary for development
4. An intermediate Swift package that consumes the binary
5. Publish script outline (CI)
6. Consumer wiring
7. Private artifact hosts

Names: framework module `SharedKit` (= Gradle `baseName` = binary target name = zip name). Keep
those four identical; mismatches are a common source of `No such module`.

## 1. Remote binary, no system libraries

```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SharedKit",
    platforms: [.iOS(.v15)],               // not lower than the framework's minimum iOS version
    products: [
        .library(name: "SharedKit", targets: ["SharedKit"]),
    ],
    targets: [
        .binaryTarget(
            name: "SharedKit",
            url: "https://example.com/releases/1.4.0/SharedKit.xcframework.zip",
            checksum: "<swift package compute-checksum output>"
        ),
    ]
)
```

## 2. Remote binary plus a wrapper target for linker settings

A `binaryTarget` cannot declare `linkerSettings`. A static Kotlin framework that calls into a system
library (the classic case: a SQLite driver that uses the OS `libsqlite3`) therefore leaves every
consumer with `Undefined symbols` unless some regular target declares the library.

```swift
// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "SharedKit",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "SharedKit", targets: ["SharedKit", "SharedKitWrapper"]),
    ],
    targets: [
        .binaryTarget(
            name: "SharedKit",
            url: "https://example.com/releases/1.4.0/SharedKit.xcframework.zip",
            checksum: "<swift package compute-checksum output>"
        ),
        .target(
            name: "SharedKitWrapper",
            dependencies: ["SharedKit"],
            path: "Sources/SharedKitWrapper",
            linkerSettings: [
                .linkedLibrary("sqlite3"),
                // .linkedFramework("Security"),   // add any other system dependency here
            ]
        ),
    ]
)
```

`Sources/SharedKitWrapper/SharedKitWrapper.swift` — a target needs at least one source file:

```swift
// Exists so this target can carry linkerSettings for the SharedKit binary target.
import SharedKit
```

Find the system libraries a static framework needs by listing its undefined symbols:

```bash
nm -u SharedKit.xcframework/ios-arm64/SharedKit.framework/SharedKit | grep -E '_sqlite3_|_OBJC_CLASS_\$_' | sort -u | head
```

If the Kotlin side uses a *bundled* SQLite (for example `androidx.sqlite:sqlite-bundled`), do not
add `sqlite3` here: linking the system library next to a bundled copy can make the linker drop the
bundled one.

## 3. Local path binary for development

```swift
.binaryTarget(
    name: "SharedKit",
    path: "Frameworks/SharedKit.xcframework"   // relative to the package root
)
```

Copy (or symlink, if your setup tolerates it) the output of
`./gradlew :shared:assembleSharedKitDebugXCFramework` into `Frameworks/`. KMMBridge users can run
`./gradlew spmDevBuild -PspmBuildTargets=ios_simulator_arm64` (`ios_x64` on Intel Macs), which builds
a debug XCFramework and writes a local-dev path into `Package.swift`. Never commit either local form
in a release commit.

## 4. An intermediate Swift package that consumes the binary

When a Swift UI package (for example a feature package built on the app's SwiftUI design system)
depends on the binary package, it is the place to declare the linker settings — not every host app:

```swift
// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "NotesUI",
    platforms: [.iOS(.v17)],
    products: [.library(name: "NotesUI", targets: ["NotesUI"])],
    dependencies: [
        .package(url: "https://example.com/shared-kit-spm.git", from: "1.4.0"),
        .package(url: "https://example.com/design-system.git", from: "3.0.0"),
    ],
    targets: [
        .target(
            name: "NotesUI",
            dependencies: [
                .product(name: "SharedKit", package: "shared-kit-spm"),
                .product(name: "DesignSystem", package: "design-system"),
            ],
            linkerSettings: [.linkedLibrary("sqlite3")]   // only if SharedKit's package lacks the wrapper
        ),
    ]
)
```

Hosts then add only `NotesUI`. Its `platforms` must not be lower than the binary package's.

## 5. Publish script outline (CI)

Adapt to your CI. The ordering is what matters: build → zip → checksum → upload → write manifest →
commit → tag → push, and refuse to run twice for the same version.

```bash
#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?usage: publish-xcframework.sh <semver>}"
NAME="SharedKit"
OUT="shared/build/XCFrameworks/release"

# Refuse to republish: tags are immutable contracts with SPM consumers.
if git ls-remote --exit-code --tags origin "refs/tags/${VERSION}" >/dev/null 2>&1; then
  echo "tag ${VERSION} already exists on origin — bump the version instead" >&2
  exit 1
fi

./gradlew ":shared:assemble${NAME}ReleaseXCFramework"

( cd "$OUT" && rm -f "${NAME}.xcframework.zip" \
  && ditto -c -k --sequesterRsrc --keepParent "${NAME}.xcframework" "${NAME}.xcframework.zip" )
CHECKSUM="$(swift package compute-checksum "${OUT}/${NAME}.xcframework.zip")"

# Upload with your host's CLI or API; it must print or imply a stable, versioned URL.
URL="https://example.com/releases/${VERSION}/${NAME}.xcframework.zip"
# upload_artifact "${OUT}/${NAME}.xcframework.zip" "$URL"     # placeholder

# Rewrite the binary target in Package.swift (template kept in the repo).
sed -e "s|__URL__|${URL}|" -e "s|__CHECKSUM__|${CHECKSUM}|" Package.swift.template > Package.swift

curl -fsIL "$URL" >/dev/null   # fail before tagging if the artifact is not downloadable

git add Package.swift
git commit -m "release: ${NAME} ${VERSION}"
git tag "${VERSION}"
git push origin HEAD "refs/tags/${VERSION}"
```

For a repo that also tags other platforms, those jobs use prefixed tags (`android-v${VERSION}`), so
this job's existence check stays unambiguous.

## 6. Consumer wiring

1. Xcode → File → Add Package Dependencies… → package URL → rule "Up to Next Major" from the version.
2. Add the `SharedKit` product to the app target (and to any extension that imports it).
3. `import SharedKit` in Swift.
4. Commit `Package.resolved` so CI resolves the same version:
   `xcodebuild -resolvePackageDependencies -project App.xcodeproj -scheme App`.
5. Static framework: no "Embed & Sign" entry for it. Each extension that links it gets its own copy
   of the Kotlin runtime and state.

## 7. Private artifact hosts

SwiftPM downloads binary targets over HTTPS with the user's credentials. Typical options:

- `~/.netrc` entry for the artifact host (hostname only, no path) with a read-only token from the
  developer's own secret store — never commit it.
- macOS keychain entries for the host.
- CI: write the netrc file from a CI secret at job start, delete it at the end.

Check access exactly as Xcode will: `curl -fsIL --netrc "<zip url>"`.
