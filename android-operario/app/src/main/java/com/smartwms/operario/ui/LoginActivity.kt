// ui/LoginActivity.kt
// Pantalla de Login — Soporta Autenticación Multifactor (TOTP), Enrolamiento y Recuperación

package com.smartwms.operario.ui

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.os.Bundle
import android.text.InputFilter
import android.text.InputType
import android.view.View
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.smartwms.operario.data.api.MfaActivateRequest
import com.smartwms.operario.data.api.MfaRecoverRequest
import com.smartwms.operario.data.api.MfaVerifyRequest
import com.smartwms.operario.data.api.RetrofitClient
import com.smartwms.operario.data.local.TokenStore
import com.smartwms.operario.databinding.ActivityLoginBinding
import kotlinx.coroutines.launch

class LoginActivity : AppCompatActivity() {

    private lateinit var binding: ActivityLoginBinding
    private lateinit var tokenStore: TokenStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)

        tokenStore = TokenStore(applicationContext)
        RetrofitClient.init(applicationContext)

        // Si ya hay sesión activa, ir directo a MainActivity
        lifecycleScope.launch {
            if (tokenStore.getToken() != null) {
                goToMain()
            }
        }

        binding.btnServerConfig.setOnClickListener {
            showServerConfigDialog()
        }

        binding.btnLogin.setOnClickListener {
            val email    = binding.etEmail.text.toString().trim()
            val password = binding.etPassword.text.toString()

            if (email.isEmpty() || password.isEmpty()) {
                Toast.makeText(this, "Completa email y contraseña", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            doLogin(email, password)
        }
    }

    private fun showServerConfigDialog() {
        val currentUrl = RetrofitClient.getServerAddress(this)
        val input = EditText(this).apply {
            setText(currentUrl)
            hint = "http://192.168.1.5:8001"
            setPadding(48, 32, 48, 32)
        }

        AlertDialog.Builder(this)
            .setTitle("Dirección del Servidor")
            .setMessage("Ingresa la URL o IP del servidor SmartWMS (Backend puerto 8001):")
            .setView(input)
            .setPositiveButton("Guardar") { _, _ ->
                val newUrl = input.text.toString().trim()
                if (newUrl.isNotEmpty()) {
                    val prefs = getSharedPreferences("smartwms_network", MODE_PRIVATE)
                    prefs.edit().putString("server_url", newUrl).apply()
                    RetrofitClient.setServerAddress(newUrl)
                    Toast.makeText(this, "Servidor configurado: $newUrl", Toast.LENGTH_SHORT).show()
                }
            }
            .setNegativeButton("Cancelar", null)
            .show()
    }

    private fun doLogin(email: String, password: String) {
        binding.progressBar.visibility = View.VISIBLE
        binding.btnLogin.isEnabled = false

        lifecycleScope.launch {
            try {
                val response = RetrofitClient.apiService.login(email, password)
                if (response.isSuccessful) {
                    val body = response.body()!!
                    if (body.mfaRequired && !body.mfaToken.isNullOrEmpty()) {
                        // Flujo MFA: se requiere segundo factor
                        if (body.stage == "setup") {
                            showMfaSetupDialog(email, body.mfaToken)
                        } else {
                            showMfaVerifyDialog(email, body.mfaToken)
                        }
                    } else if (!body.accessToken.isNullOrEmpty()) {
                        // Acceso directo
                        tokenStore.saveCredentials(body.accessToken, body.role, email)
                        goToMain()
                    }
                } else {
                    val msg = when (response.code()) {
                        401  -> "Credenciales incorrectas"
                        403  -> "Cuenta desactivada"
                        423  -> "Cuenta bloqueada temporalmente por intentos fallidos"
                        else -> "Error ${response.code()}"
                    }
                    Toast.makeText(this@LoginActivity, msg, Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                Toast.makeText(this@LoginActivity,
                    "Error de conexión: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                binding.progressBar.visibility = View.GONE
                binding.btnLogin.isEnabled = true
            }
        }
    }

    // ─── Diálogo de Verificación TOTP (Paso 2) ────────────────────────────────

    private fun showMfaVerifyDialog(email: String, mfaToken: String) {
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(50, 20, 50, 10)
        }

        val txtDesc = TextView(this).apply {
            text = "Ingresa el código de 6 dígitos de tu app autenticadora (Google Authenticator, Microsoft o Aegis):"
            textSize = 14f
            setPadding(0, 0, 0, 24)
        }
        layout.addView(txtDesc)

        val inputCode = EditText(this).apply {
            hint = "123456"
            inputType = InputType.TYPE_CLASS_NUMBER
            filters = arrayOf(InputFilter.LengthFilter(6))
            textSize = 22f
            textAlignment = View.TEXT_ALIGNMENT_CENTER
        }
        layout.addView(inputCode)

        val dialog = AlertDialog.Builder(this)
            .setTitle("Segundo Factor (MFA)")
            .setView(layout)
            .setCancelable(false)
            .setPositiveButton("Verificar", null)
            .setNeutralButton("Usar Código de Recuperación") { _, _ ->
                showMfaRecoverDialog(email, mfaToken)
            }
            .setNegativeButton("Cancelar", null)
            .create()

        dialog.setOnShowListener {
            val btn = dialog.getButton(AlertDialog.BUTTON_POSITIVE)
            btn.setOnClickListener {
                val code = inputCode.text.toString().trim()
                if (code.length != 6) {
                    Toast.makeText(this, "El código debe tener 6 dígitos", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }

                lifecycleScope.launch {
                    try {
                        val resp = RetrofitClient.apiService.mfaVerify(MfaVerifyRequest(code, mfaToken))
                        if (resp.isSuccessful) {
                            val auth = resp.body()!!
                            tokenStore.saveCredentials(auth.accessToken!!, auth.role, email)
                            dialog.dismiss()
                            Toast.makeText(this@LoginActivity, "¡Autenticación exitosa!", Toast.LENGTH_SHORT).show()
                            goToMain()
                        } else {
                            val err = if (resp.code() == 423) {
                                "Cuenta bloqueada temporalmente por intentos fallidos."
                            } else {
                                "Código incorrecto o expirado."
                            }
                            Toast.makeText(this@LoginActivity, err, Toast.LENGTH_LONG).show()
                        }
                    } catch (e: Exception) {
                        Toast.makeText(this@LoginActivity, "Error: ${e.message}", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
        dialog.show()
    }

    // ─── Diálogo de Enrolamiento Inicial (Setup) ──────────────────────────────
    private fun showMfaSetupDialog(email: String, mfaToken: String) {
        MfaDialogHelper.showMfaSetupDialog(
            activity = this,
            token = mfaToken,
            isPendingToken = true
        ) { newAccessToken ->
            lifecycleScope.launch {
                tokenStore.saveCredentials(newAccessToken, "operario", email)
                goToMain()
            }
        }
    }

    // ─── Diálogo de Recuperación de Emergencia ────────────────────────────────

    private fun showMfaRecoverDialog(email: String, mfaToken: String) {
        val layout = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(50, 20, 50, 10)
        }

        val txtDesc = TextView(this).apply {
            text = "Ingresa uno de tus códigos de recuperación de 10 caracteres (formato: ABCDE-12345):"
            textSize = 14f
            setPadding(0, 0, 0, 20)
        }
        layout.addView(txtDesc)

        val inputCode = EditText(this).apply {
            hint = "XXXXX-XXXXX"
            inputType = InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
            textSize = 18f
            textAlignment = View.TEXT_ALIGNMENT_CENTER
        }
        layout.addView(inputCode)

        val dialog = AlertDialog.Builder(this)
            .setTitle("Código de Recuperación")
            .setView(layout)
            .setPositiveButton("Acceder", null)
            .setNegativeButton("Volver") { _, _ ->
                showMfaVerifyDialog(email, mfaToken)
            }
            .create()

        dialog.setOnShowListener {
            val btn = dialog.getButton(AlertDialog.BUTTON_POSITIVE)
            btn.setOnClickListener {
                val code = inputCode.text.toString().trim()
                if (code.isEmpty()) {
                    Toast.makeText(this, "Ingresa el código de recuperación", Toast.LENGTH_SHORT).show()
                    return@setOnClickListener
                }

                lifecycleScope.launch {
                    try {
                        val resp = RetrofitClient.apiService.mfaRecover(MfaRecoverRequest(code, mfaToken))
                        if (resp.isSuccessful) {
                            val auth = resp.body()!!
                            tokenStore.saveCredentials(auth.accessToken!!, auth.role, email)
                            dialog.dismiss()
                            Toast.makeText(this@LoginActivity, "Acceso concedido por código de emergencia", Toast.LENGTH_LONG).show()
                            goToMain()
                        } else {
                            Toast.makeText(this@LoginActivity, "Código de recuperación inválido o ya usado", Toast.LENGTH_LONG).show()
                        }
                    } catch (e: Exception) {
                        Toast.makeText(this@LoginActivity, "Error: ${e.message}", Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
        dialog.show()
    }

    private fun copyToClipboard(label: String, text: String) {
        val clipboard = getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
        val clip = ClipData.newPlainText(label, text)
        clipboard.setPrimaryClip(clip)
    }

    private fun goToMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }
}
