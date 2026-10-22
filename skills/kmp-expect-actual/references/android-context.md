# Android actuals: getting a Context without leaking it

`androidMain` code often needs a `Context`. The rule: long-lived objects hold only the
**application** context, and it arrives from outside rather than being fetched from a global.

## Contents

1. [Preferred: constructor injection from DI](#1-preferred-constructor-injection-from-di)
2. [Library without DI: androidx.startup](#2-library-without-di-androidxstartup)
3. [Existing global holder](#3-existing-global-holder)
4. [APIs that need an Activity](#4-apis-that-need-an-activity)
5. [Testing Android actuals](#5-testing-android-actuals)

## 1. Preferred: constructor injection from DI

```kotlin
// androidApp: Application
class NotesApplication : Application() {
    override fun onCreate() {
        super.onCreate()
        startKoin {
            androidContext(this@NotesApplication)   // koin-android
            modules(sharedModules + platformDataModule)
        }
    }
}

// shared/androidMain
actual val platformDataModule: Module = module {
    single<NoteDraftStore> { AndroidNoteDraftStore(androidContext()) }
}
```

`androidContext()` returns the `Application`, so nothing leaks. The implementation still calls
`context.applicationContext` defensively in case someone constructs it by hand with an `Activity`.

## 2. Library without DI: androidx.startup

A published KMP library cannot assume the host app uses Koin. `androidx.startup` runs an initializer
before `Application.onCreate` and hands it the application context. It needs the
`androidx.startup:startup-runtime` dependency in `androidMain`.

```kotlin
// androidMain
internal object NotesSdkContext {
    lateinit var appContext: Context
        private set

    fun init(context: Context) { appContext = context.applicationContext }
}

class NotesSdkInitializer : Initializer<Unit> {
    override fun create(context: Context) = NotesSdkContext.init(context)
    override fun dependencies(): List<Class<out Initializer<*>>> = emptyList()
}
```

```xml
<!-- androidMain/AndroidManifest.xml -->
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:tools="http://schemas.android.com/tools">
    <application>
        <provider
            android:name="androidx.startup.InitializationProvider"
            android:authorities="${applicationId}.androidx-startup"
            android:exported="false"
            tools:node="merge">
            <meta-data
                android:name="com.example.app.notes.NotesSdkInitializer"
                android:value="androidx.startup" />
        </provider>
    </application>
</manifest>
```

## 3. Existing global holder

Some projects already have an `object AppContext { lateinit var context: Context }` set in
`Application.onCreate`. Reuse it rather than adding a second mechanism, and confirm it stores
`applicationContext`. Do not introduce one in a project that has DI; it hides the dependency and
breaks host tests that never run `Application.onCreate`.

## 4. APIs that need an Activity

Runtime permissions, biometric prompts, share sheets, in-app review and the Activity Result API all
need an `Activity`. Do not store one in a singleton: rotation and process recreation replace it, and
the old instance leaks.

Options, best first:

1. **Keep the call in the UI layer.** Trigger it from a composable or Activity and pass the result
   into shared code. Shared code exposes intent (`requestCameraPermission()` as an effect) and
   receives the outcome.
2. **Track the current Activity weakly.** Register `ActivityLifecycleCallbacks` once in the
   `Application` and keep a `WeakReference` to the resumed Activity:

```kotlin
// androidMain
class CurrentActivityTracker(application: Application) {
    private var resumed: WeakReference<Activity>? = null
    val activity: Activity? get() = resumed?.get()

    init {
        application.registerActivityLifecycleCallbacks(object : Application.ActivityLifecycleCallbacks {
            override fun onActivityResumed(activity: Activity) { resumed = WeakReference(activity) }
            override fun onActivityPaused(activity: Activity) {
                if (resumed?.get() === activity) resumed = null
            }
            override fun onActivityCreated(activity: Activity, savedInstanceState: Bundle?) = Unit
            override fun onActivityStarted(activity: Activity) = Unit
            override fun onActivityStopped(activity: Activity) = Unit
            override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
            override fun onActivityDestroyed(activity: Activity) = Unit
        })
    }
}
```

   Callers must handle `activity == null` (app in background) as a normal outcome.

3. **Start an Activity from the application context** only for fire-and-forget intents, with
   `Intent.FLAG_ACTIVITY_NEW_TASK`.

## 5. Testing Android actuals

- Consumers of the interface: `commonTest` with a fake. No Android runtime needed.
- The actual itself: a host test (`androidHostTest`, task `testAndroidHostTest` with the AGP KMP
  library plugin) using Robolectric for framework classes such as `SharedPreferences`, or a device
  test (`androidDeviceTest`) on an emulator. With the AGP KMP library plugin both are disabled until
  `withHostTest {}` / `withDeviceTest {}` is declared in `kotlin { android { } }`.
