package com.avipluto.receiptai.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import com.avipluto.receiptai.data.Api
import com.avipluto.receiptai.data.ServerConfig
import com.avipluto.receiptai.data.SettingsRepo
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(vm: AppViewModel) {
    val saved by vm.config.collectAsState()
    var url by remember { mutableStateOf("") }
    var token by remember { mutableStateOf("") }
    var status by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(saved) { saved?.let { url = it.baseUrl; token = it.token } }

    Column(Modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)
        Text(
            "The AI runs on your laptop, not on this phone. Start the server there, then enter its Wi-Fi address " +
                "(the phone and laptop must be on the same Wi-Fi).",
            style = MaterialTheme.typography.bodyMedium,
        )
        OutlinedTextField(
            url, { url = it }, Modifier.fillMaxWidth(), label = { Text("Laptop address") },
            placeholder = { Text("192.168.1.7:8765") }, singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
        )
        OutlinedTextField(
            token, { token = it }, Modifier.fillMaxWidth(), label = { Text("Access key (RECEIPTS_API_TOKEN)") },
            singleLine = true, visualTransformation = PasswordVisualTransformation(),
        )
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = { vm.save(url, token); status = "Saved." }) { Text("Save") }
            OutlinedButton(onClick = {
                status = "Testing…"
                scope.launch {
                    status = try {
                        val h = Api(ServerConfig(SettingsRepo.normalizeUrl(url), token.trim())).health()
                        "Connected ✓  ${h.receipts} receipts · local AI: ${h.ollama}"
                    } catch (e: Exception) {
                        e.message
                    }
                }
            }) { Text("Test connection") }
        }
        status?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
    }
}
