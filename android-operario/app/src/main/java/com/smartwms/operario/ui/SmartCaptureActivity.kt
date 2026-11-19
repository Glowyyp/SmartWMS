package com.smartwms.operario.ui

import android.os.Bundle
import com.google.zxing.BarcodeFormat
import com.google.zxing.DecodeHintType
import com.google.zxing.client.android.Intents
import com.journeyapps.barcodescanner.CaptureActivity
import com.journeyapps.barcodescanner.DecoratedBarcodeView
import com.journeyapps.barcodescanner.DefaultDecoderFactory
import com.journeyapps.barcodescanner.ScanOptions

/**
 * Actividad de escáner configurada para leer tanto códigos QR como códigos de barras 1D
 * (Code 128, Code 39, EAN-13, UPC, etc.), incluyendo pantallas con brillo o contraste invertido.
 */
class SmartCaptureActivity : CaptureActivity() {

    private var scannerView: DecoratedBarcodeView? = null

    override fun initializeContent(): DecoratedBarcodeView {
        val view = super.initializeContent()
        scannerView = view
        return view
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val formats = listOf(
            BarcodeFormat.QR_CODE,
            BarcodeFormat.CODE_128,
            BarcodeFormat.CODE_39,
            BarcodeFormat.CODE_93,
            BarcodeFormat.EAN_13,
            BarcodeFormat.EAN_8,
            BarcodeFormat.UPC_A,
            BarcodeFormat.UPC_E,
            BarcodeFormat.ITF,
            BarcodeFormat.DATA_MATRIX
        )
        val hints = mapOf<DecodeHintType, Any>(
            DecodeHintType.TRY_HARDER to java.lang.Boolean.TRUE
        )
        scannerView?.setDecoderFactory(
            DefaultDecoderFactory(formats, hints, null, Intents.Scan.MIXED_SCAN)
        )
    }

    companion object {
        fun buildScanOptions(prompt: String): ScanOptions {
            return ScanOptions().apply {
                setCaptureActivity(SmartCaptureActivity::class.java)
                setDesiredBarcodeFormats(ScanOptions.ALL_CODE_TYPES)
                setPrompt(prompt)
                setCameraId(0)
                setBeepEnabled(true)
                setBarcodeImageEnabled(false)
                setOrientationLocked(false)
                addExtra(Intents.Scan.SCAN_TYPE, Intents.Scan.MIXED_SCAN)
            }
        }
    }
}
