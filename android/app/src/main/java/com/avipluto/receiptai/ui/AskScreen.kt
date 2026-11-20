package com.avipluto.receiptai.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.dp
import com.avipluto.receiptai.data.AskResult
import kotlinx.coroutines.launch
import kotlinx.serialization.json.jsonPrimitive

private val EXAMPLES = listOf(
    "How much did I spend in total?",
    "Which store got the most money?",
    "How much did I spend last month?",
    "Did I buy any coffee?",
)

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun AskScreen(vm: AppViewModel, openReceipt: (Int) -> Unit) {
    val scope = rememberCoroutineScope()
    var question by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun submit(q: String) {
        if (q.isBlank() || busy) return
        busy = true; error = null
        scope.launch {
            try {
                vm.askHistory.add(0, vm.api().ask(q.trim()))
                question = ""
            } catch (e: Exception) {
                error = e.message
            } finally {
                busy = false
            }
        }
    }

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = question, onValueChange = { question = it },
                label = { Text("Ask about your spending") },
                modifier = Modifier.weight(1f), singleLine = true,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(onSend = { submit(question) }),
            )
            if (busy) CircularProgressIndicator(Modifier.padding(start = 12.dp))
            else IconButton(onClick = { submit(question) }) { Icon(Icons.AutoMirrored.Filled.Send, "Ask") }
        }
        error?.let { ErrorBox(it) }
        if (vm.askHistory.isEmpty()) {
            FlowRow(Modifier.padding(horizontal = 16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                EXAMPLES.forEach { SuggestionChip(onClick = { submit(it) }, label = { Text(it) }) }
            }
        }
        LazyColumn(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            items(vm.askHistory) { AnswerCard(it, openReceipt) }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AnswerCard(a: AskResult, openReceipt: (Int) -> Unit) {
    Card(Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(a.question, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            Text(a.answer, style = MaterialTheme.typography.bodyLarge)
            val tool = a.route["tool"]?.jsonPrimitive?.content ?: "?"
            // Say how the answer was made: honest about when the LLM phrased it.
            Text(
                "Searched: $tool · ${a.period} · " +
                    if (a.usedLlm) "worded by the local AI, numbers checked against your data" else "exact figures from your data",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            if (a.note.isNotBlank()) Text(a.note, style = MaterialTheme.typography.bodySmall)
            if (a.receiptIds.isNotEmpty()) {
                Text("Sources", style = MaterialTheme.typography.labelMedium)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    a.receiptIds.take(12).forEach { id -> AssistChip(onClick = { openReceipt(id) }, label = { Text("#$id") }) }
                    if (a.receiptIds.size > 12) Text("+${a.receiptIds.size - 12} more", Modifier.align(Alignment.CenterVertically))
                }
            }
        }
    }
}
