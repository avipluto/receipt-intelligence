package com.avipluto.receiptai.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.avipluto.receiptai.data.ApiException
import com.avipluto.receiptai.data.amount
import com.avipluto.receiptai.data.money

sealed interface Load<out T> {
    data object Loading : Load<Nothing>
    data class Ok<T>(val value: T) : Load<T>
    data class Failed(val message: String) : Load<Nothing>
}

class Loader<T>(val state: Load<T>, val reload: () -> Unit)

/** Runs [block] when [key] changes or on reload(); errors become a readable message. */
@Composable
fun <T> rememberLoad(key: Any?, block: suspend () -> T): Loader<T> {
    var state by remember { mutableStateOf<Load<T>>(Load.Loading) }
    var attempt by remember { mutableIntStateOf(0) }
    LaunchedEffect(key, attempt) {
        state = Load.Loading
        state = try {
            Load.Ok(block())
        } catch (e: ApiException) {
            Load.Failed(e.message ?: "Failed")
        } catch (e: Exception) {
            Load.Failed(e.message ?: e.javaClass.simpleName)
        }
    }
    return Loader(state) { attempt++ }
}

@Composable
fun <T> LoadView(loader: Loader<T>, content: @Composable (T) -> Unit) {
    when (val s = loader.state) {
        Load.Loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        is Load.Failed -> ErrorBox(s.message, loader.reload)
        is Load.Ok -> content(s.value)
    }
}

@Composable
fun ErrorBox(message: String, retry: (() -> Unit)? = null) {
    Card(
        Modifier.fillMaxWidth().padding(16.dp),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(message, color = MaterialTheme.colorScheme.onErrorContainer)
            if (retry != null) TextButton(onClick = retry) { Text("Try again") }
        }
    }
}

@Composable
fun ReviewNote(text: String) {
    Row(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
            .background(MaterialTheme.colorScheme.tertiaryContainer).padding(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(Icons.Filled.Warning, contentDescription = "Needs review", tint = MaterialTheme.colorScheme.onTertiaryContainer)
        Text(text, Modifier.padding(start = 8.dp), color = MaterialTheme.colorScheme.onTertiaryContainer,
            style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
fun StatTile(label: String, value: String, modifier: Modifier = Modifier) {
    Card(modifier) {
        Column(Modifier.padding(12.dp)) {
            Text(label, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(value, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold,
                maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
    }
}

/**
 * One series, so one colour and no legend: the section title names it. Each row is
 * label | bar | value, bars scaled to the largest value with rounded ends.
 */
@Composable
fun BarList(rows: List<Pair<String, String?>>) {
    val max = rows.maxOfOrNull { amount(it.second) }?.takeIf { it > 0 } ?: 1.0
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        rows.forEach { (label, value) ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(label, Modifier.width(110.dp), style = MaterialTheme.typography.bodySmall,
                    maxLines = 1, overflow = TextOverflow.Ellipsis)
                Box(Modifier.weight(1f).height(14.dp)) {
                    Box(
                        Modifier.fillMaxWidth((amount(value) / max).toFloat().coerceIn(0.02f, 1f)).height(14.dp)
                            .clip(RoundedCornerShape(topEnd = 4.dp, bottomEnd = 4.dp))
                            .background(MaterialTheme.colorScheme.primary)
                    )
                }
                Text(money(value), Modifier.width(80.dp).padding(start = 8.dp),
                    style = MaterialTheme.typography.bodySmall, maxLines = 1)
            }
        }
    }
}
