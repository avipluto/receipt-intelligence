package com.avipluto.receiptai.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import coil.request.ImageRequest
import com.avipluto.receiptai.data.money

@Composable
fun ReceiptListScreen(vm: AppViewModel, openReceipt: (Int) -> Unit) {
    var onlyFlagged by remember { mutableStateOf(false) }
    val loader = rememberLoad(vm.config.value) { vm.api().receipts() }

    Column {
        Row(Modifier.padding(16.dp, 16.dp, 16.dp, 0.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Receipts", style = MaterialTheme.typography.headlineSmall, modifier = Modifier.weight(1f))
            FilterChip(selected = onlyFlagged, onClick = { onlyFlagged = !onlyFlagged }, label = { Text("Needs review") })
        }
        LoadView(loader) { all ->
            val rows = if (onlyFlagged) all.filter { it.needsReview } else all
            if (rows.isEmpty()) Text("Nothing here yet.", Modifier.padding(16.dp))
            LazyColumn {
                items(rows, key = { it.id }) { r ->
                    ListItem(
                        headlineContent = { Text(r.merchant ?: "Unknown merchant") },
                        supportingContent = { Text("#${r.id} · ${r.date ?: "no date"}") },
                        trailingContent = {
                            Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                if (r.needsReview) Icon(Icons.Filled.Warning, "Needs review", tint = MaterialTheme.colorScheme.tertiary)
                                Text(money(r.total), fontWeight = FontWeight.SemiBold)
                            }
                        },
                        modifier = Modifier.clickable { openReceipt(r.id) },
                    )
                    HorizontalDivider()
                }
            }
        }
    }
}

/** A receipt and its evidence: the original photo, what was extracted, and what OCR read. */
@Composable
fun ReceiptDetailScreen(vm: AppViewModel, id: Int) {
    val context = LocalContext.current
    var showOcr by remember { mutableStateOf(false) }
    val loader = rememberLoad(id) { vm.api().receipt(id) }

    LoadView(loader) { r ->
        val api = vm.api()
        Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text(r.merchant ?: "Unknown merchant", style = MaterialTheme.typography.headlineSmall)
            Text("Receipt #${r.id} · ${r.date ?: "no date"}", color = MaterialTheme.colorScheme.onSurfaceVariant)
            r.issues.forEach { ReviewNote(it) }

            Card {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Line("Subtotal", r.subtotal)
                    Line("Tax", r.tax)
                    if (r.serviceCharge != null) Line("Service", r.serviceCharge)
                    if (r.discount != null) Line("Discount", r.discount)
                    HorizontalDivider()
                    Line("Total", r.total, bold = true)
                    r.paymentMethod?.let { Text("Paid: $it", style = MaterialTheme.typography.bodySmall) }
                }
            }

            if (r.items.isNotEmpty()) {
                Card {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                        Text("Items", style = MaterialTheme.typography.titleMedium)
                        r.items.forEach { Line(listOfNotNull(it.quantity?.let { q -> "$q×" }, it.name).joinToString(" "), it.lineTotal) }
                    }
                }
            }

            if (!r.fileName.lowercase().endsWith(".pdf")) {
                AsyncImage(
                    model = ImageRequest.Builder(context).data(api.fileUrl(r.id))
                        .apply { api.imageHeaders.forEach { (k, v) -> addHeader(k, v) } }.build(),
                    contentDescription = "Original receipt photo",
                    contentScale = ContentScale.FillWidth,
                    modifier = Modifier.fillMaxWidth().heightIn(max = 600.dp),
                )
            }
            TextButton(onClick = { showOcr = !showOcr }) { Text(if (showOcr) "Hide OCR text" else "Show what OCR read") }
            if (showOcr) Text(r.ocrText, fontFamily = FontFamily.Monospace, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun Line(label: String, value: String?, bold: Boolean = false) {
    Row(Modifier.fillMaxWidth()) {
        Text(label, Modifier.weight(1f), fontWeight = if (bold) FontWeight.Bold else null)
        Text(money(value), fontWeight = if (bold) FontWeight.Bold else null)
    }
}
