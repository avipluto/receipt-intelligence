package com.avipluto.receiptai.data

import java.math.BigDecimal
import java.text.DecimalFormat

/** "552600.00" -> "552,600"; "120.50" -> "120.50"; null -> "—". Display only; never used for maths. */
fun money(value: String?): String {
    if (value.isNullOrBlank()) return "—"
    val d = value.toBigDecimalOrNull() ?: return value
    val whole = d.stripTrailingZeros().scale() <= 0
    return DecimalFormat(if (whole) "#,##0" else "#,##0.00").format(d)
}

/** For chart bar lengths only. */
fun amount(value: String?): Double = value?.toBigDecimalOrNull()?.toDouble() ?: 0.0

fun sum(values: List<String?>): String =
    values.mapNotNull { it?.toBigDecimalOrNull() }.fold(BigDecimal.ZERO, BigDecimal::add).toPlainString()
