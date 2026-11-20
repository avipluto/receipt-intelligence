package com.avipluto.receiptai.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.IOException
import java.util.concurrent.TimeUnit

/** A failure the UI can show as-is. */
class ApiException(message: String) : Exception(message)

/**
 * Thin client over the laptop's FastAPI. All network work runs on Dispatchers.IO.
 *
 * Timeouts are long on purpose: reading a receipt is OCR (~10 s on the laptop CPU)
 * plus the local LLM (~8 s), and a question is two LLM calls.
 */
class Api(private val config: ServerConfig) {

    val imageHeaders: Map<String, String> =
        if (config.token.isNotBlank()) mapOf("X-API-Key" to config.token) else emptyMap()

    fun fileUrl(receiptId: Int) = "${config.baseUrl}/receipts/$receiptId/file"

    suspend fun health(): Health = get("/health")
    suspend fun receipts(): List<ReceiptRow> = get("/receipts?limit=500")
    suspend fun receipt(id: Int): ReceiptDetail = get("/receipts/$id")
    suspend fun merchants(): Stats<MerchantStat> = get("/stats/merchants?top_n=8")
    suspend fun monthly(): Stats<MonthStat> = get("/stats/monthly")

    suspend fun ask(question: String): AskResult =
        send("/ask", json.encodeToString(AskRequest.serializer(), AskRequest(question)).toRequestBody(JSON))

    suspend fun upload(fileName: String, bytes: ByteArray, mime: String): UploadResult {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", fileName, bytes.toRequestBody(mime.toMediaType()))
            .build()
        return send("/receipts", body)
    }

    private suspend inline fun <reified T> get(path: String): T =
        call(Request.Builder().url(config.baseUrl + path).get())

    private suspend inline fun <reified T> send(path: String, body: okhttp3.RequestBody): T =
        call(Request.Builder().url(config.baseUrl + path).post(body))

    private suspend inline fun <reified T> call(builder: Request.Builder): T = withContext(Dispatchers.IO) {
        if (!config.isSet) throw ApiException("Set the laptop's address in Settings first.")
        imageHeaders.forEach { (k, v) -> builder.header(k, v) }
        val request = try {
            builder.build()
        } catch (e: IllegalArgumentException) {
            throw ApiException("\"${config.baseUrl}\" isn't a valid address.")
        }
        try {
            client.newCall(request).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                when {
                    resp.code == 401 -> throw ApiException("Wrong or missing access key (Settings).")
                    !resp.isSuccessful -> throw ApiException("Server error ${resp.code}: ${detail(text)}")
                    else -> json.decodeFromString<T>(text)
                }
            }
        } catch (e: IOException) {
            throw ApiException("Can't reach the laptop at ${config.baseUrl}. Same Wi-Fi? Server running?")
        }
    }

    private fun detail(body: String): String =
        Regex("\"detail\"\\s*:\\s*\"([^\"]*)\"").find(body)?.groupValues?.get(1) ?: body.take(200)

    companion object {
        private val JSON = "application/json".toMediaType()
        val json = Json { ignoreUnknownKeys = true }
        private val client = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.MINUTES)
            .writeTimeout(1, TimeUnit.MINUTES)
            .build()
    }
}
