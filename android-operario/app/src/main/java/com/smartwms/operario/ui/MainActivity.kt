// ui/MainActivity.kt
// Actividad principal con Bottom Navigation (Inicio / Picking / Putaway / Historial / Copiloto IA)

package com.smartwms.operario.ui

import android.content.Intent
import android.os.Bundle
import android.view.Menu
import android.view.MenuItem
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import androidx.navigation.fragment.NavHostFragment
import androidx.navigation.ui.AppBarConfiguration
import androidx.navigation.ui.setupActionBarWithNavController
import androidx.navigation.ui.setupWithNavController
import com.smartwms.operario.R
import com.smartwms.operario.data.local.TokenStore
import com.smartwms.operario.databinding.ActivityMainBinding
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var tokenStore: TokenStore

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        tokenStore = TokenStore(applicationContext)

        // Configurar Navigation Component + Bottom Navigation
        val navHostFragment = supportFragmentManager
            .findFragmentById(R.id.nav_host_fragment) as NavHostFragment
        val navController = navHostFragment.navController

        // 5 tabs top-level — ninguno muestra el botón "Up" (←)
        val appBarConfig = AppBarConfiguration(
            setOf(
                R.id.homeFragment,
                R.id.pickingFragment,
                R.id.putawayFragment,
                R.id.historialFragment,
                R.id.chatFragment
            )
        )
        setupActionBarWithNavController(navController, appBarConfig)
        binding.bottomNavigation.setupWithNavController(navController)

        // Mostrar nombre y rol del usuario en el ActionBar
        loadUserInfoInActionBar()
    }

    private fun loadUserInfoInActionBar() {
        lifecycleScope.launch {
            val tokenStore = TokenStore(applicationContext)
            val email = tokenStore.getEmail() ?: "Operario"
            val role  = tokenStore.getRole()  ?: "operario"

            val displayName = formatDisplayName(email)
            val roleLabel   = formatRole(role)

            // Título = nombre del operario, subtítulo = rol
            supportActionBar?.title    = displayName
            supportActionBar?.subtitle = roleLabel
        }
    }

    private fun formatDisplayName(email: String): String {
        val local = email.substringBefore("@")
        return local.split(Regex("[._-]"))
            .joinToString(" ") { it.replaceFirstChar { c -> c.uppercase() } }
    }

    private fun formatRole(role: String) = when (role) {
        "admin"      -> "Administrador"
        "supervisor" -> "Supervisor de Bodega"
        "operario"   -> "Operario de Picking"
        else          -> role.replaceFirstChar { it.uppercase() }
    }

    override fun onCreateOptionsMenu(menu: Menu): Boolean {
        menuInflater.inflate(R.menu.main_menu, menu)
        return true
    }

    override fun onOptionsItemSelected(item: MenuItem): Boolean {
        return when (item.itemId) {
            R.id.action_mfa -> {
                lifecycleScope.launch {
                    val token = tokenStore.getToken()
                    if (token != null) {
                        MfaDialogHelper.showMfaSetupDialog(
                            activity = this@MainActivity,
                            token = token,
                            isPendingToken = false
                        ) { newToken ->
                            lifecycleScope.launch {
                                val email = tokenStore.getEmail() ?: "operario"
                                val role  = tokenStore.getRole() ?: "operario"
                                tokenStore.saveCredentials(newToken, role, email)
                            }
                        }
                    }
                }
                true
            }
            R.id.action_logout -> {
                lifecycleScope.launch {
                    tokenStore.clear()
                    startActivity(Intent(this@MainActivity, LoginActivity::class.java))
                    finish()
                }
                true
            }
            else -> super.onOptionsItemSelected(item)
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        val navHostFragment = supportFragmentManager.findFragmentById(R.id.nav_host_fragment) as NavHostFragment
        return navHostFragment.navController.navigateUp() || navHostFragment.navController.popBackStack() || super.onSupportNavigateUp()
    }
}
