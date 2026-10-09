// ui/LoginActivity.kt
// Pantalla de Login — Llama a POST /api/auth/login y guarda el JWT

package com.smartwms.operario.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
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

        // Si ya hay sesion activa, ir directo a MainActivity
        lifecycleScope.launch {
            if (tokenStore.getToken() != null) {
                goToMain()
            }
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

    private fun doLogin(email: String, password: String) {
        binding.progressBar.visibility = View.VISIBLE
        binding.btnLogin.isEnabled = false

        lifecycleScope.launch {
            try {
                val response = RetrofitClient.apiService.login(email, password)
                if (response.isSuccessful) {
                    val body = response.body()!!
                    tokenStore.saveCredentials(body.accessToken, body.role, email)
                    goToMain()
                } else {
                    val msg = when (response.code()) {
                        401  -> "Credenciales incorrectas"
                        403  -> "Cuenta desactivada"
                        else -> "Error ${response.code()}"
                    }
                    Toast.makeText(this@LoginActivity, msg, Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                Toast.makeText(this@LoginActivity,
                    "Error de conexion: ${e.message}", Toast.LENGTH_LONG).show()
            } finally {
                binding.progressBar.visibility = View.GONE
                binding.btnLogin.isEnabled = true
            }
        }
    }

    private fun goToMain() {
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }
}
