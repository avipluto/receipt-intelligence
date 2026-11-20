package com.avipluto.receiptai.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.avipluto.receiptai.data.Api
import com.avipluto.receiptai.data.AskResult
import com.avipluto.receiptai.data.ServerConfig
import com.avipluto.receiptai.data.SettingsRepo
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.launch

/** App-wide state: the server settings, and the Ask history (kept while the app runs). */
class AppViewModel(app: Application) : AndroidViewModel(app) {
    val settings = SettingsRepo(app)

    val config: StateFlow<ServerConfig?> = settings.config
        .map<ServerConfig, ServerConfig?> { it }
        .stateIn(viewModelScope, SharingStarted.Eagerly, null)

    fun api() = Api(config.value ?: ServerConfig("", ""))

    val askHistory = androidx.compose.runtime.mutableStateListOf<AskResult>()

    fun save(url: String, token: String) = viewModelScope.launch { settings.save(url, token) }
}
