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
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
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

// ---------------------------------------------------------------- data

val PROMOTIONS = listOf("UFC", "BKFC", "ONE", "RAF")

private val RED = Color(0xFFE53935)
private val GOLD = Color(0xFFFFB300)
private val CARD_BG = Color(0xFF1E1E1E)

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

data class FightData(val generated: Long, val events: List<FightEvent>, val broken: Map<String, String>)

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
    val health = root.optJSONObject("health")
    if (health != null) {
        for (key in health.keys()) {
            val h = health.getJSONObject(key)
            if (!h.optBoolean("ok", true)) broken[key] = h.optString("message")
        }
    }
    return FightData(root.optLong("generatedMs"), events, broken)
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
}

fun mainBout(e: FightEvent): Bout? =
    e.bouts.firstOrNull { it.section.equals("Main Event", ignoreCase = true) } ?: e.bouts.firstOrNull()

// ---------------------------------------------------------------- alarms & notifications

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

// ---------------------------------------------------------------- formatting helpers

private val TIME_FMT = DateTimeFormatter.ofPattern("EEE d MMM, h:mm a")

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
    if (firstStart != null && now >= firstStart) return "PRELIMS UNDERWAY"
    val mins = (e.start - now) / 60_000
    val d = mins / 1440
    val h = (mins % 1440) / 60
    val m = mins % 60
    return when {
        d > 0 -> "in ${d}d ${h}h"
        h > 0 -> "in ${h}h ${m}m"
        else -> "in ${m}m"
    }
}

fun promoColor(p: String): Color = when (p) {
    "UFC" -> Color(0xFFD20A0A)
    "BKFC" -> Color(0xFF8E24AA)
    "ONE" -> Color(0xFFF9A825)
    "RAF" -> Color(0xFF1565C0)
    else -> Color.DarkGray
}

// ---------------------------------------------------------------- UI

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        Notify.ensureChannel(this)
        RefreshWorker.enqueue(this)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = RED, secondary = GOLD)) {
                Surface(Modifier.fillMaxSize(), color = Color(0xFF121212)) {
                    AppScreen()
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // re-arm alarms in case the exact-alarm permission was just granted
        Repo.loadCached(this)?.let { Alarms.scheduleAll(this, it) }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppScreen() {
    val ctx = LocalContext.current
    val prefs = remember { Prefs(ctx) }
    val scope = rememberCoroutineScope()

    var data by remember { mutableStateOf(Repo.loadCached(ctx)) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var promotions by remember { mutableStateOf(prefs.promotions) }
    var followed by remember { mutableStateOf(prefs.followed) }
    var showSettings by remember { mutableStateOf(false) }
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

    Column(Modifier.fillMaxSize().systemBarsPadding()) {
        // header
        Row(Modifier.fillMaxWidth().padding(16.dp, 12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("🥊 Fight Alerts", fontSize = 22.sp, fontWeight = FontWeight.Bold, color = Color.White)
                Text(
                    data?.let { "Data updated ${ago(now - it.generated)}" } ?: "No data yet",
                    fontSize = 12.sp, color = Color.Gray,
                )
            }
            TextButton(onClick = { refresh() }, enabled = !loading) { Text(if (loading) "Loading…" else "Refresh") }
            TextButton(onClick = { showSettings = true }) { Text("Settings") }
        }

        // warnings: broken scraper / stale data / download errors
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
                "⚠ $w", color = Color.Black, fontSize = 13.sp,
                modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)
                    .background(GOLD, RoundedCornerShape(8.dp)).padding(10.dp),
            )
        }

        // promotion toggles (controls both what's shown and what alerts you get)
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp)) {
            PROMOTIONS.forEach { p ->
                FilterChip(
                    selected = p in promotions,
                    onClick = {
                        promotions = if (p in promotions) promotions - p else promotions + p
                        prefs.promotions = promotions
                        reschedule()
                    },
                    label = { Text(p) },
                    modifier = Modifier.padding(end = 8.dp),
                )
            }
        }

        val events = d?.events.orEmpty()
            .filter { it.promotion in promotions && it.start > now - 6 * 3_600_000L }
            .sortedBy { it.start }

        if (events.isEmpty()) {
            Text(
                if (d == null) "Loading fights…" else "No upcoming fights for the promotions you picked.",
                color = Color.Gray, modifier = Modifier.padding(24.dp),
            )
        }

        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(12.dp)) {
            items(events, key = { it.id }) { e ->
                EventCard(e, now, followed) { name ->
                    followed = if (name in followed) followed - name else followed + name
                    prefs.followed = followed
                    reschedule()
                }
            }
        }
    }

    if (showSettings) {
        SettingsDialog(prefs) {
            showSettings = false
            reschedule()
        }
    }
}

@Composable
fun EventCard(e: FightEvent, now: Long, followed: Set<String>, onFollow: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val ctx = LocalContext.current
    val hasFollowed = e.bouts.any { it.a.name in followed || it.b.name in followed }
    var selected by remember { mutableStateOf<Pair<Bout, Boolean>?>(null) }

    Card(
        modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp).clickable { expanded = !expanded },
        colors = CardDefaults.cardColors(containerColor = CARD_BG),
    ) {
        Column(Modifier.padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    e.promotion, color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                    modifier = Modifier.background(promoColor(e.promotion), RoundedCornerShape(4.dp))
                        .padding(horizontal = 6.dp, vertical = 2.dp),
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    countdown(e, now),
                    color = if (now >= (e.earlyPrelims ?: e.prelims ?: e.start)) RED else GOLD,
                    fontSize = 12.sp, fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.weight(1f))
                if (hasFollowed) Text("★", color = GOLD, fontSize = 16.sp)
            }
            Spacer(Modifier.height(6.dp))
            Text(e.title, color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.Bold)
            Text("Main card: ${fmt(e.start)}", color = Color.LightGray, fontSize = 13.sp)
            e.prelims?.let { Text("Prelims: ${fmt(it)}", color = Color.Gray, fontSize = 12.sp) }
            e.earlyPrelims?.let { Text("Early prelims: ${fmt(it)}", color = Color.Gray, fontSize = 12.sp) }

            if (!expanded) {
                val main = mainBout(e)
                Text(
                    if (main != null) "${withFlag(main.a)} vs ${withFlag(main.b)}" else "Card to be announced",
                    color = if (main != null) Color.White else Color.Gray,
                    fontSize = 14.sp, modifier = Modifier.padding(top = 6.dp),
                )
                if (e.bouts.size > 1) {
                    Text("Tap to see all ${e.bouts.size} fights", color = Color.Gray, fontSize = 11.sp)
                }
            } else {
                if (e.bouts.isEmpty()) {
                    Text("Card to be announced", color = Color.Gray, modifier = Modifier.padding(top = 8.dp))
                }
                var lastSection = ""
                e.bouts.forEach { b ->
                    if (b.section.isNotBlank() && b.section != lastSection) {
                        lastSection = b.section
                        Text(
                            b.section.uppercase(), color = RED, fontSize = 11.sp, fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(top = 10.dp, bottom = 2.dp),
                        )
                    }
                    Row(
                        Modifier.fillMaxWidth().padding(vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        FighterName(b.a, b.a.name in followed, Modifier.weight(1f), alignEnd = false) { selected = b to true }
                        Text("vs", color = Color.Gray, fontSize = 12.sp, modifier = Modifier.padding(horizontal = 6.dp))
                        FighterName(b.b, b.b.name in followed, Modifier.weight(1f), alignEnd = true) { selected = b to false }
                    }
                    val info = listOfNotNull(b.weight.ifBlank { null }, if (b.title) "Title fight" else null)
                        .joinToString(" · ")
                    if (info.isNotEmpty()) {
                        Text(
                            info, color = Color.Gray, fontSize = 11.sp, textAlign = TextAlign.Center,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                }
                Text(
                    "Tap a fighter for their profile and to follow them ★", color = Color.Gray, fontSize = 11.sp,
                    modifier = Modifier.padding(top = 10.dp),
                )
                if (e.url.isNotBlank()) {
                    TextButton(onClick = {
                        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(e.url)))
                    }) { Text("Open full event page") }
                }
            }
        }
    }

    selected?.let { (bout, isA) ->
        val f = if (isA) bout.a else bout.b
        val opp = if (isA) bout.b else bout.a
        FighterDialog(
            f = f, opponent = opp, bout = bout, event = e,
            isFollowed = f.name in followed,
            onFollow = { onFollow(f.name) },
            onDismiss = { selected = null },
        )
    }
}

fun withFlag(f: Fighter): String = if (f.flag.isNotBlank()) "${f.flag} ${f.name}" else f.name

@Composable
fun FighterName(f: Fighter, isFollowed: Boolean, modifier: Modifier, alignEnd: Boolean, onClick: () -> Unit) {
    Column(
        modifier = modifier.clickable { onClick() }.padding(4.dp),
        horizontalAlignment = if (alignEnd) Alignment.End else Alignment.Start,
    ) {
        Text(
            text = (if (isFollowed) "★ " else "") + withFlag(f),
            color = if (isFollowed) GOLD else Color.White,
            fontWeight = if (isFollowed) FontWeight.Bold else FontWeight.Normal,
            fontSize = 14.sp,
            textAlign = if (alignEnd) TextAlign.End else TextAlign.Start,
        )
        if (f.record.isNotBlank()) {
            Text(f.record, color = Color.Gray, fontSize = 11.sp)
        }
    }
}

@Composable
fun FighterPhoto(f: Fighter, size: androidx.compose.ui.unit.Dp) {
    Box(
        modifier = Modifier.size(size).clip(CircleShape).background(Color(0xFF2A2A2A)),
        contentAlignment = Alignment.Center,
    ) {
        val initials = f.name.split(" ").filter { it.isNotBlank() }.take(2).joinToString("") { it.take(1).uppercase() }
        Text(initials, color = Color.Gray, fontSize = 32.sp, fontWeight = FontWeight.Bold)
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

@Composable
fun RecordBoxes(record: String) {
    val parts = record.split("-").map { it.trim() }
    if (parts.size < 2) {
        Text(record, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
        return
    }
    val labels = listOf("Wins" to Color(0xFF43A047), "Losses" to RED, "Draws" to Color.Gray)
    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
        parts.take(3).forEachIndexed { i, n ->
            val (label, color) = labels[i]
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                modifier = Modifier.background(Color(0xFF262626), RoundedCornerShape(10.dp))
                    .padding(horizontal = 14.dp, vertical = 8.dp),
            ) {
                Text(n, color = color, fontSize = 22.sp, fontWeight = FontWeight.Bold)
                Text(label, color = Color.Gray, fontSize = 11.sp)
            }
        }
    }
}

@Composable
fun FighterDialog(
    f: Fighter,
    opponent: Fighter,
    bout: Bout,
    event: FightEvent,
    isFollowed: Boolean,
    onFollow: () -> Unit,
    onDismiss: () -> Unit,
) {
    val ctx = LocalContext.current
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = {
            TextButton(onClick = onFollow) { Text(if (isFollowed) "★ Unfollow" else "☆ Follow") }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text("Close") } },
        text = {
            Column(
                Modifier.fillMaxWidth().verticalScroll(rememberScrollState()),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                FighterPhoto(f, 112.dp)
                Spacer(Modifier.height(10.dp))
                Text(
                    withFlag(f), color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center,
                )
                if (f.nickname.isNotBlank()) {
                    Text("“${f.nickname}”", color = Color.LightGray, fontStyle = FontStyle.Italic, fontSize = 14.sp)
                }
                if (f.country.isNotBlank()) {
                    Text(f.country, color = Color.Gray, fontSize = 13.sp)
                }
                if (f.rank.isNotBlank()) {
                    Text(
                        if (f.rank == "C") "🏆 Champion" else "Ranked ${f.rank}",
                        color = GOLD, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
                if (f.record.isNotBlank()) {
                    Spacer(Modifier.height(12.dp))
                    RecordBoxes(f.record)
                }
                if (f.stats.isNotEmpty()) {
                    Spacer(Modifier.height(12.dp))
                    f.stats.forEach { (label, value) ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
                            Text(label, color = Color.Gray, fontSize = 13.sp, modifier = Modifier.weight(1f))
                            Text(value, color = Color.White, fontSize = 13.sp)
                        }
                    }
                }
                Spacer(Modifier.height(12.dp))
                HorizontalDivider(color = Color(0xFF333333))
                Spacer(Modifier.height(10.dp))
                Text("NEXT FIGHT", color = RED, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                Text(
                    "vs ${withFlag(opponent)}" + if (opponent.record.isNotBlank()) " (${opponent.record})" else "",
                    color = Color.White, fontSize = 15.sp, textAlign = TextAlign.Center,
                )
                Text(
                    listOfNotNull(
                        bout.weight.ifBlank { null },
                        if (bout.title) "Title fight" else null,
                        bout.section.ifBlank { null },
                    ).joinToString(" · "),
                    color = Color.Gray, fontSize = 12.sp, textAlign = TextAlign.Center,
                )
                Text("${event.promotion} · ${event.title}", color = Color.LightGray, fontSize = 13.sp, textAlign = TextAlign.Center)
                Text(fmt(event.start), color = Color.Gray, fontSize = 12.sp)
                if (f.url.isNotBlank()) {
                    TextButton(onClick = {
                        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(f.url)))
                    }) { Text("Full profile on next-fight.com") }
                }
            }
        },
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsDialog(prefs: Prefs, onDismiss: () -> Unit) {
    val ctx = LocalContext.current
    var lead by remember { mutableStateOf(prefs.leadMinutes) }
    var prelims by remember { mutableStateOf(prefs.prelimAlerts) }
    var onlyFollowed by remember { mutableStateOf(prefs.onlyFollowed) }

    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = onDismiss) { Text("Done") } },
        title = { Text("Alert settings") },
        text = {
            Column {
                Text("Notify me before the start:")
                Row(Modifier.horizontalScroll(rememberScrollState())) {
                    listOf(0, 5, 15, 30, 60).forEach { m ->
                        FilterChip(
                            selected = lead == m,
                            onClick = { lead = m; prefs.leadMinutes = m },
                            label = { Text(if (m == 0) "At start" else "$m min") },
                            modifier = Modifier.padding(end = 6.dp),
                        )
                    }
                }
                SettingRow("Also alert for prelims", prelims) { prelims = it; prefs.prelimAlerts = it }
                SettingRow("Only cards with fighters I follow", onlyFollowed) {
                    onlyFollowed = it
                    prefs.onlyFollowed = it
                }
                if (!Alarms.canExact(ctx) && Build.VERSION.SDK_INT >= 31) {
                    TextButton(onClick = {
                        ctx.startActivity(
                            Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM, Uri.parse("package:${ctx.packageName}"))
                        )
                    }) { Text("Allow exact alarms (so alerts arrive on time)") }
                }
                if (!Notify.hasPermission(ctx)) {
                    Text("Notifications are turned off for this app — enable them in Android settings.", color = RED)
                }
                TextButton(onClick = {
                    Notify.show(ctx, 999, "UFC: Main card starts in 15 min", "Test alert\nThis is what your fight alerts look like")
                }) { Text("Send a test notification") }
            }
        },
    )
}

@Composable
fun SettingRow(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChange)
    }
}
