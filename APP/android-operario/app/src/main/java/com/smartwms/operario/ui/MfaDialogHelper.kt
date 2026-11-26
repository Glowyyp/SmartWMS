// ui/MfaDialogHelper.kt
// Helper para el flujo de configuración, vinculación automática por Intent,
// renderizado de código QR y activación de Autenticación Multifactor (MFA / TOTP)

package com.smartwms.operario.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.view.LayoutInflater
import android.view.View
import android.widget.EditText
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.google.android.material.button.MaterialButton
import com.google.zxing.BarcodeFormat
import com.journeyapps.barcodescanner.BarcodeEncoder
import com.smartwms.operario.R
import com.smartwms.operario.data.api.MfaActivateRequest
import com.smartwms.operario.data.api.RetrofitClient
import kotlinx.coroutines.launch

object MfaDialogHelper {

    /**
     * Muestra el diálogo completo para vincular y activar MFA.
     *
     * @param activity Actividad que invoca el diálogo (AppCompatActivity)
     * @param token Token de autorización (accessToken si ya está autenticado, o mfaToken si es paso 1 de login)
     * @param isPendingToken true si se utiliza durante el login con mfaToken; false si se hace desde dentro de la sesión
     * @param onActivated Callback invocado cuando la activación se confirma en el backend con el nuevo accessToken
     */
    fun showMfaSetupDialog(
        activity: AppCompatActivity,
        token: String,
        isPendingToken: Boolean,
        onActivated: (newAccessToken: String) -> Unit
    ) {
        val progressDialog = AlertDialog.Builder(activity)
            .setTitle("Generando vinculación MFA")
            .setMessage("Por favor espera...")
            .setCancelable(false)
            .create()

        progressDialog.show()

        activity.lifecycleScope.launch {
            try {
                val setupResp = RetrofitClient.apiService.mfaSetup("Bearer $token")
                progressDialog.dismiss()

                if (!setupResp.isSuccessful || setupResp.body() == null) {
                    Toast.makeText(activity, "Error al generar vinculación MFA: ${setupResp.code()}", Toast.LENGTH_LONG).show()
                    return@launch
                }

                val data = setupResp.body()!!

                // Generar bitmap QR con ZXing BarcodeEncoder
                val barcodeEncoder = BarcodeEncoder()
                val qrBitmap = barcodeEncoder.encodeBitmap(
                    data.provisioningUri,
                    BarcodeFormat.QR_CODE,
                    500,
                    500
                )

                // Inflar vista personalizada
                val dialogView = LayoutInflater.from(activity).inflate(R.layout.dialog_mfa_setup, null)

                val tvAccount         = dialogView.findViewById<TextView>(R.id.tv_mfa_account)
                val btnOpenAuth       = dialogView.findViewById<MaterialButton>(R.id.btn_open_authenticator)
                val ivQr              = dialogView.findViewById<ImageView>(R.id.iv_mfa_qr)
                val tvSecret          = dialogView.findViewById<TextView>(R.id.tv_mfa_secret)
                val btnCopySecret     = dialogView.findViewById<MaterialButton>(R.id.btn_copy_secret)
                val etCode            = dialogView.findViewById<EditText>(R.id.et_mfa_code)
                val tvError           = dialogView.findViewById<TextView>(R.id.tv_mfa_error)
                val pbLoading         = dialogView.findViewById<ProgressBar>(R.id.pb_mfa_loading)
                val btnActivate       = dialogView.findViewById<MaterialButton>(R.id.btn_activate_mfa)
                val btnCancel         = dialogView.findViewById<MaterialButton>(R.id.btn_cancel_mfa)

                tvAccount.text = "Cuenta: ${data.accountName}"
                ivQr.setImageBitmap(qrBitmap)
                tvSecret.text = data.secret

                val setupDialog = AlertDialog.Builder(activity)
                    .setView(dialogView)
                    .setCancelable(false)
                    .create()

                // Botón 1: Abrir directamente la app autenticadora vía Intent con otpauth://
                btnOpenAuth.setOnClickListener {
                    try {
                        val intent = Intent(Intent.ACTION_VIEW, Uri.parse(data.provisioningUri))
                        activity.startActivity(intent)
                    } catch (e: Exception) {
                        Toast.makeText(
                            activity,
                            "No se encontró una aplicación de autenticación compatible (Google Authenticator, Aegis o Microsoft). Escanea el código QR o copia la clave.",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }

                // Botón 2: Copiar clave secreta manual al portapapeles
                btnCopySecret.setOnClickListener {
                    val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    val clip = ClipData.newPlainText("Clave MFA SmartWMS", data.secret)
                    clipboard.setPrimaryClip(clip)
                    Toast.makeText(activity, "Clave copiada al portapapeles", Toast.LENGTH_SHORT).show()
                }

                btnCancel.setOnClickListener {
                    setupDialog.dismiss()
                }

                // Botón 3: Validar código de 6 dígitos y activar MFA
                btnActivate.setOnClickListener {
                    val code = etCode.text.toString().trim()
                    if (code.length != 6) {
                        tvError.text = "El código debe tener exactamente 6 dígitos."
                        tvError.visibility = View.VISIBLE
                        return@setOnClickListener
                    }

                    tvError.visibility = View.GONE
                    pbLoading.visibility = View.VISIBLE
                    btnActivate.isEnabled = false

                    activity.lifecycleScope.launch {
                        try {
                            val actResp = if (isPendingToken) {
                                RetrofitClient.apiService.mfaActivate(
                                    MfaActivateRequest(code = code, mfaToken = token)
                                )
                            } else {
                                RetrofitClient.apiService.mfaActivate(
                                    MfaActivateRequest(code = code),
                                    token = "Bearer $token"
                                )
                            }

                            if (actResp.isSuccessful && actResp.body()?.accessToken != null) {
                                val newAccessToken = actResp.body()!!.accessToken!!
                                setupDialog.dismiss()
                                Toast.makeText(activity, "¡Autenticación MFA activada con éxito!", Toast.LENGTH_LONG).show()

                                // Notificar callback
                                onActivated(newAccessToken)

                                // Mostrar diálogo de entrega de códigos de emergencia
                                showRecoveryCodesDialog(activity, data.recoveryCodes)
                            } else {
                                pbLoading.visibility = View.GONE
                                btnActivate.isEnabled = true
                                etCode.text.clear()
                                val msg = if (actResp.code() == 423) {
                                    "Cuenta bloqueada temporalmente por intentos fallidos."
                                } else {
                                    "Código incorrecto o expirado. Verifica la hora de tu dispositivo e inténtalo de nuevo."
                                }
                                tvError.text = msg
                                tvError.visibility = View.VISIBLE
                                Toast.makeText(activity, msg, Toast.LENGTH_LONG).show()
                            }
                        } catch (e: Exception) {
                            pbLoading.visibility = View.GONE
                            btnActivate.isEnabled = true
                            tvError.text = "Error de conexión: ${e.message}"
                            tvError.visibility = View.VISIBLE
                        }
                    }
                }

                setupDialog.show()

            } catch (e: Exception) {
                progressDialog.dismiss()
                Toast.makeText(activity, "Error al iniciar configuración MFA: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }

    /**
     * Muestra los 10 códigos de recuperación para respaldo del operario.
     */
    fun showRecoveryCodesDialog(activity: AppCompatActivity, recoveryCodes: List<String>) {
        val dialogView = LayoutInflater.from(activity).inflate(R.layout.dialog_mfa_recovery_codes, null)
        val tvCodesList = dialogView.findViewById<TextView>(R.id.tv_recovery_codes_list)
        val btnCopyCodes = dialogView.findViewById<MaterialButton>(R.id.btn_copy_recovery_codes)
        val btnFinish = dialogView.findViewById<MaterialButton>(R.id.btn_finish_recovery)

        val formattedText = recoveryCodes.mapIndexed { index, code ->
            "${(index + 1).toString().padStart(2, ' ')}. $code"
        }.joinToString("\n")

        tvCodesList.text = formattedText

        val dialog = AlertDialog.Builder(activity)
            .setView(dialogView)
            .setCancelable(false)
            .create()

        btnCopyCodes.setOnClickListener {
            val clipboard = activity.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            val clip = ClipData.newPlainText("Códigos Recuperación SmartWMS", formattedText)
            clipboard.setPrimaryClip(clip)
            Toast.makeText(activity, "Códigos de recuperación copiados al portapapeles", Toast.LENGTH_SHORT).show()
        }

        btnFinish.setOnClickListener {
            dialog.dismiss()
        }

        dialog.show()
    }
}
