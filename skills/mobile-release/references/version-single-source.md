# One version, two apps

How to keep Android `versionName`/`versionCode` and iOS `CFBundleShortVersionString`/`CFBundleVersion`
in one file, read by both builds.

Contents:

1. The source file
2. Android: read it in `build.gradle.kts`
3. Android: signing from environment variables
4. iOS: xcconfig synced from the same file
5. CI guard: fail when the two drift
6. Bumping

## 1. The source file

`gradle.properties` at the repository root (Gradle reads it natively; a shell or Ruby one-liner reads
it too):

```properties
app.versionName=1.4.0
app.versionCode=42
```

Prefer this over the version catalog for app versions: the catalog is for dependency versions, is
often shared across repositories, and is awkward to read from Xcode or shell scripts. A separate
`version.properties` works equally well if the team prefers; read it the same way.

## 2. Android: read it in `build.gradle.kts`

```kotlin
// androidApp/build.gradle.kts
val appVersionName = providers.gradleProperty("app.versionName").get()
val appVersionCode = providers.gradleProperty("app.versionCode").get().toInt()

android {
    namespace = "com.example.app"

    defaultConfig {
        applicationId = "com.example.app"
        versionCode = appVersionCode
        versionName = appVersionName   // clean MAJOR.MINOR.PATCH in every flavour
    }

    flavorDimensions += "environment"
    productFlavors {
        create("staging") {
            dimension = "environment"
            applicationIdSuffix = ".staging"   // installs side by side; no versionNameSuffix
        }
        create("production") {
            dimension = "environment"
        }
    }
}
```

Leave `versionNameSuffix` out. A suffix such as `1.4.0-staging` stops being plain semver, and
anything that compares versions — a backend minimum-version check, a remote-config update prompt,
crash-dashboard grouping — can misread it. Distinguish environments by `applicationIdSuffix` (and
app name/icon), not by the version string.

## 3. Android: signing from environment variables

Release signing reads CI-provided values and is configured only when they exist, so debug builds
and contributors without the keystore still build.

```kotlin
android {
    val keystorePath = providers.environmentVariable("ANDROID_KEYSTORE_PATH").orNull
    if (keystorePath != null) {
        signingConfigs {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = providers.environmentVariable("ANDROID_KEYSTORE_PASSWORD").get()
                keyAlias = providers.environmentVariable("ANDROID_KEY_ALIAS").get()
                keyPassword = providers.environmentVariable("ANDROID_KEY_PASSWORD").get()
            }
        }
        buildTypes {
            getByName("release") {
                signingConfig = signingConfigs.getByName("release")
            }
        }
    }
}
```

With Play App Signing, this keystore is the **upload** key; Google re-signs with the app signing
key. If the app checks its own signing certificate at runtime (tamper detection, API allowlists),
the allowlist must include the Play app signing certificate, not only the upload certificate.

## 4. iOS: xcconfig synced from the same file

In the Xcode target, set Info.plist to build-setting references (the default for projects created
by recent Xcode versions):

```text
CFBundleShortVersionString = $(MARKETING_VERSION)
CFBundleVersion            = $(CURRENT_PROJECT_VERSION)
```

Generate an xcconfig from `gradle.properties` and include it from the target's base xcconfig:

```bash
#!/usr/bin/env bash
# scripts/sync-ios-version.sh — run after every bump; CI checks the result is committed.
set -euo pipefail
name=$(sed -nE 's/^app\.versionName=(.*)$/\1/p' gradle.properties)
code=$(sed -nE 's/^app\.versionCode=(.*)$/\1/p' gradle.properties)
cat > iosApp/Configuration/Version.xcconfig <<EOF
// Generated from gradle.properties by scripts/sync-ios-version.sh. Do not edit.
MARKETING_VERSION = ${name}
CURRENT_PROJECT_VERSION = ${code}
EOF
```

```text
// iosApp/Configuration/Config.xcconfig
#include "Version.xcconfig"
```

Remove `MARKETING_VERSION` and `CURRENT_PROJECT_VERSION` from the target's build settings in the
Xcode project, or they override the xcconfig. Release builds from Fastlane also pass both values as
`xcargs`, so a forgotten sync cannot ship a wrong number.

Per-environment bundle ids on iOS mirror `applicationIdSuffix`: set `PRODUCT_BUNDLE_IDENTIFIER`
per build configuration (`com.example.app` and `com.example.app.staging`), never the version.

## 5. CI guard: fail when the two drift

```bash
bash scripts/sync-ios-version.sh
git diff --exit-code iosApp/Configuration/Version.xcconfig   # non-zero exit = bump not synced
```

The release workflow additionally checks that the pushed tag equals `app.versionName`.

## 6. Bumping

```bash
# Edit both keys in gradle.properties, then:
bash scripts/sync-ios-version.sh
git add gradle.properties iosApp/Configuration/Version.xcconfig
git commit -m "chore(release): bump to 1.4.0 (42)"
git tag -a android-v1.4.0 -m "Android 1.4.0 (42)"
git tag -a ios-v1.4.0 -m "iOS 1.4.0 (42)"
```

Push the commit and tags only when the user says so: `git push origin HEAD android-v1.4.0 ios-v1.4.0`.
