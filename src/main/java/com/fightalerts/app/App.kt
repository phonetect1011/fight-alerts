package com.fightalerts.app

import android.Manifest
import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.expandVertically
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.shrinkVertically
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.NetworkType
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import coil.compose.AsyncImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.concurrent.TimeUnit

// ================================================================ data

val PROMOTIONS = listOf("UFC", "BKFC", "ONE", "RAF")

data class Fighter(
    val name: String,
    val country: String = "",
    val flag: String = "",
    val record: String = "",
    val rank: String = "",
    val nickname: String = "",
    val photo: String = "",
    val url: String = "",
    val stats: List<Pair<String, String>> = emptyList(),
)

data class Bout(val a: Fighter, val b: Fighter, val section: String, val weight: String, val title: Boolean)

data class FightEvent(
    val id: String,
    val promotion: String,
    val title: String,
    val url: String,
    val start: Long,
    val prelims: Long?,
    val earlyPrelims: Long?,
    val bouts: List<Bout>,
)

data class FightData(
    val generated: Long,
    val events: List<FightEvent>,
    val broken: Map<String, String>,
    val healthy: List<String>,
)

fun parseFighter(o: JSONObject?, fallbackName: String): Fighter {
    if (o == null) return Fighter(fallbackName)
    val stats = mutableListOf<Pair<String, String>>()
    val s = o.optJSONObject("stats")
    if (s != null) for (k in s.keys()) stats += k to s.optString(k)
    return Fighter(
        name = o.optString("name").ifBlank { fallbackName },
        country = o.optString("country"),
        flag = o.optString("flag"),
        record = o.optString("record"),
        rank = o.optString("rank"),
        nickname = o.optString("nickname"),
        photo = o.optString("photo"),
        url = o.optString("url"),
        stats = stats,
    )
}

fun parseData(json: String): FightData {
    val root = JSONObject(json)
    val events = mutableListOf<FightEvent>()
    val arr = root.getJSONArray("events")
    for (i in 0 until arr.length()) {
        val e = arr.getJSONObject(i)
        val bouts = mutableListOf<Bout>()
        val boutsArr = e.optJSONArray("bouts")
        if (boutsArr != null) {
            for (j in 0 until boutsArr.length()) {
                val b = boutsArr.getJSONObject(j)
                bouts += Bout(
                    a = parseFighter(b.optJSONObject("fa"), b.optString("a")),
                    b = parseFighter(b.optJSONObject("fb"), b.optString("b")),
                    section = b.optString("section"),
                    weight = b.optString("weight"),
                    title = b.optBoolean("title"),
                )
            }
        }
        events += FightEvent(
            id = e.getString("id"),
            promotion = e.getString("promotion"),
            title = e.getString("title"),
            url = e.optString("url"),
            start = e.getLong("startMs"),
            prelims = if (e.isNull("prelimsMs")) null else e.getLong("prelimsMs"),
            earlyPrelims = if (e.isNull("earlyPrelimsMs")) null else e.getLong("earlyPrelimsMs"),
            bouts = bouts,
        )
    }
    val broken = mutableMapOf<String, String>()
    val healthy = mutableListOf<String>()
    val health = root.optJSONObject("health")
    if (health != null) {
        for (key in health.keys()) {
            val h = health.getJSONObject(key)
            if (h.optBoolean("ok", true)) healthy += key else broken[key] = h.optString("message")
        }
    }
    return FightData(root.optLong("generatedMs"), events, broken, healthy)
}

object Repo {
    private fun cacheFile(ctx: Context) = File(ctx.filesDir, "events.json")

    fun loadCached(ctx: Context): FightData? = try {
        val f = cacheFile(ctx)
        if (f.exists()) parseData(f.readText()) else null
    } catch (e: Exception) {
        null
    }

    fun fetch(ctx: Context): FightData {
        val url = URL(BuildConfig.DATA_URL + "?t=" + System.currentTimeMillis())
        val conn = url.openConnection() as HttpURLConnection
        conn.connectTimeout = 15_000
        conn.readTimeout = 20_000
        try {
            if (conn.responseCode != 200) throw Exception("HTTP ${conn.responseCode}")
            val text = conn.inputStream.bufferedReader().use { it.readText() }
            val data = parseData(text)
            cacheFile(ctx).writeText(text)
            return data
        } finally {
            conn.disconnect()
        }
    }
}

class Prefs(ctx: Context) {
    private val sp = ctx.getSharedPreferences("settings", Context.MODE_PRIVATE)

    var promotions: Set<String>
        get() = sp.getStringSet("promotions", null)?.toSet() ?: PROMOTIONS.toSet()
        set(v) = sp.edit().putStringSet("promotions", v).apply()

    var followed: Set<String>
        get() = sp.getStringSet("followed", null)?.toSet() ?: emptySet()
        set(v) = sp.edit().putStringSet("followed", v).apply()

    var scheduled: Set<String>
        get() = sp.getStringSet("scheduled", null)?.toSet() ?: emptySet()
        set(v) = sp.edit().putStringSet("scheduled", v).apply()

    var leadMinutes: Int
        get() = sp.getInt("lead", 15)
        set(v) = sp.edit().putInt("lead", v).apply()

    var prelimAlerts: Boolean
        get() = sp.getBoolean("prelims", false)
        set(v) = sp.edit().putBoolean("prelims", v).apply()

    var onlyFollowed: Boolean
        get() = sp.getBoolean("onlyFollowed", false)
        set(v) = sp.edit().putBoolean("onlyFollowed", v).apply()

    /** "system", "day" or "night" */
    var theme: String
        get() = sp.getString("theme", "system") ?: "system"
        set(v) = sp.edit().putString("theme", v).apply()
}

fun mainBout(e: FightEvent): Bout? =
    e.bouts.firstOrNull { it.section.equals("Main Event", ignoreCase = true) } ?: e.bouts.firstOrNull()

// ================================================================ alarms & notifications

object Alarms {
    fun canExact(ctx: Context): Boolean {
        if (Build.VERSION.SDK_INT < 31) return true
        return ctx.getSystemService(AlarmManager::class.java).canScheduleExactAlarms()
    }

    fun scheduleAll(ctx: Context, data: FightData) {
        val prefs = Prefs(ctx)
        val am = ctx.getSystemService(AlarmManager::class.java)

        // cancel everything we set last time
        for (code in prefs.scheduled) {
            val old = PendingIntent.getBroadcast(
                ctx, code.toInt(), Intent(ctx, AlarmReceiver::class.java),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_NO_CREATE,
            )
            if (old != null) {
                am.cancel(old)
                old.cancel()
            }
        }

        val now = System.currentTimeMillis()
        val leadMin = prefs.leadMinutes
        val lead = leadMin * 60_000L
        val followed = prefs.followed
        val enabled = prefs.promotions
        val exact = canExact(ctx)
        val newCodes = mutableSetOf<String>()

        for (e in data.events) {
            if (e.promotion !in enabled) continue
            val followedHere = e.bouts.flatMap { listOf(it.a.name, it.b.name) }.filter { it in followed }.distinct()
            if (prefs.onlyFollowed && followedHere.isEmpty()) continue

            val slots = mutableListOf("Main card" to e.start)
            if (prefs.prelimAlerts) {
                e.prelims?.let { slots += "Prelims" to it }
                e.earlyPrelims?.let { slots += "Early prelims" to it }
            }

            for ((label, startTime) in slots) {
                val at = startTime - lead
                if (at <= now) continue
                val code = (e.id + label).hashCode()
                val title = if (leadMin == 0) "${e.promotion}: $label starting now"
                else "${e.promotion}: $label starts in $leadMin min"
                val body = buildString {
                    append(e.title)
                    mainBout(e)?.let { append("\n${it.a.name} vs ${it.b.name}") }
                    if (followedHere.isNotEmpty()) append("\n★ You follow: ${followedHere.joinToString()}")
                }
                val intent = Intent(ctx, AlarmReceiver::class.java)
                    .putExtra("id", code)
                    .putExtra("title", title)
                    .putExtra("body", body)
                val pi = PendingIntent.getBroadcast(
                    ctx, code, intent,
                    PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
                )
                if (exact) am.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
                else am.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pi)
                newCodes += code.toString()
            }
        }
        prefs.scheduled = newCodes
    }
}

object Notify {
    private const val CHANNEL = "fights"

    fun ensureChannel(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, "Fight alerts", NotificationManager.IMPORTANCE_HIGH)
        )
    }

    fun hasPermission(ctx: Context): Boolean =
        Build.VERSION.SDK_INT < 33 ||
            ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) ==
            PackageManager.PERMISSION_GRANTED

    fun show(ctx: Context, id: Int, title: String, body: String) {
        ensureChannel(ctx)
        if (!hasPermission(ctx)) return
        val open = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE,
        )
        val n = NotificationCompat.Builder(ctx, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_lock_idle_alarm)
            .setContentTitle(title)
            .setContentText(body.lineSequence().firstOrNull() ?: "")
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        try {
            NotificationManagerCompat.from(ctx).notify(id, n)
        } catch (e: SecurityException) {
            // permission was revoked
        }
    }
}

class AlarmReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        Notify.show(
            ctx,
            intent.getIntExtra("id", 0),
            intent.getStringExtra("title") ?: "Fight starting",
            intent.getStringExtra("body") ?: "",
        )
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED) {
            Repo.loadCached(ctx)?.let { Alarms.scheduleAll(ctx, it) }
            RefreshWorker.enqueue(ctx)
        }
    }
}

class RefreshWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            val data = Repo.fetch(applicationContext)
            Alarms.scheduleAll(applicationContext, data)
            Result.success()
        } catch (e: Exception) {
            Result.retry()
        }
    }

    companion object {
        fun enqueue(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<RefreshWorker>(6, TimeUnit.HOURS)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx)
                .enqueueUniquePeriodicWork("refresh", ExistingPeriodicWorkPolicy.KEEP, req)
        }
    }
}

// ================================================================ theme

private val RED = Color(0xFFE53935)

data class Palette(
    val isDark: Boolean,
    val bg: Color,
    val card: Color,
    val cardBorder: Color,
    val sheet: Color,
    val text: Color,
    val text2: Color,
    val text3: Color,
    val divider: Color,
    val gold: Color,
    val green: Color,
)

/** Night: true black for AMOLED screens. */
val NightPalette = Palette(
    isDark = true,
    bg = Color(0xFF000000),
    card = Color(0xFF0C0C0C),
    cardBorder = Color(0xFF1C1C1C),
    sheet = Color(0xFF0C0C0C),
    text = Color(0xFFFFFFFF),
    text2 = Color(0xFFB8B8B8),
    text3 = Color(0xFF7A7A7A),
    divider = Color(0xFF1F1F1F),
    gold = Color(0xFFFFB300),
    green = Color(0xFF4CAF50),
)

/** Day: clean white. */
val DayPalette = Palette(
    isDark = false,
    bg = Color(0xFFFFFFFF),
    card = Color(0xFFF5F5F7),
    cardBorder = Color(0xFFE6E6EA),
    sheet = Color(0xFFFFFFFF),
    text = Color(0xFF111111),
    text2 = Color(0xFF4A4A50),
    text3 = Color(0xFF8A8A90),
    divider = Color(0xFFE5E5EA),
    gold = Color(0xFFB7791F),
    green = Color(0xFF2E7D32),
)

val LocalPalette = staticCompositionLocalOf { NightPalette }

// ================================================================ formatting helpers

private val TIME_FMT = DateTimeFormatter.ofPattern("EEE d MMM · h:mm a")

fun fmt(ms: Long): String = TIME_FMT.format(Instant.ofEpochMilli(ms).atZone(ZoneId.systemDefault()))

fun ago(ms: Long): String {
    val m = ms / 60_000
    return when {
        m < 1 -> "just now"
        m < 60 -> "${m}m ago"
        m < 1440 -> "${m / 60}h ago"
        else -> "${m / 1440}d ago"
    }
}

fun countdown(e: FightEvent, now: Long): String {
    if (now >= e.start) return "LIVE NOW"
    val firstStart = e.earlyPrelims ?: e.prelims
    if (firstStart != null && now >= firstStart) return "PRELIMS LIVE"
    val mins = (e.start - now) / 60_000
    val d = mins / 1440
    val h = (mins % 1440) / 60
    val m = mins % 60
    return when {
        d > 0 -> "IN ${d}D ${h}H"
        h > 0 -> "IN ${h}H ${m}M"
        else -> "IN ${m}M"
    }
}

fun isLive(e: FightEvent, now: Long): Boolean = now >= (e.earlyPrelims ?: e.prelims ?: e.start)

fun promoColor(p: String): Color = when (p) {
    "UFC" -> Color(0xFFD20A0A)
    "BKFC" -> Color(0xFF8E24AA)
    "ONE" -> Color(0xFFF9A825)
    "RAF" -> Color(0xFF1E88E5)
    else -> Color.Gray
}

fun withFlag(f: Fighter): String = if (f.flag.isNotBlank()) "${f.flag} ${f.name}" else f.name

fun openUrl(ctx: Context, url: String) {
    try {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
    } catch (e: Exception) {
        // no browser
    }
}

// ================================================================ activity + root

class MainActivity : ComponentActivity() {
    private val resumeTick = mutableIntStateOf(0)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        Notify.ensureChannel(this)
        RefreshWorker.enqueue(this)
        setContent { FightApp(this, resumeTick.intValue) }
    }

    override fun onResume() {
        super.onResume()
        resumeTick.intValue++
        // re-arm alarms in case the exact-alarm permission was just granted
        Repo.loadCached(this)?.let { Alarms.scheduleAll(this, it) }
    }
}

enum class Screen { Main, Settings }

@Composable
fun FightApp(activity: ComponentActivity, resumeTick: Int) {
    val prefs = remember { Prefs(activity) }
    var themeMode by remember { mutableStateOf(prefs.theme) }
    val dark = when (themeMode) {
        "day" -> false
        "night" -> true
        else -> isSystemInDarkTheme()
    }
    val p = if (dark) NightPalette else DayPalette

    DisposableEffect(dark) {
        val clear = android.graphics.Color.TRANSPARENT
        val style = if (dark) SystemBarStyle.dark(clear) else SystemBarStyle.light(clear, clear)
        activity.enableEdgeToEdge(statusBarStyle = style, navigationBarStyle = style)
        onDispose { }
    }

    val scheme = if (dark) {
        darkColorScheme(
            primary = RED, onPrimary = Color.White, secondary = p.gold,
            background = p.bg, onBackground = p.text, surface = p.bg, onSurface = p.text,
            surfaceVariant = p.card, onSurfaceVariant = p.text2, outline = p.cardBorder,
            surfaceContainerLow = p.sheet, surfaceContainerHigh = p.card,
        )
    } else {
        lightColorScheme(
            primary = RED, onPrimary = Color.White, secondary = p.gold,
            background = p.bg, onBackground = p.text, surface = p.bg, onSurface = p.text,
            surfaceVariant = p.card, onSurfaceVariant = p.text2, outline = p.cardBorder,
            surfaceContainerLow = p.sheet, surfaceContainerHigh = p.card,
        )
    }

    CompositionLocalProvider(LocalPalette provides p) {
        MaterialTheme(colorScheme = scheme) {
            Surface(Modifier.fillMaxSize(), color = p.bg) {
                AppScreen(prefs, themeMode, { themeMode = it; prefs.theme = it }, resumeTick)
            }
        }
    }
}

@Composable
fun AppScreen(prefs: Prefs, themeMode: String, onTheme: (String) -> Unit, resumeTick: Int) {
    val ctx = LocalContext.current
    val c = LocalPalette.current
    val scope = rememberCoroutineScope()

    var data by remember { mutableStateOf(Repo.loadCached(ctx)) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var promotions by remember { mutableStateOf(prefs.promotions) }
    var followed by remember { mutableStateOf(prefs.followed) }
    var screen by remember { mutableStateOf(Screen.Main) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }

    val notifLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { }

    fun reschedule() {
        data?.let { Alarms.scheduleAll(ctx, it) }
    }

    fun refresh() {
        loading = true
        error = null
        scope.launch {
            try {
                val d = withContext(Dispatchers.IO) { Repo.fetch(ctx) }
                data = d
                Alarms.scheduleAll(ctx, d)
            } catch (e: Exception) {
                error = "Couldn't download fight data: ${e.message}"
            }
            loading = false
            now = System.currentTimeMillis()
        }
    }

    LaunchedEffect(Unit) {
        if (!Notify.hasPermission(ctx) && Build.VERSION.SDK_INT >= 33) {
            notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        refresh()
    }
    LaunchedEffect(Unit) {
        while (true) {
            delay(30_000)
            now = System.currentTimeMillis()
        }
    }

    BackHandler(enabled = screen == Screen.Settings) { screen = Screen.Main }

    if (screen == Screen.Settings) {
        SettingsScreen(
            prefs = prefs,
            themeMode = themeMode,
            onTheme = onTheme,
            data = data,
            now = now,
            resumeTick = resumeTick,
            onBack = { screen = Screen.Main },
            onChanged = { reschedule() },
        )
        return
    }

    Column(Modifier.fillMaxSize().systemBarsPadding()) {
        // ---- header
        Row(
            Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 14.dp, bottom = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("Fight Alerts", fontSize = 28.sp, fontWeight = FontWeight.Black, color = c.text)
                Text(
                    data?.let { "Updated ${ago(now - it.generated)}" } ?: "Getting fights…",
                    fontSize = 12.sp, color = c.text3,
                )
            }
            if (loading) {
                CircularProgressIndicator(
                    modifier = Modifier.padding(12.dp).size(22.dp), color = RED, strokeWidth = 2.5.dp,
                )
            } else {
                IconButton(onClick = { refresh() }) {
                    Icon(Icons.Filled.Refresh, contentDescription = "Refresh", tint = c.text2)
                }
            }
            IconButton(onClick = { screen = Screen.Settings }) {
                Icon(Icons.Filled.Settings, contentDescription = "Settings", tint = c.text2)
            }
        }

        // ---- warnings: broken scraper / stale data / download errors
        val d = data
        val warnings = buildList {
            error?.let { add(it) }
            d?.broken?.forEach { (promo, msg) ->
                add("$promo data is broken ($msg). Showing last known fights — check the GitHub issue.")
            }
            if (d != null && now - d.generated > 24 * 3_600_000L) {
                add("Fight data hasn't updated in ${ago(now - d.generated)} — check the scraper on GitHub Actions.")
            }
        }
        warnings.forEach { w ->
            Text(
                "⚠  $w", color = c.text, fontSize = 13.sp,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)
                    .clip(RoundedCornerShape(12.dp))
                    .background(c.gold.copy(alpha = 0.16f))
                    .padding(12.dp),
            )
        }

        // ---- promotion toggles (controls what's shown and what you get alerts for)
        Row(
            Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            PROMOTIONS.forEach { promo ->
                PromoChip(promo, selected = promo in promotions) {
                    promotions = if (promo in promotions) promotions - promo else promotions + promo
                    prefs.promotions = promotions
                    reschedule()
                }
            }
        }

        val events = d?.events.orEmpty()
            .filter { it.promotion in promotions && it.start > now - 6 * 3_600_000L }
            .sortedBy { it.start }

        if (events.isEmpty()) {
            Column(
                Modifier.fillMaxWidth().padding(40.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("🥊", fontSize = 44.sp)
                Spacer(Modifier.height(8.dp))
                Text(
                    if (d == null) "Loading fights…" else "No upcoming fights for the promotions you picked.",
                    color = c.text3, textAlign = TextAlign.Center,
                )
            }
        }

        LazyColumn(
            Modifier.fillMaxSize(),
            contentPadding = PaddingValues(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 24.dp),
        ) {
            items(events, key = { it.id }) { e ->
                EventCard(e, now, followed) { name ->
                    followed = if (name in followed) followed - name else followed + name
                    prefs.followed = followed
                    reschedule()
                }
            }
        }
    }
}

// ================================================================ main screen pieces

@Composable
fun PromoChip(promo: String, selected: Boolean, onClick: () -> Unit) {
    val c = LocalPalette.current
    val color = promoColor(promo)
    Row(
        Modifier.clip(RoundedCornerShape(50))
            .background(if (selected) color.copy(alpha = if (c.isDark) 0.22f else 0.14f) else Color.Transparent)
            .border(1.dp, if (selected) color else c.cardBorder, RoundedCornerShape(50))
            .clickable { onClick() }
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(8.dp).clip(CircleShape).background(if (selected) color else c.text3))
        Spacer(Modifier.width(8.dp))
        Text(
            promo, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
            color = if (selected) c.text else c.text3,
        )
    }
}

@Composable
fun Pill(text: String, color: Color, filled: Boolean = false) {
    Text(
        text, fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 0.5.sp,
        color = if (filled) Color.White else color,
        modifier = Modifier.clip(RoundedCornerShape(6.dp))
            .background(if (filled) color else color.copy(alpha = 0.15f))
            .padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

@Composable
fun EventCard(e: FightEvent, now: Long, followed: Set<String>, onFollow: (String) -> Unit) {
    val c = LocalPalette.current
    val ctx = LocalContext.current
    var expanded by remember { mutableStateOf(false) }
    var selected by remember { mutableStateOf<Pair<Bout, Boolean>?>(null) }
    val hasFollowed = e.bouts.any { it.a.name in followed || it.b.name in followed }
    val live = isLive(e, now)

    Card(
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp),
        shape = RoundedCornerShape(20.dp),
        colors = CardDefaults.cardColors(containerColor = c.card),
        border = BorderStroke(1.dp, if (live) RED.copy(alpha = 0.6f) else c.cardBorder),
    ) {
        Column(Modifier.clickable { expanded = !expanded }.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Pill(e.promotion, promoColor(e.promotion), filled = true)
                Spacer(Modifier.width(8.dp))
                Pill(countdown(e, now), if (live) RED else c.gold, filled = live)
                Spacer(Modifier.weight(1f))
                if (hasFollowed) {
                    Icon(Icons.Filled.Star, contentDescription = "Has a fighter you follow", tint = c.gold, modifier = Modifier.size(20.dp))
                }
            }
            Spacer(Modifier.height(12.dp))
            Text(e.title, color = c.text, fontSize = 19.sp, fontWeight = FontWeight.Bold, lineHeight = 24.sp)
            Spacer(Modifier.height(4.dp))
            Text("Main card  ·  ${fmt(e.start)}", color = c.text2, fontSize = 13.sp)
            e.prelims?.let { Text("Prelims  ·  ${fmt(it)}", color = c.text3, fontSize = 12.sp) }
            e.earlyPrelims?.let { Text("Early prelims  ·  ${fmt(it)}", color = c.text3, fontSize = 12.sp) }

            val main = mainBout(e)
            if (main == null) {
                Spacer(Modifier.height(12.dp))
                Text("Card to be announced", color = c.text3, fontSize = 14.sp)
            } else if (!expanded) {
                Spacer(Modifier.height(14.dp))
                MatchupRow(main, followed, photoSize = 46.dp) { isA -> selected = main to isA }
            }

            AnimatedVisibility(
                visible = expanded,
                enter = expandVertically() + fadeIn(),
                exit = shrinkVertically() + fadeOut(),
            ) {
                Column {
                    var lastSection = ""
                    e.bouts.forEach { b ->
                        if (b.section.isNotBlank() && b.section != lastSection) {
                            lastSection = b.section
                            Text(
                                b.section.uppercase(), color = RED, fontSize = 11.sp,
                                fontWeight = FontWeight.Bold, letterSpacing = 1.sp,
                                modifier = Modifier.padding(top = 16.dp, bottom = 6.dp),
                            )
                        }
                        MatchupRow(b, followed, photoSize = 36.dp) { isA -> selected = b to isA }
                        val info = listOfNotNull(b.weight.ifBlank { null }, if (b.title) "🏆 Title fight" else null)
                            .joinToString("  ·  ")
                        if (info.isNotEmpty()) {
                            Text(
                                info, color = c.text3, fontSize = 11.sp, textAlign = TextAlign.Center,
                                modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp),
                            )
                        }
                        HorizontalDivider(color = c.divider, modifier = Modifier.padding(vertical = 4.dp))
                    }
                    if (e.url.isNotBlank()) {
                        TextButton(onClick = { openUrl(ctx, e.url) }) {
                            Text("Open full event page", color = RED)
                        }
                    }
                }
            }

            Spacer(Modifier.height(10.dp))
            Text(
                when {
                    expanded -> "Hide fights  ▲"
                    e.bouts.size > 1 -> "Show all ${e.bouts.size} fights  ▼"
                    else -> "Details  ▼"
                },
                color = RED, fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center,
            )
        }
    }

    selected?.let { (bout, isA) ->
        val f = if (isA) bout.a else bout.b
        val opp = if (isA) bout.b else bout.a
        FighterSheet(
            f = f, opponent = opp, bout = bout, event = e,
            isFollowed = f.name in followed,
            onFollow = { onFollow(f.name) },
            onDismiss = { selected = null },
        )
    }
}

@Composable
fun MatchupRow(b: Bout, followed: Set<String>, photoSize: Dp, onTap: (Boolean) -> Unit) {
    val c = LocalPalette.current
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Row(
            Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).clickable { onTap(true) }.padding(4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            FighterPhoto(b.a, photoSize)
            Spacer(Modifier.width(8.dp))
            FighterLabel(b.a, b.a.name in followed, alignEnd = false)
        }
        Text(
            "VS", color = c.text3, fontSize = 11.sp, fontWeight = FontWeight.Black,
            modifier = Modifier.padding(horizontal = 4.dp),
        )
        Row(
            Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).clickable { onTap(false) }.padding(4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.End,
        ) {
            FighterLabel(b.b, b.b.name in followed, alignEnd = true, modifier = Modifier.weight(1f, fill = false))
            Spacer(Modifier.width(8.dp))
            FighterPhoto(b.b, photoSize)
        }
    }
}

@Composable
fun FighterLabel(f: Fighter, isFollowed: Boolean, alignEnd: Boolean, modifier: Modifier = Modifier) {
    val c = LocalPalette.current
    Column(modifier, horizontalAlignment = if (alignEnd) Alignment.End else Alignment.Start) {
        Text(
            text = (if (isFollowed) "★ " else "") + withFlag(f),
            color = if (isFollowed) c.gold else c.text,
            fontWeight = FontWeight.SemiBold,
            fontSize = 14.sp,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
            textAlign = if (alignEnd) TextAlign.End else TextAlign.Start,
        )
        val sub = listOfNotNull(
            f.rank.ifBlank { null }?.let { if (it == "C") "Champ" else it },
            f.record.ifBlank { null },
        ).joinToString(" · ")
        if (sub.isNotBlank()) Text(sub, color = c.text3, fontSize = 11.sp)
    }
}

@Composable
fun FighterPhoto(f: Fighter, size: Dp) {
    val c = LocalPalette.current
    Box(
        modifier = Modifier.size(size).clip(CircleShape).background(c.cardBorder),
        contentAlignment = Alignment.Center,
    ) {
        val initials = f.name.split(" ").filter { it.isNotBlank() }.take(2)
            .joinToString("") { it.take(1).uppercase() }
        Text(initials, color = c.text3, fontSize = (size.value * 0.32f).sp, fontWeight = FontWeight.Bold)
        if (f.photo.isNotBlank()) {
            AsyncImage(
                model = f.photo,
                contentDescription = f.name,
                contentScale = ContentScale.Crop,
                alignment = Alignment.TopCenter,
                modifier = Modifier.size(size).clip(CircleShape),
            )
        }
    }
}

// ================================================================ fighter profile sheet

@Composable
fun RecordBoxes(record: String) {
    val c = LocalPalette.current
    val parts = record.split("-").map { it.trim() }
    if (parts.size < 2) {
        Text(record, color = c.text, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        return
    }
    val labels = listOf("WINS" to c.green, "LOSSES" to RED, "DRAWS" to c.text3)
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        parts.take(3).forEachIndexed { i, n ->
            val (label, color) = labels[i]
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.weight(1f).clip(RoundedCornerShape(14.dp))
                    .background(c.card).border(1.dp, c.cardBorder, RoundedCornerShape(14.dp))
                    .padding(vertical = 12.dp),
            ) {
                Text(n, color = color, fontSize = 26.sp, fontWeight = FontWeight.Black)
                Text(label, color = c.text3, fontSize = 10.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun FighterSheet(
    f: Fighter,
    opponent: Fighter,
    bout: Bout,
    event: FightEvent,
    isFollowed: Boolean,
    onFollow: () -> Unit,
    onDismiss: () -> Unit,
) {
    val c = LocalPalette.current
    val ctx = LocalContext.current
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = c.sheet,
        contentColor = c.text,
    ) {
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                .padding(start = 24.dp, end = 24.dp, bottom = 32.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            FighterPhoto(f, 120.dp)
            Spacer(Modifier.height(14.dp))
            Text(
                withFlag(f), color = c.text, fontSize = 26.sp, fontWeight = FontWeight.Black,
                textAlign = TextAlign.Center,
            )
            if (f.nickname.isNotBlank()) {
                Text("“${f.nickname}”", color = c.text2, fontStyle = FontStyle.Italic, fontSize = 15.sp)
            }
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Pill(event.promotion, promoColor(event.promotion), filled = true)
                if (f.rank.isNotBlank()) Pill(if (f.rank == "C") "🏆 CHAMPION" else "RANKED ${f.rank}", c.gold)
                if (f.country.isNotBlank()) Pill(f.country.uppercase(), c.text2)
            }

            if (f.record.isNotBlank()) {
                Spacer(Modifier.height(18.dp))
                RecordBoxes(f.record)
            }

            if (f.stats.isNotEmpty()) {
                Spacer(Modifier.height(14.dp))
                Column(
                    Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp))
                        .background(c.card).border(1.dp, c.cardBorder, RoundedCornerShape(14.dp))
                        .padding(horizontal = 16.dp, vertical = 6.dp),
                ) {
                    f.stats.forEachIndexed { i, (label, value) ->
                        if (i > 0) HorizontalDivider(color = c.divider)
                        Row(Modifier.fillMaxWidth().padding(vertical = 10.dp)) {
                            Text(label, color = c.text3, fontSize = 14.sp, modifier = Modifier.weight(1f))
                            Text(value, color = c.text, fontSize = 14.sp, fontWeight = FontWeight.Medium)
                        }
                    }
                }
            }

            Spacer(Modifier.height(14.dp))
            Column(
                Modifier.fillMaxWidth().clip(RoundedCornerShape(14.dp))
                    .background(c.card).border(1.dp, c.cardBorder, RoundedCornerShape(14.dp))
                    .padding(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text("NEXT FIGHT", color = RED, fontSize = 11.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    FighterPhoto(opponent, 40.dp)
                    Spacer(Modifier.width(10.dp))
                    Column {
                        Text("vs ${withFlag(opponent)}", color = c.text, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        if (opponent.record.isNotBlank()) Text(opponent.record, color = c.text3, fontSize = 12.sp)
                    }
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    listOfNotNull(
                        bout.weight.ifBlank { null },
                        if (bout.title) "Title fight" else null,
                        bout.section.ifBlank { null },
                    ).joinToString("  ·  "),
                    color = c.text3, fontSize = 12.sp, textAlign = TextAlign.Center,
                )
                Text(event.title, color = c.text2, fontSize = 13.sp, textAlign = TextAlign.Center)
                Text(fmt(event.start), color = c.text3, fontSize = 12.sp)
            }

            Spacer(Modifier.height(18.dp))
            Button(
                onClick = onFollow,
                modifier = Modifier.fillMaxWidth().height(52.dp),
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (isFollowed) c.card else RED,
                    contentColor = if (isFollowed) c.gold else Color.White,
                ),
                border = if (isFollowed) BorderStroke(1.dp, c.gold) else null,
            ) {
                Text(
                    if (isFollowed) "★  Following" else "☆  Follow ${f.name.substringBefore(" ")}",
                    fontSize = 16.sp, fontWeight = FontWeight.Bold,
                )
            }
            if (f.url.isNotBlank()) {
                TextButton(onClick = { openUrl(ctx, f.url) }) {
                    Text("Full profile on next-fight.com", color = c.text2)
                }
            }
        }
    }
}

// ================================================================ settings screen

@Composable
fun SettingsScreen(
    prefs: Prefs,
    themeMode: String,
    onTheme: (String) -> Unit,
    data: FightData?,
    now: Long,
    resumeTick: Int,
    onBack: () -> Unit,
    onChanged: () -> Unit,
) {
    val c = LocalPalette.current
    val ctx = LocalContext.current
    var lead by remember { mutableStateOf(prefs.leadMinutes) }
    var prelims by remember { mutableStateOf(prefs.prelimAlerts) }
    var onlyFollowed by remember { mutableStateOf(prefs.onlyFollowed) }
    var notifTick by remember { mutableIntStateOf(0) }
    val notifOk = remember(resumeTick, notifTick) { Notify.hasPermission(ctx) }
    val exactOk = remember(resumeTick) { Alarms.canExact(ctx) }
    val notifLauncher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        notifTick++
    }

    Column(Modifier.fillMaxSize().systemBarsPadding()) {
        Row(
            Modifier.fillMaxWidth().padding(start = 4.dp, end = 16.dp, top = 8.dp, bottom = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back", tint = c.text)
            }
            Text("Settings", fontSize = 24.sp, fontWeight = FontWeight.Black, color = c.text)
        }

        Column(
            Modifier.fillMaxSize().verticalScroll(rememberScrollState())
                .padding(start = 16.dp, end = 16.dp, bottom = 32.dp),
        ) {
            SectionTitle("Appearance")
            SettingsCard {
                Text("Theme", color = c.text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                Text("Night uses true black to save battery on AMOLED screens", color = c.text3, fontSize = 12.sp)
                Spacer(Modifier.height(12.dp))
                SegmentedPicker(
                    options = listOf("system" to "📱 Auto", "day" to "☀️ Day", "night" to "🌙 Night"),
                    selected = themeMode,
                    onSelect = onTheme,
                )
            }

            SectionTitle("Alerts")
            SettingsCard {
                Text("Notify me before the start", color = c.text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(12.dp))
                SegmentedPicker(
                    options = listOf("0" to "At start", "5" to "5m", "15" to "15m", "30" to "30m", "60" to "1h"),
                    selected = lead.toString(),
                    onSelect = { v ->
                        lead = v.toInt()
                        prefs.leadMinutes = lead
                        onChanged()
                    },
                )
                SettingsDivider()
                ToggleRow("Prelims alerts", "Also alert before prelims and early prelims", prelims) {
                    prelims = it
                    prefs.prelimAlerts = it
                    onChanged()
                }
                SettingsDivider()
                ToggleRow("Only my fighters", "Only alert for cards with a fighter you follow", onlyFollowed) {
                    onlyFollowed = it
                    prefs.onlyFollowed = it
                    onChanged()
                }
            }

            SectionTitle("Permissions")
            SettingsCard {
                StatusRow(
                    title = "Notifications",
                    ok = notifOk,
                    action = "Allow",
                    onAction = {
                        if (Build.VERSION.SDK_INT >= 33) {
                            notifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                        } else {
                            ctx.startActivity(
                                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                                    .putExtra(Settings.EXTRA_APP_PACKAGE, ctx.packageName)
                            )
                        }
                    },
                )
                SettingsDivider()
                StatusRow(
                    title = "Exact alarms",
                    subtitle = "So alerts arrive right on time",
                    ok = exactOk,
                    action = "Allow",
                    onAction = {
                        if (Build.VERSION.SDK_INT >= 31) {
                            ctx.startActivity(
                                Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${ctx.packageName}"))
                            )
                        }
                    },
                )
                Spacer(Modifier.height(12.dp))
                Button(
                    onClick = {
                        Notify.show(ctx, 999, "UFC: Main card starts in 15 min", "Test alert\nThis is what your fight alerts look like")
                    },
                    modifier = Modifier.fillMaxWidth().height(48.dp),
                    shape = RoundedCornerShape(14.dp),
                    colors = ButtonDefaults.buttonColors(containerColor = RED, contentColor = Color.White),
                ) { Text("Send a test notification", fontWeight = FontWeight.SemiBold) }
            }

            SectionTitle("Fight data")
            SettingsCard {
                InfoRow("Last updated", data?.let { ago(now - it.generated) } ?: "Never")
                SettingsDivider()
                InfoRow("Source", "next-fight.com")
                SettingsDivider()
                PROMOTIONS.forEach { promo ->
                    val msg = data?.broken?.get(promo)
                    Row(Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(8.dp).clip(CircleShape).background(promoColor(promo)))
                        Spacer(Modifier.width(10.dp))
                        Text(promo, color = c.text, fontSize = 14.sp, modifier = Modifier.weight(1f))
                        Text(
                            when {
                                data == null -> "—"
                                msg != null -> "⚠ Broken"
                                else -> "✓ Working"
                            },
                            color = if (msg != null) RED else c.green, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        )
                    }
                }
                SettingsDivider()
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = { openUrl(ctx, BuildConfig.REPO_URL + "/issues") }) {
                        Text("Scraper issues", color = RED)
                    }
                    TextButton(onClick = { openUrl(ctx, BuildConfig.REPO_URL + "/actions") }) {
                        Text("GitHub Actions", color = RED)
                    }
                }
            }

            Spacer(Modifier.height(20.dp))
            Text(
                "Fight Alerts v${BuildConfig.VERSION_NAME}",
                color = c.text3, fontSize = 12.sp, textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth(),
            )
        }
    }
}

@Composable
fun SectionTitle(text: String) {
    val c = LocalPalette.current
    Text(
        text.uppercase(), color = c.text3, fontSize = 12.sp, fontWeight = FontWeight.Bold, letterSpacing = 1.2.sp,
        modifier = Modifier.padding(start = 6.dp, top = 22.dp, bottom = 8.dp),
    )
}

@Composable
fun SettingsCard(content: @Composable () -> Unit) {
    val c = LocalPalette.current
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(18.dp))
            .background(c.card).border(1.dp, c.cardBorder, RoundedCornerShape(18.dp))
            .padding(16.dp),
    ) { content() }
}

@Composable
fun SettingsDivider() {
    HorizontalDivider(color = LocalPalette.current.divider, modifier = Modifier.padding(vertical = 10.dp))
}

@Composable
fun SegmentedPicker(options: List<Pair<String, String>>, selected: String, onSelect: (String) -> Unit) {
    val c = LocalPalette.current
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(c.bg)
            .border(1.dp, c.cardBorder, RoundedCornerShape(12.dp)).padding(4.dp),
    ) {
        options.forEach { (key, label) ->
            val isSel = key == selected
            Box(
                Modifier.weight(1f).clip(RoundedCornerShape(9.dp))
                    .background(if (isSel) RED else Color.Transparent)
                    .clickable { onSelect(key) }
                    .padding(vertical = 10.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    label, fontSize = 13.sp, fontWeight = FontWeight.SemiBold, maxLines = 1,
                    color = if (isSel) Color.White else c.text2,
                )
            }
        }
    }
}

@Composable
fun ToggleRow(title: String, subtitle: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    val c = LocalPalette.current
    Row(Modifier.fillMaxWidth().clickable { onChange(!checked) }, verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f).padding(end = 12.dp)) {
            Text(title, color = c.text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
            Text(subtitle, color = c.text3, fontSize = 12.sp)
        }
        Switch(
            checked = checked,
            onCheckedChange = onChange,
            colors = SwitchDefaults.colors(
                checkedThumbColor = Color.White,
                checkedTrackColor = RED,
                uncheckedThumbColor = c.text3,
                uncheckedTrackColor = c.bg,
                uncheckedBorderColor = c.cardBorder,
            ),
        )
    }
}

@Composable
fun StatusRow(title: String, ok: Boolean, action: String, onAction: () -> Unit, subtitle: String = "") {
    val c = LocalPalette.current
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, color = c.text, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
            if (subtitle.isNotBlank()) Text(subtitle, color = c.text3, fontSize = 12.sp)
        }
        if (ok) {
            Text("✓ Allowed", color = c.green, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
        } else {
            TextButton(onClick = onAction) { Text(action, color = RED, fontWeight = FontWeight.Bold) }
        }
    }
}

@Composable
fun InfoRow(label: String, value: String) {
    val c = LocalPalette.current
    Row(Modifier.fillMaxWidth()) {
        Text(label, color = c.text3, fontSize = 14.sp, modifier = Modifier.weight(1f))
        Text(value, color = c.text, fontSize = 14.sp, fontWeight = FontWeight.Medium)
    }
}
