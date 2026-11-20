package com.avipluto.receiptai.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// Mirrors the FastAPI responses in src/receipt_ai/api.py.
// Money arrives as strings ("552600.00") and stays a string until display:
// the server already did exact Decimal maths, the phone never recomputes it.

@Serializable
data class Health(val ollama: String, val receipts: Int)

@Serializable
data class ReceiptRow(
    @SerialName("receipt_id") val id: Int,
    val merchant: String? = null,
    val date: String? = null,
    val total: String? = null,
    @SerialName("needs_review") val needsReview: Boolean = false,
)

@Serializable
data class Item(
    val name: String,
    val quantity: String? = null,
    @SerialName("unit_price") val unitPrice: String? = null,
    @SerialName("line_total") val lineTotal: String? = null,
)

@Serializable
data class Receipt(
    val merchant: String? = null,
    val date: String? = null,
    val currency: String? = null,
    val subtotal: String? = null,
    val tax: String? = null,
    @SerialName("service_charge") val serviceCharge: String? = null,
    val discount: String? = null,
    val total: String? = null,
    @SerialName("payment_method") val paymentMethod: String? = null,
    @SerialName("needs_review") val needsReview: Boolean = false,
    val issues: List<String> = emptyList(),
    val items: List<Item> = emptyList(),
)

@Serializable
data class ReceiptDetail(
    @SerialName("receipt_id") val id: Int,
    val merchant: String? = null,
    val date: String? = null,
    val subtotal: String? = null,
    val tax: String? = null,
    @SerialName("service_charge") val serviceCharge: String? = null,
    val discount: String? = null,
    val total: String? = null,
    @SerialName("payment_method") val paymentMethod: String? = null,
    @SerialName("needs_review") val needsReview: Boolean = false,
    val issues: List<String> = emptyList(),
    val items: List<Item> = emptyList(),
    @SerialName("ocr_text") val ocrText: String = "",
    @SerialName("file_name") val fileName: String = "",
)

@Serializable
data class UploadResult(
    @SerialName("receipt_id") val id: Int,
    val created: Boolean,
    val duplicate: Boolean,
    val receipt: Receipt,
)

@Serializable
data class AskRequest(val question: String)

@Serializable
data class AskResult(
    val question: String,
    val answer: String,
    @SerialName("used_llm") val usedLlm: Boolean,
    val period: String,
    val route: JsonObject,
    val rows: List<JsonObject> = emptyList(),
    @SerialName("receipt_ids") val receiptIds: List<Int> = emptyList(),
    @SerialName("needs_review") val needsReview: Int = 0,
    val note: String = "",
)

@Serializable
data class MerchantStat(val merchant: String, val receipts: Int, val total: String? = null)

@Serializable
data class MonthStat(val month: String, val receipts: Int, val total: String? = null)

@Serializable
data class Stats<T>(val rows: List<T> = emptyList(), val note: String = "")
