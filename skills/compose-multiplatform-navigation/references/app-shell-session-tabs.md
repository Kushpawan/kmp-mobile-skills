# App shell: session gate, session expiry and bottom tabs

A complete, typed shell for a notes app: splash while the session resolves, a signed-out graph, a
signed-in tab host with one back stack per tab, session-expiry handling and a pending deep link that
opens after sign-in. Adapt names, DI and the screen contract to the project.

`MviViewModel` / `CollectEffects` are the small helpers described in the
`compose-multiplatform-screen` skill; use the project's own equivalents if they exist.

Contents

1. [Routes](#1-routes)
2. [Session contract](#2-session-contract)
3. [Shell ViewModel](#3-shell-viewmodel)
4. [Root host](#4-root-host)
5. [Tab host](#5-tab-host)
6. [Android splash hold](#6-android-splash-hold)
7. [Shell ViewModel tests](#7-shell-viewmodel-tests)

## 1. Routes

```kotlin
// Root host
@Serializable data object SplashRoute
@Serializable data object AuthGraph
@Serializable data object SignInRoute
@Serializable data object MainRoute                                  // hosts the tab NavHost
@Serializable data class NoteDetailRoute(val noteId: String)         // full-screen, deep-linkable
@Serializable data class NoteEditorRoute(val noteId: String? = null)

// Tab host
@Serializable data object NotesTab
@Serializable data object NotesListRoute
@Serializable data object ProfileTab
@Serializable data object ProfileRoute
@Serializable data object SettingsRoute
```

## 2. Session contract

The data layer knows *why* the user is signed out (explicit sign-out vs failed token refresh), so it
reports it:

```kotlin
enum class SessionState { Unknown, SignedIn, SignedOut, Expired }

interface SessionRepository {
    /** Starts with Unknown until the token store has been read. */
    val session: Flow<SessionState>
}

/** Parsed in commonMain from an incoming URI; independent of navigation types. */
sealed interface DeepLinkTarget {
    data class Note(val noteId: String) : DeepLinkTarget
}
```

## 3. Shell ViewModel

```kotlin
data class AppShellUiState(
    val session: SessionState = SessionState.Unknown,
    val pendingDeepLink: DeepLinkTarget? = null,
    val isSessionExpiredDialogVisible: Boolean = false,
)

sealed interface AppShellAction {
    data class DeepLinkReceived(val target: DeepLinkTarget) : AppShellAction
    data object SessionExpiredDialogDismissed : AppShellAction
}

sealed interface AppShellEffect {
    data object ShowMain : AppShellEffect
    data object ShowSignIn : AppShellEffect
    data class Open(val target: DeepLinkTarget) : AppShellEffect
}

class AppShellViewModel(
    sessionRepository: SessionRepository,
) : MviViewModel<AppShellUiState, AppShellEffect>(initialState = AppShellUiState()) {

    init {
        viewModelScope.launch {
            sessionRepository.session
                .filter { it != SessionState.Unknown }
                .distinctUntilChanged()
                .collect(::onSessionChanged)
        }
    }

    fun onAction(action: AppShellAction) {
        when (action) {
            is AppShellAction.DeepLinkReceived ->
                if (currentState.session == SessionState.SignedIn) {
                    sendEffect(AppShellEffect.Open(action.target))
                } else {
                    updateState { copy(pendingDeepLink = action.target) }   // replayed after sign-in
                }
            AppShellAction.SessionExpiredDialogDismissed ->
                updateState { copy(isSessionExpiredDialogVisible = false) }
        }
    }

    private fun onSessionChanged(session: SessionState) {
        val pending = currentState.pendingDeepLink
        updateState {
            copy(
                session = session,
                pendingDeepLink = if (session == SessionState.SignedIn) null else pendingDeepLink,
                isSessionExpiredDialogVisible = session == SessionState.Expired,
            )
        }
        when (session) {
            SessionState.SignedIn -> {
                sendEffect(AppShellEffect.ShowMain)
                pending?.let { sendEffect(AppShellEffect.Open(it)) }
            }
            SessionState.SignedOut, SessionState.Expired -> sendEffect(AppShellEffect.ShowSignIn)
            SessionState.Unknown -> Unit
        }
    }
}
```

The ViewModel is retained across configuration changes and the effects travel through a Channel, so
a rotation does not replay `ShowMain`.

## 4. Root host

```kotlin
@Composable
fun AppRoot(shellViewModel: AppShellViewModel = koinViewModel()) {
    val navController = rememberNavController()
    val shell by shellViewModel.state.collectAsStateWithLifecycle()

    NavHost(navController = navController, startDestination = SplashRoute) {
        composable<SplashRoute> { SplashScreen() }
        navigation<AuthGraph>(startDestination = SignInRoute) {
            // Sign-in success changes the session; the shell reacts. No navigate() here.
            composable<SignInRoute> { SignInScreen() }
        }
        composable<MainRoute> { MainTabsScreen(rootNavController = navController) }
        composable<NoteDetailRoute> { NoteDetailScreen(onBack = navController::popBackStack) }
        composable<NoteEditorRoute> { /* see compose-multiplatform-screen worked example */ }
    }

    if (shell.isSessionExpiredDialogVisible) {
        SessionExpiredDialog(onDismiss = { shellViewModel.onAction(AppShellAction.SessionExpiredDialogDismissed) })
    }

    // Deep links arriving from Android/iOS entry points (see deep-links.md).
    DeepLinkListener { uri ->
        parseDeepLink(uri)?.let { shellViewModel.onAction(AppShellAction.DeepLinkReceived(it)) }
    }

    // The only app-level navigation.
    CollectEffects(shellViewModel.effects) { effect ->
        when (effect) {
            // Guard: after process death the NavController restores a deep stack and a fresh
            // ViewModel emits ShowMain again; only leave splash/auth, never reset a live stack.
            AppShellEffect.ShowMain ->
                if (navController.isOnSplashOrAuth()) navController.navigateClearingBackStack(MainRoute)
            AppShellEffect.ShowSignIn ->
                if (!navController.isInGraph(AuthGraph::class)) navController.navigateClearingBackStack(AuthGraph)
            is AppShellEffect.Open -> when (val target = effect.target) {
                is DeepLinkTarget.Note -> navController.navigate(NoteDetailRoute(noteId = target.noteId))
            }
        }
    }
}

fun NavController.navigateClearingBackStack(route: Any) = navigate(route) {
    popUpTo(graph.id) { inclusive = true }
    launchSingleTop = true
}

private fun NavController.isInGraph(graph: KClass<*>): Boolean =
    currentDestination?.hierarchy?.any { it.hasRoute(graph) } == true

private fun NavController.isOnSplashOrAuth(): Boolean =
    currentDestination == null ||
        currentDestination?.hasRoute(SplashRoute::class) == true ||
        isInGraph(AuthGraph::class)
```

Notes:

- `NavHost` sets the graph during composition, before `CollectEffects`'s `LaunchedEffect` runs, so
  the first effect can navigate safely.
- `SessionExpiredDialog` is state-driven; it is shown above whatever destination is current and
  survives rotation.
- Destinations reachable by deep link (`NoteDetailRoute`) live on the **root** host so the shell can
  open them regardless of the selected tab.

## 5. Tab host

```kotlin
enum class MainTab(
    val graph: Any,
    val rootRoute: Any,
    val label: StringResource,
    val icon: DrawableResource,
    val testTag: String,
) {
    Notes(NotesTab, NotesListRoute, Res.string.tab_notes, Res.drawable.ic_tab_notes, "main_tab_notes"),
    Profile(ProfileTab, ProfileRoute, Res.string.tab_profile, Res.drawable.ic_tab_profile, "main_tab_profile"),
}

@Composable
fun MainTabsScreen(rootNavController: NavController) {
    val tabNavController = rememberNavController()
    val currentEntry by tabNavController.currentBackStackEntryAsState()
    val currentDestination = currentEntry?.destination
    val isOnTabRoot = MainTab.entries.any { tab -> currentDestination?.hasRoute(tab.rootRoute::class) == true }

    Scaffold(
        bottomBar = {
            if (isOnTabRoot) {
                NavigationBar(modifier = Modifier.testTag("main_tabs_bottom_bar")) {
                    MainTab.entries.forEach { tab ->
                        val selected = currentDestination?.hierarchy?.any { it.hasRoute(tab.graph::class) } == true
                        NavigationBarItem(
                            selected = selected,
                            onClick = {
                                if (selected) tabNavController.popBackStack(tab.rootRoute, inclusive = false)
                                else tabNavController.switchTab(tab.graph)
                            },
                            icon = { Icon(painterResource(tab.icon), contentDescription = null) },
                            label = { Text(stringResource(tab.label)) },
                            modifier = Modifier.testTag(tab.testTag),
                        )
                    }
                }
            }
        },
    ) { innerPadding ->
        NavHost(
            navController = tabNavController,
            startDestination = NotesTab,
            modifier = Modifier.padding(innerPadding),
        ) {
            navigation<NotesTab>(startDestination = NotesListRoute) {
                composable<NotesListRoute> {
                    NotesListScreen(
                        onOpenNote = { id -> rootNavController.navigate(NoteDetailRoute(noteId = id)) },
                        onCreateNote = { rootNavController.navigate(NoteEditorRoute()) },
                    )
                }
            }
            navigation<ProfileTab>(startDestination = ProfileRoute) {
                composable<ProfileRoute> { ProfileScreen(onOpenSettings = { tabNavController.navigate(SettingsRoute) }) }
                composable<SettingsRoute> { SettingsScreen(onBack = tabNavController::popBackStack) }
            }
        }
    }
}

fun NavController.switchTab(tabGraph: Any) = navigate(tabGraph) {
    // Inside the tab host the start destination resolves to the first tab's root,
    // which is always on the stack: back from another tab returns there, then exits.
    popUpTo(graph.findStartDestination().id) { saveState = true }
    launchSingleTop = true
    restoreState = true
}
```

Why a nested host: `findStartDestination()` resolves the graph's start destination recursively. On
the root host that is `SplashRoute`, which was popped after sign-in, so the recipe would pop nothing
and stacks would pile up. Inside the tab host it resolves to `NotesListRoute`.

Icons come from `composeResources/drawable` (`painterResource`), which avoids depending on the
Material icons artifacts, whose availability differs between Compose Multiplatform versions.

The tab label is visible text, so the icon's `contentDescription` is `null` to avoid a duplicate
announcement.

## 6. Android splash hold

```kotlin
class MainActivity : ComponentActivity() {
    private val shellViewModel: AppShellViewModel by viewModel()   // org.koin.androidx.viewmodel.ext.android.viewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        installSplashScreen().setKeepOnScreenCondition {
            shellViewModel.state.value.session == SessionState.Unknown
        }
        super.onCreate(savedInstanceState)
        setContent { AppRoot() }   // koinViewModel() resolves the same Activity-scoped instance
    }
}
```

`installSplashScreen()` comes from `androidx.core:core-splashscreen`. On iOS, keep `SplashScreen()`
visually identical to the launch screen so the hand-off is invisible.

## 7. Shell ViewModel tests

```kotlin
class FakeSessionRepository : SessionRepository {
    val sessionFlow = MutableStateFlow(SessionState.Unknown)
    override val session: Flow<SessionState> = sessionFlow
}

@OptIn(ExperimentalCoroutinesApi::class)
class AppShellViewModelTest {
    private val sessionRepository = FakeSessionRepository()

    @BeforeTest fun setUp() = Dispatchers.setMain(StandardTestDispatcher())
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test
    fun should_openPendingDeepLink_when_userSignsInAfterLinkArrived() = runTest {
        val viewModel = AppShellViewModel(sessionRepository)
        val effects = mutableListOf<AppShellEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }

        sessionRepository.sessionFlow.value = SessionState.SignedOut
        advanceUntilIdle()
        viewModel.onAction(AppShellAction.DeepLinkReceived(DeepLinkTarget.Note(noteId = "42")))
        sessionRepository.sessionFlow.value = SessionState.SignedIn
        advanceUntilIdle()

        assertEquals(
            listOf(AppShellEffect.ShowSignIn, AppShellEffect.ShowMain, AppShellEffect.Open(DeepLinkTarget.Note("42"))),
            effects,
        )
        assertNull(viewModel.state.value.pendingDeepLink)
    }

    @Test
    fun should_showExpiredDialog_and_signIn_when_sessionExpires() = runTest {
        val viewModel = AppShellViewModel(sessionRepository)
        val effects = mutableListOf<AppShellEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }

        sessionRepository.sessionFlow.value = SessionState.SignedIn
        advanceUntilIdle()
        sessionRepository.sessionFlow.value = SessionState.Expired
        advanceUntilIdle()

        assertTrue(viewModel.state.value.isSessionExpiredDialogVisible)
        assertEquals(AppShellEffect.ShowSignIn, effects.last())
    }

    @Test
    fun should_emitNothing_when_sessionStillUnknown() = runTest {
        val viewModel = AppShellViewModel(sessionRepository)
        val effects = mutableListOf<AppShellEffect>()
        backgroundScope.launch(UnconfinedTestDispatcher(testScheduler)) { viewModel.effects.toList(effects) }

        advanceUntilIdle()

        assertTrue(effects.isEmpty())
        assertEquals(SessionState.Unknown, viewModel.state.value.session)
    }
}
```

A `MutableStateFlow` conflates: set one value and `advanceUntilIdle()` before setting the next, or
the ViewModel only sees the last one.
