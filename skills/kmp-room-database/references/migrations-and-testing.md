# Room KMP migrations and tests

APIs shown are Room 2.7+ (`androidx.room`). Room 3.x differences are called out where they matter.

## Contents

1. [Before the first release](#1-before-the-first-release)
2. [Auto-migrations](#2-auto-migrations)
3. [Manual migrations](#3-manual-migrations)
4. [Destructive fallback](#4-destructive-fallback)
5. [DAO tests](#5-dao-tests)
6. [Migration tests](#6-migration-tests)
7. [Faking the database in repository tests](#7-faking-the-database-in-repository-tests)

## 1. Before the first release

Until a build with the database reaches users, you may change the schema in place at `version = 1`
— nobody has an old file. From the first release on, every change bumps `version` and ships with a
migration. Decide which phase you are in from the release tags, not from memory; a single internal
beta that reached testers counts as a release.

Changing the schema without bumping the version fails at open with
`Room cannot verify the data integrity`.

## 2. Auto-migrations

Room generates the migration from the exported schemas of both versions. They must be in
`schemas/` (from `room { schemaDirectory(...) }`) and committed.

```kotlin
@Database(
    entities = [ArticleEntity::class, TagEntity::class],
    version = 3,
    autoMigrations = [
        AutoMigration(from = 1, to = 2),                                   // added a column with defaultValue
        AutoMigration(from = 2, to = 3, spec = AppMigrations.Spec2To3::class),
    ],
)
@ConstructedBy(AppDatabaseConstructor::class)
abstract class AppDatabase : RoomDatabase() { /* DAOs */ }
```

Renames and deletions are ambiguous, so Room needs a spec:

```kotlin
// commonMain — core/database/AppMigrations.kt
import androidx.room.DeleteColumn
import androidx.room.RenameColumn
import androidx.room.migration.AutoMigrationSpec
import androidx.room.migration.Migration
import androidx.sqlite.SQLiteConnection
import androidx.sqlite.execSQL

object AppMigrations {

    @RenameColumn(tableName = "articles", fromColumnName = "body", toColumnName = "content")
    @DeleteColumn(tableName = "articles", columnName = "legacy_flags")
    class Spec2To3 : AutoMigrationSpec {
        override fun onPostMigrate(connection: SQLiteConnection) {
            // optional data fix-up after the generated SQL ran
        }
    }

    val MIGRATION_3_4 = object : Migration(3, 4) {
        override fun migrate(connection: SQLiteConnection) {
            // Full literal SQL — never build it from constants that may change later.
            connection.execSQL("ALTER TABLE articles ADD COLUMN author TEXT")
            connection.execSQL("UPDATE articles SET author = 'unknown' WHERE author IS NULL")
        }
    }

    val ALL: Array<Migration> = arrayOf(MIGRATION_3_4)
}
```

`@RenameTable` and `@DeleteTable` work the same way. If a manual and an auto-migration cover the
same versions, Room uses the manual one.

## 3. Manual migrations

- Room 2.7+ in common code: `Migration.migrate(connection: SQLiteConnection)` with
  `androidx.sqlite.execSQL`. The `SupportSQLiteDatabase` overload is Android-only.
- Room 3.x: `migrate` is a `suspend` function. Use the SQL execution helper of the `androidx.sqlite`
  version you depend on (check its API reference); the shape is otherwise the same.
- Adding a `NOT NULL` column needs a `DEFAULT` in the SQL and the same `defaultValue` in
  `@ColumnInfo`, or Room's post-migration validation fails with `Migration didn't properly handle`.
- Copy-table migrations (create new, copy, drop old, rename) are needed for changes SQLite's
  `ALTER TABLE` cannot express. Recreate the table's indices afterwards.
- Register: `builder.addMigrations(*AppMigrations.ALL)`.

## 4. Destructive fallback

```kotlin
builder.fallbackToDestructiveMigration(dropAllTables = true)          // any missing path wipes data
builder.fallbackToDestructiveMigrationOnDowngrade(dropAllTables = true) // only on downgrade
builder.fallbackToDestructiveMigrationFrom(dropAllTables = true, 1, 2)  // only from listed versions
```

Allowed for a pure cache the app can refetch. Not allowed for tables holding pending offline writes
or anything the user created — the wipe is silent.

## 5. DAO tests

Run DAO tests against a real in-memory database with the bundled driver, on the iOS simulator (and on
a `jvm()` target if the project has one). Android host tests have no `Context`; use instrumented
tests or rely on the iOS/JVM run for shared DAO logic.

```kotlin
// iosTest — core/database/ArticleDaoTest.kt
class ArticleDaoTest {

    private lateinit var database: AppDatabase
    private lateinit var dao: ArticleDao

    @BeforeTest
    fun setUp() {
        database = Room.inMemoryDatabaseBuilder<AppDatabase>()
            .setDriver(BundledSQLiteDriver())
            .build()
        dao = database.articleDao()
    }

    @AfterTest
    fun tearDown() {
        database.close()
    }

    @Test
    fun should_emitNewestFirst_when_articlesUpserted() = runTest {
        dao.upsertAll(listOf(article(id = "a", updatedAt = 1), article(id = "b", updatedAt = 2)))

        assertEquals(listOf("b", "a"), dao.observeAll().first().map { it.id })
    }

    @Test
    fun should_replaceAllRows_when_replaceAllCalled() = runTest {
        dao.upsertAll(listOf(article(id = "old", updatedAt = 1)))

        dao.replaceAll(listOf(article(id = "new", updatedAt = 2)))

        assertEquals(listOf("new"), dao.observeAll().first().map { it.id })
    }

    private fun article(id: String, updatedAt: Long) =
        ArticleEntity(id = id, title = "t", body = "b", updatedAtEpochMillis = updatedAt)
}
```

- DAO suspend functions run on Room's query context, not the test dispatcher. Await them directly;
  `advanceUntilIdle()` does not wait for Room.
- To assert a sequence of `Flow` emissions use Turbine if the project has it; otherwise collect into
  a list in a `backgroundScope` job.

## 6. Migration tests

Google documents `MigrationTestHelper` from `room-testing` (`androidx.room3:room3-testing` for Room
3) for Android instrumented tests: create the database at the old version with raw SQL, run the
migration, and let the helper validate the schema against the exported JSON.

```kotlin
// androidInstrumentedTest — core/database/MigrationTest.kt
@RunWith(AndroidJUnit4::class)
class MigrationTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @get:Rule
    val helper = MigrationTestHelper(
        instrumentation = instrumentation,
        databaseClass = AppDatabase::class,
        driver = BundledSQLiteDriver(),
        file = instrumentation.targetContext.getDatabasePath("migration-test.db"),
    )

    @Test
    fun should_keepRows_when_migrating3To4() = runTest {
        val v3 = helper.createDatabase(3)
        v3.execSQL("INSERT INTO articles (id, title, content, updated_at, is_bookmarked) VALUES ('a', 't', 'c', 1, 0)")
        v3.close()

        val v4 = helper.runMigrationsAndValidate(4, listOf(AppMigrations.MIGRATION_3_4))
        val author = v4.prepare("SELECT author FROM articles WHERE id = 'a'").use { it.step(); it.getText(0) }

        assertEquals("unknown", author)
        v4.close()
    }
}
```

The constructor above is the driver-based form in Google's current documentation; older Room
versions take `(instrumentation, databaseClass)` and return a `SupportSQLiteDatabase`. Match the
constructor your `room-testing` version exposes.

Also keep one test that opens the **latest** database over a version-1 file with every migration
registered — it catches a gap in the chain. Whether `room-testing` offers a driver-based helper for
iOS or JVM tests depends on the Room version; check its API reference before relying on it.

## 7. Faking the database in repository tests

Repository tests should not need SQLite. Put a small interface between the repository and the DAO
when the repository logic is worth testing on its own:

```kotlin
// commonMain
interface ArticleStore {
    fun observeAll(): Flow<List<ArticleEntity>>
    suspend fun replaceAll(articles: List<ArticleEntity>)
}

class RoomArticleStore(private val articleDao: ArticleDao) : ArticleStore {
    override fun observeAll() = articleDao.observeAll()
    override suspend fun replaceAll(articles: List<ArticleEntity>) = articleDao.replaceAll(articles)
}

// commonTest
class InMemoryArticleStore : ArticleStore {
    private val rows = MutableStateFlow<List<ArticleEntity>>(emptyList())
    override fun observeAll(): Flow<List<ArticleEntity>> = rows.map { list -> list.sortedByDescending { it.updatedAtEpochMillis } }
    override suspend fun replaceAll(articles: List<ArticleEntity>) { rows.value = articles }
}
```

Keep the fake's behaviour (ordering, replace semantics) identical to the DAO's — the DAO test in
section 5 is what proves the real one matches.
