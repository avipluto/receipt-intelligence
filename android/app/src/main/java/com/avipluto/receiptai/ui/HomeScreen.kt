package com.avipluto.receiptai.ui

import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.core.content.FileProvider
import com.avipluto.receiptai.data.UploadResult
import com.avipluto.receiptai.data.money
import com.avipluto.receiptai.data.preparePhoto
import com.avipluto.receiptai.data.sum
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File

private data class Dashboard(
    val ollama: String,
    val total: String,
    val receipts: Int,
    val flagged: Int,
    val merchants: List<Pair<String, String?>>,
    val months: List<Pair<String, String?>>,
    val monthNote: String,
)

@Composable
fun HomeScreen(vm: AppViewModel, openReceipt: (Int) -> Unit, openSettings: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var refresh by remember { mutableIntStateOf(0) }
    var uploading by remember { mutableStateOf(false) }
    var result by remember { mutableStateOf<UploadResult?>(null) }
    var uploadError by remember { mutableStateOf<String?>(null) }
    var pendingCapture by remember { mutableStateOf<Uri?>(null) }

    fun upload(uri: Uri) {
        uploading = true; uploadError = null
        scope.launch {
            try {
                val bytes = withContext(Dispatchers.IO) { preparePhoto(context, uri) }
                result = vm.api().upload("receipt.jpg", bytes, "image/jpeg")
                refresh++
            } catch (e: Exception) {
                uploadError = e.message ?: "Upload failed"
            } finally {
                uploading = false
            }
        }
    }

    val camera = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { ok ->
        pendingCapture?.let { if (ok) upload(it) }
    }
    val gallery = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        uri?.let(::upload)
    }

    val loader = rememberLoad(refresh to vm.config.value) {
        val api = vm.api()
        coroutineScope {
            val health = async { api.health() }
            val rows = async { api.receipts() }
            val merchants = async { api.merchants() }
            val months = async { api.monthly() }
            val r = rows.await()
            Dashboard(
                ollama = health.await().ollama,
                total = sum(r.map { it.total }),
                receipts = r.size,
                flagged = r.count { it.needsReview },
                merchants = merchants.await().rows.map { it.merchant to it.total },
                months = months.await().let { m -> m.rows.map { it.month to it.total } },
                monthNote = months.await().note,
            )
        }
    }

    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Receipt AI", style = MaterialTheme.typography.headlineMedium)

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = {
                val dir = File(context.cacheDir, "captures").apply { mkdirs() }
                val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", File(dir, "capture.jpg"))
                pendingCapture = uri
                camera.launch(uri)
            }, enabled = !uploading, modifier = Modifier.weight(1f)) {
                Icon(Icons.Filled.CameraAlt, null); Spacer(Modifier.padding(4.dp)); Text("Scan receipt")
            }
            OutlinedButton(onClick = {
                gallery.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            }, enabled = !uploading, modifier = Modifier.weight(1f)) {
                Icon(Icons.Filled.PhotoLibrary, null); Spacer(Modifier.padding(4.dp)); Text("From gallery")
            }
        }
        if (uploading) {
            Column {
                Text("Reading the receipt on your laptop (OCR + local AI, ~20 s)…", style = MaterialTheme.typography.bodySmall)
                Spacer(Modifier.height(4.dp))
                LinearProgressIndicator(Modifier.fillMaxWidth())
            }
        }
        uploadError?.let { ErrorBox(it) }

        when (val s = loader.state) {
            Load.Loading -> LinearProgressIndicator(Modifier.fillMaxWidth())
            is Load.Failed -> {
                ErrorBox(s.message, loader.reload)
                if (vm.config.value?.isSet != true) TextButton(onClick = openSettings) { Text("Open Settings") }
            }
            is Load.Ok -> DashboardBody(s.value)
        }
    }

    result?.let { r ->
        AlertDialog(
            onDismissRequest = { result = null },
            title = { Text(if (r.duplicate) "Already saved" else "Receipt saved") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("${r.receipt.merchant ?: "Unknown merchant"} · total ${money(r.receipt.total)}")
                    if (r.receipt.needsReview) ReviewNote("Please check: " + r.receipt.issues.joinToString("; "))
                }
            },
            confirmButton = { TextButton(onClick = { result = null; openReceipt(r.id) }) { Text("Open") } },
            dismissButton = { TextButton(onClick = { result = null }) { Text("Close") } },
        )
    }
}

@Composable
private fun DashboardBody(d: Dashboard) {
    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        if (d.ollama != "ok") ErrorBox("The laptop's local AI (Ollama) is ${d.ollama}. Uploads and questions won't work until it runs.")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            StatTile("Total spent", money(d.total), Modifier.weight(1.4f))
            StatTile("Receipts", d.receipts.toString(), Modifier.weight(1f))
            StatTile("To review", d.flagged.toString(), Modifier.weight(1f))
        }
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Spending per month", style = MaterialTheme.typography.titleMedium)
                if (d.months.isEmpty()) Text("No dated receipts yet.", style = MaterialTheme.typography.bodySmall)
                else BarList(d.months)
                if (d.monthNote.isNotBlank()) Text(d.monthNote, style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Card {
            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                Text("Top merchants", style = MaterialTheme.typography.titleMedium)
                if (d.merchants.isEmpty()) Text("No receipts yet. Scan one!", style = MaterialTheme.typography.bodySmall)
                else BarList(d.merchants)
            }
        }
    }
}
