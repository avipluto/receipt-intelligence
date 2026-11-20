package com.avipluto.receiptai.data

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import android.media.ExifInterface
import android.net.Uri
import java.io.ByteArrayOutputStream

private const val MAX_SIDE = 2000

/**
 * Read a photo and shrink it to at most 2000 px on the long side, as JPEG.
 * Phone photos are 4-8 MB; this keeps uploads quick on Wi-Fi while staying sharper
 * than the CORD benchmark photos (864x1296) the OCR was measured on.
 * Camera photos are often stored sideways with an EXIF rotation tag, so we apply it.
 */
fun preparePhoto(context: Context, uri: Uri): ByteArray {
    val resolver = context.contentResolver
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    resolver.openInputStream(uri).use { BitmapFactory.decodeStream(it, null, bounds) }
    require(bounds.outWidth > 0) { "That file isn't an image." }

    var sample = 1
    while (maxOf(bounds.outWidth, bounds.outHeight) / (sample * 2) >= MAX_SIDE) sample *= 2
    val decoded = resolver.openInputStream(uri).use {
        BitmapFactory.decodeStream(it, null, BitmapFactory.Options().apply { inSampleSize = sample })
    } ?: error("Couldn't read the image.")

    val rotation = resolver.openInputStream(uri).use { stream ->
        when (stream?.let { ExifInterface(it) }?.getAttributeInt(ExifInterface.TAG_ORIENTATION, 1)) {
            ExifInterface.ORIENTATION_ROTATE_90 -> 90f
            ExifInterface.ORIENTATION_ROTATE_180 -> 180f
            ExifInterface.ORIENTATION_ROTATE_270 -> 270f
            else -> 0f
        }
    }
    val scale = minOf(1f, MAX_SIDE.toFloat() / maxOf(decoded.width, decoded.height))
    val matrix = Matrix().apply { postScale(scale, scale); postRotate(rotation) }
    val out = Bitmap.createBitmap(decoded, 0, 0, decoded.width, decoded.height, matrix, true)

    return ByteArrayOutputStream().use {
        out.compress(Bitmap.CompressFormat.JPEG, 90, it)
        it.toByteArray()
    }
}
