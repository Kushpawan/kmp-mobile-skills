---
name: kmp-room-database
description: Use when adding, configuring or debugging Room in a Kotlin Multiplatform project — @Database, @Dao, @Entity in commonMain, RoomDatabaseConstructor, BundledSQLiteDriver, KSP per target, schema export, migrations, @AutoMigration — or on "Cannot find the associated RoomDatabaseConstructor", "_Impl does not exist", SQLITE_MISUSE or undefined _sqlite3_ symbols on iOS, a migration crash after an app update, or Flows that stop updating.
license: Apache-2.0
compatibility: Kotlin Multiplatform project (Android + iOS) with Room 2.7+ (androidx.room) or Room 3.x (androidx.room3) and KSP. iOS steps need macOS with Xcode.
metadata:
  category: data
  platforms: android, ios
---

# Room in Kotlin Multiplatform

Entities, DAOs and the `@Database` class live in `commonMain`; only the file path is platform code.
Most Room KMP failures compile cleanly and crash at runtime on one platform — a missing KSP target,
the wrong SQLite on the iOS link line, a missing migration. So this skill checks the build wiring as
carefully as the Kotlin.

## When to use

- Adding Room to a KMP module, or adding entities, DAOs or a migration.
- A Room error: `Cannot find the associated androidx.room.RoomDatabaseConstructor for ... Is Room
  annotation processor correctly configured?` (iOS), `Cannot find implementation for ... _Impl does
  not exist` (Android), `SQLITE_MISUSE`, `Undefined symbols ... _sqlite3_...`, `Migration didn't
  properly handle`, `A migration from N to M was required but not found`.
- A DAO `Flow` that does not emit after writes.

## When not to use

- The project uses **SQLDelight** — follow SQLDelight (<https://sqldelight.github.io/sqldelight/>);
  do not add Room beside it. The iOS SQLite linking rules in [references/ios-sqlite-linking.md](references/ios-sqlite-linking.md) still apply.
- Key-value settings — DataStore or multiplatform-settings.
- Tokens and secrets — **kmp-secure-storage**. Never store a token in a plain Room table.
- Repository, caching and sync design — **kmp-data-layer**.

## Step 0 — Read the project first

```bash
grep -nE "room|sqlite|ksp|sqldelight" gradle/libs.versions.toml
grep -rnE "ksp(Android|Ios|CommonMainMetadata)|room3? *\{|linkerOpts|lsqlite3" --include=*.gradle.kts .
grep -rnE "ios(Arm64|SimulatorArm64|X64)\(\)|jvm\(\)|androidTarget|androidLibrary" --include=*.gradle.kts .
grep -rnE "@Database|RoomDatabaseConstructor|setDriver|setQueryCoroutineContext" --include=*.kt .
```

| Finding | Then |
|---|---|
| `androidx.room:*`, plugin `androidx.room`, `room { }` | Room 2.x. Examples below are written for it. |
| `androidx.room3:*`, plugin `androidx.room3`, `room3 { }`, imports `androidx.room3.*` | Room 3.x: same shape, new package names; DAO functions must be `suspend` or return `Flow`; a driver is mandatory. |
| SQLDelight | Stop; see **When not to use**. |
| Existing driver | Keep it. Switching `NativeSQLiteDriver` ↔ `BundledSQLiteDriver` changes the iOS link rules. |
| Declared targets | Each one needs a KSP line (step 2). |
| Existing `@Database` | Add to it. One database per app unless you have a reason. |

Do not upgrade Room's major version as a side effect of another task.

## Workflow

### 1. Catalog and plugins

```toml
# gradle/libs.versions.toml — keep versions the catalog already pins
[libraries]
androidx-room-runtime = { module = "androidx.room:room-runtime", version.ref = "room" }
androidx-room-compiler = { module = "androidx.room:room-compiler", version.ref = "room" }
androidx-sqlite-bundled = { module = "androidx.sqlite:sqlite-bundled", version.ref = "sqlite" }

[plugins]
ksp = { id = "com.google.devtools.ksp", version.ref = "ksp" }     # a KSP release built for your Kotlin version
androidx-room = { id = "androidx.room", version.ref = "room" }
```

```kotlin
// shared/build.gradle.kts
plugins {
    alias(libs.plugins.ksp)
    alias(libs.plugins.androidx.room)
}

kotlin {
    // keep the project's existing target declarations
    sourceSets {
        commonMain.dependencies {
            implementation(libs.androidx.room.runtime)
            implementation(libs.androidx.sqlite.bundled)
        }
    }
}

room {
    schemaDirectory("$projectDir/schemas")      // required by the plugin; commit this directory
}
```

### 2. KSP for every target

```kotlin
// shared/build.gradle.kts — top-level dependencies block, one line per declared target
dependencies {
    add("kspAndroid", libs.androidx.room.compiler)
    add("kspIosArm64", libs.androidx.room.compiler)
    add("kspIosSimulatorArm64", libs.androidx.room.compiler)
    add("kspIosX64", libs.androidx.room.compiler)        // only if iosX64() is declared
    // add("kspJvm", ...) for a jvm() target, and so on
}
```

**A missing line compiles and then crashes on that platform** the first time the database is built:
iOS throws `Cannot find the associated RoomDatabaseConstructor`, Android throws
`Cannot find implementation for ...`. Do not add the compiler to `kspCommonMainMetadata` — the
generated `actual` objects belong to each platform compilation.

Done when the two lists match:

```bash
grep -oE "ios(Arm64|SimulatorArm64|X64)\(\)" shared/build.gradle.kts | sort -u
grep -oE "\"ksp(Android|IosArm64|IosSimulatorArm64|IosX64|Jvm)\"" shared/build.gradle.kts | sort -u
```

### 3. Entities and DAOs — `commonMain`

```kotlin
// commonMain — articles/data/local/ArticleEntity.kt
@Entity(tableName = "articles")
data class ArticleEntity(
    @PrimaryKey val id: String,
    val title: String,
    val body: String,
    @ColumnInfo(name = "updated_at") val updatedAtEpochMillis: Long,
    @ColumnInfo(name = "is_bookmarked", defaultValue = "0") val isBookmarked: Boolean = false,
)
```

```kotlin
// commonMain — articles/data/local/ArticleDao.kt
@Dao
abstract class ArticleDao {
    @Query("SELECT * FROM articles ORDER BY updated_at DESC")
    abstract fun observeAll(): Flow<List<ArticleEntity>>

    @Query("SELECT * FROM articles WHERE id = :id")
    abstract suspend fun findById(id: String): ArticleEntity?

    @Upsert
    abstract suspend fun upsertAll(articles: List<ArticleEntity>)

    @Query("DELETE FROM articles")
    abstract suspend fun deleteAll()

    /** One transaction, so observers never see the empty table between the two statements. */
    @Transaction
    open suspend fun replaceAll(articles: List<ArticleEntity>) {
        deleteAll()
        upsertAll(articles)
    }
}
```

- Every DAO function in common code is `suspend` or returns `Flow`. Blocking DAO functions, `LiveData`
  and RxJava types are Android-only.
- Give every non-null column you add later a `defaultValue`, or the migration cannot fill old rows.
- Entities are storage types. Map them to domain models in the repository (**kmp-data-layer**).

### 4. Database and constructor — `commonMain`

```kotlin
// commonMain — core/database/AppDatabase.kt
@Database(entities = [ArticleEntity::class], version = 1, exportSchema = true)
@ConstructedBy(AppDatabaseConstructor::class)
abstract class AppDatabase : RoomDatabase() {
    abstract fun articleDao(): ArticleDao
}

// Room's KSP processor generates the `actual` object for each target.
@Suppress("KotlinNoActualForExpect")
expect object AppDatabaseConstructor : RoomDatabaseConstructor<AppDatabase> {
    override fun initialize(): AppDatabase
}

internal const val DATABASE_NAME = "app.db"
```

The IDE may flag the `expect` object as having no `actual`; the suppression is the documented fix.

### 5. Platform builders — the only platform code

```kotlin
// androidMain — core/database/DatabaseBuilder.android.kt
fun databaseBuilder(context: Context): RoomDatabase.Builder<AppDatabase> {
    val appContext = context.applicationContext
    val dbFile = appContext.getDatabasePath(DATABASE_NAME)
    return Room.databaseBuilder<AppDatabase>(context = appContext, name = dbFile.absolutePath)
}
```

```kotlin
// iosMain — core/database/DatabaseBuilder.ios.kt
fun databaseBuilder(): RoomDatabase.Builder<AppDatabase> =
    Room.databaseBuilder<AppDatabase>(name = documentDirectory() + "/$DATABASE_NAME")

@OptIn(ExperimentalForeignApi::class)
private fun documentDirectory(): String {
    val url = NSFileManager.defaultManager.URLForDirectory(
        directory = NSDocumentDirectory,
        inDomain = NSUserDomainMask,
        appropriateForURL = null,
        create = false,
        error = null,
    )
    return requireNotNull(url?.path) { "Documents directory unavailable" }
}
```

- `NSHomeDirectory()` itself is not writable — use a directory inside it. `Library/Caches` and
  `tmp` can be purged by the OS; never put a source-of-truth database there.
- `NSApplicationSupportDirectory` keeps the file out of the user-visible Documents folder; pass
  `create = true`, because it does not exist on first launch.

### 6. Build once, in common code

```kotlin
// commonMain — core/database/AppDatabaseFactory.kt
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.IO                     // Dispatchers.IO is an extension outside the JVM

fun createAppDatabase(builder: RoomDatabase.Builder<AppDatabase>): AppDatabase =
    builder
        .setDriver(BundledSQLiteDriver())         // same SQLite version on every platform
        .setQueryCoroutineContext(Dispatchers.IO)
        .addMigrations(*AppMigrations.ALL)
        .build()
```

Provide it as a singleton — **one instance per database file per process**. Room's invalidation
tracker only sees writes made through the same `RoomDatabase` instance, so a second instance makes
`Flow`s miss changes. With Koin:

```kotlin
// androidMain:  single { databaseBuilder(androidContext()) }
// iosMain:      single { databaseBuilder() }
// commonMain:
val databaseModule = module {
    single { createAppDatabase(builder = get()) }
    single { get<AppDatabase>().articleDao() }
}
```

### 7. iOS linking — pick the driver, then follow its rule

| Driver | `-lsqlite3` | Why |
|---|---|---|
| `BundledSQLiteDriver` (recommended) | **Do not add it** | The driver ships its own SQLite. Adding the system library puts two providers of every `sqlite3_*` symbol on the link line. |
| `NativeSQLiteDriver` | **Required** on every binary, tests included: `binaries.all { linkerOpts("-lsqlite3") }` | Without it: `Undefined symbols ... _sqlite3_...`. |

Observed with the bundled driver: a large static iOS framework shipped without the bundled SQLite
because `-lsqlite3` was also on the link line, iOS fell back to the system library, and the app
crashed with `SQLITE_MISUSE` on iOS 26. Diagnosis, verification with `nm`, and where `-lsqlite3`
sneaks in: [references/ios-sqlite-linking.md](references/ios-sqlite-linking.md).

### 8. Migrations — from the first release on

Once a build ships, every schema change bumps `version` and comes with a migration.

```kotlin
@Database(
    entities = [ArticleEntity::class],
    version = 2,
    autoMigrations = [AutoMigration(from = 1, to = 2)],   // e.g. a column with a defaultValue was added
)
```

- Auto-migrations need the exported JSON for **both** versions in `schemas/` — commit it.
- Renames and deletions need an `AutoMigrationSpec` (`@RenameColumn`, `@DeleteColumn`, `@RenameTable`,
  `@DeleteTable`); anything else gets a manual `Migration`.
- `fallbackToDestructiveMigration(dropAllTables = true)` deletes user data. Use it only for a pure
  cache that can be refetched — never for a table holding unsynced writes.

Manual migrations, specs, Room 3 differences and migration tests:
[references/migrations-and-testing.md](references/migrations-and-testing.md).

### 9. Transactions

| Scope | API (Room 2.7+, common code) |
|---|---|
| Inside one DAO | `@Transaction open suspend fun` in an abstract-class DAO (step 3) |
| Across DAOs, write | `database.useWriterConnection { it.immediateTransaction { articleDao.deleteAll(); tagDao.upsertAll(tags) } }` |
| Consistent multi-query read | `database.useReaderConnection { it.deferredTransaction { ... } }` |
| Room 3.x | also `database.withWriteTransaction { ... }` |

`withTransaction { }` from `room-ktx` is Android-only; it does not compile in `commonMain`.
`useReaderConnection` allows only `deferredTransaction`; immediate or exclusive throws.

### 10. Tests

- **Repository and ViewModel tests:** fake the data source behind an interface — no database.
- **DAO and migration tests:** a real in-memory database with the bundled driver:

```kotlin
// iosTest (and jvmTest if the project has a jvm() target)
fun inMemoryDatabase(): AppDatabase =
    Room.inMemoryDatabaseBuilder<AppDatabase>()
        .setDriver(BundledSQLiteDriver())
        .build()

// Android instrumented test (androidInstrumentedTest / androidTest)
fun inMemoryDatabase(context: Context): AppDatabase =
    Room.inMemoryDatabaseBuilder<AppDatabase>(context)
        .setDriver(BundledSQLiteDriver())
        .build()
```

Android host unit tests have no `Context`; Google recommends JVM tests through Room KMP over
Robolectric. Close the database in `@AfterTest`. A `@Database` declared only in test sources needs
its own KSP test configuration (for example `kspIosSimulatorArm64Test`). Full DAO test template:
[references/migrations-and-testing.md](references/migrations-and-testing.md).

## Quick reference

| Item | Rule |
|---|---|
| Location | Entities, DAOs, `@Database`, `expect object ...Constructor` in `commonMain` |
| Platform code | Only `databaseBuilder(...)`: Android `getDatabasePath`, iOS Documents or Application Support |
| KSP | `kspAndroid` + one `kspIos…` per iOS target (+ `kspJvm`, …); never `kspCommonMainMetadata` |
| Driver | `BundledSQLiteDriver`; `setQueryCoroutineContext(Dispatchers.IO)` with `import kotlinx.coroutines.IO` |
| DAO shape | `suspend` or `Flow` only |
| Instance | One per file per process (DI `single`) |
| Schemas | `room { schemaDirectory("$projectDir/schemas") }`, committed |
| Migrations | Every shipped schema change; auto-migration where possible |
| iOS linker | Bundled: no `-lsqlite3`. Native: `-lsqlite3` on all binaries |
| Cross-DAO transaction | `useWriterConnection { it.immediateTransaction { } }` |

## Verify

Report each as `PASS`, `FAIL` or `NOT RUN` (with the reason). A green compile is not evidence the
database opens on iOS — run the iOS tests or the app.

```bash
./gradlew :shared:tasks --all | grep -iE "^ksp"          # one KSP task per target exists
./gradlew :shared:iosSimulatorArm64Test                  # DAO tests on Kotlin/Native
./gradlew :shared:allTests
./gradlew :shared:linkDebugFrameworkIosSimulatorArm64    # framework links (undefined _sqlite3_ symbols show here)
./gradlew :composeApp:assembleDebug
find shared/schemas -name "*.json" | sort                # one JSON per version, committed
grep -n "lsqlite3" shared/build.gradle.kts               # must be empty with BundledSQLiteDriver
```

Then open the database once on a real iOS device or simulator (any screen that reads it). If the
project has an iOS UI test or smoke test, run it.

## Common mistakes

| Mistake | Why it bites | Fix |
|---|---|---|
| KSP line missing for one target | Compiles; crashes on first database access on that platform | One `ksp<Target>` per declared target |
| Room compiler on `kspCommonMainMetadata` | Duplicate or misplaced generated code | Platform KSP configurations only |
| `-lsqlite3` with `BundledSQLiteDriver` | Two SQLite providers; observed: bundled copy dropped, `SQLITE_MISUSE` on iOS | Remove it; verify with `nm` |
| `NativeSQLiteDriver` without `-lsqlite3` on test binaries | Framework links, `iosSimulatorArm64Test` fails with undefined symbols | `binaries.all { linkerOpts("-lsqlite3") }` |
| Database under `NSHomeDirectory()` root or `Caches` | Not writable, or purged by the OS | Documents or Application Support |
| Two `RoomDatabase` instances on one file | `Flow`s miss writes from the other instance | DI `single` |
| `Dispatchers.IO` unresolved in `commonMain` | It is an extension property outside the JVM | `import kotlinx.coroutines.IO` |
| Schema change without version bump or migration | `Room cannot verify the data integrity` or `A migration from N to M was required but not found` at open after an update | Bump `version`, add an auto or manual migration |
| `schemas/` not committed | Auto-migrations cannot be generated on CI or a teammate's machine | Commit the JSON files |
| New non-null column without `defaultValue` | Migration cannot fill existing rows | `@ColumnInfo(defaultValue = ...)` or nullable |
| `fallbackToDestructiveMigration` on user data | Silent data loss after an update | Only for refetchable caches |
| `withTransaction` in common code | Android-only API | `useWriterConnection { it.immediateTransaction { } }` |
| Token or password in a Room column | Readable on rooted or backed-up devices | **kmp-secure-storage** |

## Related skills

- **kmp-data-layer** — repositories, offline-first reads, write-through refresh.
- **kmp-koin-di** — providing the database and DAOs per platform.
- **kmp-secure-storage** — secrets that must not live in Room; wiping tables on logout.
- **kmp-xcframework-distribution** — shipping the shared framework to iOS consumers.
- **kmp-crash-triage** — symbolicating an iOS crash that ends in SQLite.
- Room KMP setup: <https://developer.android.com/kotlin/multiplatform/room>
- Room migrations: <https://developer.android.com/training/data-storage/room/migrating-db-versions>
- Room 3 release notes: <https://developer.android.com/jetpack/androidx/releases/room3>
