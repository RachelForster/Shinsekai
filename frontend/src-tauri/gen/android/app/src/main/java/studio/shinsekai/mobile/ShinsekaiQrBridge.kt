package studio.shinsekai.mobile

import android.graphics.BitmapFactory
import android.util.Base64
import android.webkit.JavascriptInterface
import com.google.zxing.BarcodeFormat
import com.google.zxing.BinaryBitmap
import com.google.zxing.DecodeHintType
import com.google.zxing.RGBLuminanceSource
import com.google.zxing.common.GlobalHistogramBinarizer
import com.google.zxing.common.HybridBinarizer
import com.google.zxing.qrcode.QRCodeReader

class ShinsekaiQrBridge {
  @JavascriptInterface
  fun decodeImageDataUrl(dataUrl: String): String {
    return try {
      val cleanBase64 = dataUrl.substringAfter("base64,", dataUrl).trim()
      if (cleanBase64.isBlank()) {
        return ""
      }
      val bytes = Base64.decode(cleanBase64, Base64.DEFAULT)
      val bitmap = BitmapFactory.decodeByteArray(bytes, 0, bytes.size) ?: return ""
      val width = bitmap.width
      val height = bitmap.height
      if (width <= 0 || height <= 0) {
        bitmap.recycle()
        return ""
      }
      val pixels = IntArray(width * height)
      bitmap.getPixels(pixels, 0, width, 0, 0, width, height)
      bitmap.recycle()

      val source = RGBLuminanceSource(width, height, pixels)
      val hints = mapOf(
        DecodeHintType.POSSIBLE_FORMATS to listOf(BarcodeFormat.QR_CODE),
        DecodeHintType.TRY_HARDER to true,
        DecodeHintType.CHARACTER_SET to "UTF-8",
      )
      val candidates = listOf(
        BinaryBitmap(HybridBinarizer(source)),
        BinaryBitmap(GlobalHistogramBinarizer(source)),
        BinaryBitmap(HybridBinarizer(source.invert())),
      )
      val reader = QRCodeReader()
      for (candidate in candidates) {
        try {
          val result = reader.decode(candidate, hints)
          if (!result.text.isNullOrBlank()) {
            return result.text
          }
        } catch (_: Throwable) {
          // Try next binarizer candidate
        } finally {
          reader.reset()
        }
      }
      ""
    } catch (_: Throwable) {
      ""
    }
  }
}
