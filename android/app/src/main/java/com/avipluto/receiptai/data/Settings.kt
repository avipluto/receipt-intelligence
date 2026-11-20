package com.avipluto.receiptai.data

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.store by preferencesDataStore(name = "settings")

/** Where the laptop server is, and the access key it expects (RECEIPTS_API_TOKEN). */
data class ServerConfig(val baseUrl: String, val token: String) {
    val isSet get() = baseUrl.isNotBlank()
}

class SettingsRepo(private val context: Context) {
    private val urlKey = stringPreferencesKey("base_url")
    private val tokenKey = stringPreferencesKey("token")

    val config: Flow<ServerConfig> = context.store.data.map {
        ServerConfig(it[urlKey] ?: "", it[tokenKey] ?: "")
    }

    suspend fun save(baseUrl: String, token: String) {
        context.store.edit {
            it[urlKey] = normalizeUrl(baseUrl)
            it[tokenKey] = token.trim()
        }
    }

    companion object {
        /** "192.168.1.7:8765" -> "http://192.168.1.7:8765"; trailing slashes dropped. */
        fun normalizeUrl(input: String): String {
            val s = input.trim().trimEnd('/')
            if (s.isEmpty()) return s
            return if (s.startsWith("http://") || s.startsWith("https://")) s else "http://$s"
        }
    }
}
