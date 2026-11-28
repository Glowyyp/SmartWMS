// ui/fragments/HomeFragment.kt
// Dashboard principal del Operario: saludo dinámico, orden activa, acciones rápidas e historial de hoy.

package com.smartwms.operario.ui.fragments

import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.fragment.app.activityViewModels
import androidx.navigation.fragment.findNavController
import com.smartwms.operario.R
import com.smartwms.operario.data.api.WorkOrder
import com.smartwms.operario.data.local.TokenStore
import com.smartwms.operario.databinding.FragmentHomeBinding
import com.smartwms.operario.ui.OrderViewModel
import java.text.SimpleDateFormat
import java.util.*
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch

class HomeFragment : Fragment() {

    private var _binding: FragmentHomeBinding? = null
    private val binding get() = _binding!!

    private val orderVm: OrderViewModel by activityViewModels()
    private lateinit var tokenStore: TokenStore

    // Timer para actualizar el tiempo de la orden activa en tiempo real
    private val timerHandler = Handler(Looper.getMainLooper())
    private var timerRunnable: Runnable? = null
    private var orderStartTime: Long = System.currentTimeMillis()

    // Estado local del picking (ítems recogidos de la orden activa)
    private var pickedCount: Int = 0

    override fun onCreateView(
        inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?
    ): View {
        _binding = FragmentHomeBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        tokenStore = TokenStore(requireContext())

        setupGreeting()
        setupUserInfo()
        setupQuickActions()
        observeViewModel()
    }

    // ── SALUDO DINÁMICO Y FECHA ────────────────────────────────────────────────

    private fun setupGreeting() {
        val hour = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)
        val greeting = when {
            hour < 12 -> "Buenos días,"
            hour < 19 -> "Buenas tardes,"
            else       -> "Buenas noches,"
        }
        binding.tvGreeting.text = greeting

        // Fecha completa en español
        val sdf = SimpleDateFormat("EEEE, d 'de' MMMM 'de' yyyy", Locale("es", "ES"))
        val dateStr = sdf.format(Date()).replaceFirstChar { it.uppercase() }

        // Turno según hora
        val shift = when {
            hour in 6..13  -> "Mañana"
            hour in 14..21 -> "Tarde"
            else            -> "Noche"
        }
        binding.tvDateShift.text = "$dateStr  ·  Turno: $shift"
    }

    private fun setupUserInfo() {
        // Usar el email guardado sincrónicamente para las iniciales
        // El nombre completo se actualiza desde el ViewModel si está disponible
        val displayEmail = orderVm.currentUserEmail
        val displayName = formatDisplayName(displayEmail)
        val initials = getInitials(displayName)

        binding.tvUserName.text = displayName
        binding.tvAvatar.text = initials
        binding.tvRoleLabel.text = formatRole(orderVm.currentUserRole)
    }

    // ── ACCIONES RÁPIDAS ──────────────────────────────────────────────────────

    private fun setupQuickActions() {
        // Picking guiado → navega al tab Picking y selecciona el pedido activo
        binding.btnQuickPicking.setOnClickListener {
            val activeOrder = orderVm.selectedOrder.value
            if (activeOrder != null) {
                // Ya hay pedido seleccionado, ir directamente a Picking
                findNavController().navigate(R.id.pickingFragment)
            } else {
                // No hay pedido activo, ir a Picking para seleccionar uno
                findNavController().navigate(R.id.pickingFragment)
            }
        }

        // Putaway / Ingreso
        binding.btnQuickPutaway.setOnClickListener {
            findNavController().navigate(R.id.putawayFragment)
        }

        // Cerrar pedido → va a Packing (verificación y cierre)
        binding.btnQuickClose.setOnClickListener {
            findNavController().navigate(R.id.packingFragment)
        }

        // Consultar con IA → tab Chat
        binding.btnQuickAi.setOnClickListener {
            findNavController().navigate(R.id.chatFragment)
        }

        // Botón "Continuar Picking" o "Cerrar pedido" en la tarjeta de orden activa
        binding.btnContinuePicking.setOnClickListener {
            if (orderVm.isPickingComplete()) {
                findNavController().navigate(R.id.packingFragment)
            } else {
                findNavController().navigate(R.id.pickingFragment)
            }
        }
    }

    // ── OBSERVADORES ─────────────────────────────────────────────────────────

    private fun observeViewModel() {
        // Actualizar nombre cuando el ViewModel tenga el email cargado
        orderVm.workOrders.observe(viewLifecycleOwner) { orders ->
            // Refrescar info de usuario (ya disponible)
            val email = orderVm.currentUserEmail
            val name = formatDisplayName(email)
            binding.tvUserName.text = name
            binding.tvAvatar.text = getInitials(name)
            binding.tvRoleLabel.text = formatRole(orderVm.currentUserRole)

            // Historial de hoy: pedidos completados HOY (dispatched)
            renderTodayHistory(orders)
        }

        // Pedido activo seleccionado
        orderVm.selectedOrder.observe(viewLifecycleOwner) { order ->
            renderActiveOrder(order)
        }
        
        // Conteo de picking
        orderVm.pickedSkus.observe(viewLifecycleOwner) { skus ->
            pickedCount = skus.size
            // Re-renderizar progreso
            orderVm.selectedOrder.value?.let { renderActiveOrder(it) }
        }
    }

    // ── ORDEN ACTIVA ──────────────────────────────────────────────────────────

    private fun renderActiveOrder(order: WorkOrder?) {
        if (order == null || order.status != "pending") {
            binding.layoutNoActiveOrder.visibility = View.VISIBLE
            binding.layoutActiveOrder.visibility = View.GONE
            stopActiveTimer()
        } else {
            binding.layoutNoActiveOrder.visibility = View.GONE
            binding.layoutActiveOrder.visibility = View.VISIBLE

            binding.tvActiveOrderId.text = order.orderNumber
            binding.tvActiveOrderName.text = "Pedido: ${order.assignedOperarioEmail ?: order.createdByEmail ?: "—"}"
            val totalItems = order.items.sumOf { it.quantity }
            val pickedMap = orderVm.pickedSkus.value ?: emptyMap()
            var currentTotalPicked = 0
            order.items.forEach { 
                currentTotalPicked += Math.min(it.quantity, pickedMap[it.sku] ?: 0)
            }

            binding.tvActiveTotal.text = totalItems.toString()
            binding.tvActiveProgress.text = "$currentTotalPicked/$totalItems"

            val pct = if (totalItems > 0)
                (currentTotalPicked * 100) / totalItems else 0
            binding.progressActiveOrder.progress = pct

            if (orderVm.isPickingComplete()) {
                binding.btnContinuePicking.text = "Cerrar pedido"
            } else {
                binding.btnContinuePicking.text = "Continuar Picking"
            }

            startActiveTimer()
        }
    }

    // ── TIMER ACTIVO ─────────────────────────────────────────────────────────

    private fun startActiveTimer() {
        stopActiveTimer()
        
        viewLifecycleOwner.lifecycleScope.launch {
            var startTime = tokenStore.getActiveOrderStartTime()
            if (startTime == null) {
                startTime = System.currentTimeMillis()
                tokenStore.saveActiveOrderId(orderVm.selectedOrder.value?.id, startTime)
            }
            orderStartTime = startTime

            timerRunnable = object : Runnable {
                override fun run() {
                    if (_binding == null) return // Evitar NPE si la vista ya fue destruida
                    
                    var elapsed = System.currentTimeMillis() - orderStartTime
                    if (elapsed < 0) elapsed = 0 // Evitar valores negativos
                    
                    val minutes = (elapsed / 60000).toInt()
                    val seconds = ((elapsed % 60000) / 1000).toInt()
                    binding.tvActiveTimer.text = String.format("%02d:%02d", minutes, seconds)
                    timerHandler.postDelayed(this, 1000)
                }
            }
            timerHandler.post(timerRunnable!!)
        }
    }

    private fun stopActiveTimer() {
        timerHandler.removeCallbacksAndMessages(null)
        timerRunnable?.let { timerHandler.removeCallbacks(it) }
        timerRunnable = null
    }

    // ── HISTORIAL DE HOY ─────────────────────────────────────────────────────

    private fun renderTodayHistory(allOrders: List<WorkOrder>) {
        binding.llTodayOrders.removeAllViews()

        // Filtrar pedidos de HOY (usando created_at)
        val todayOrders = allOrders.filter { order ->
            isToday(order.createdAt)
        }

        if (todayOrders.isEmpty()) {
            binding.layoutNoHistory.visibility = View.VISIBLE
            binding.tvTodayCount.text = "0 completados"
            return
        }

        binding.layoutNoHistory.visibility = View.GONE
        val completed = todayOrders.count { it.status == "dispatched" }
        binding.tvTodayCount.text = "$completed completados"

        todayOrders.forEach { order ->
            val itemView = layoutInflater.inflate(
                R.layout.item_today_order,
                binding.llTodayOrders,
                false
            )

            val tvOrderId    = itemView.findViewById<TextView>(R.id.tv_history_order_id)
            val tvStatus     = itemView.findViewById<TextView>(R.id.tv_history_status)
            val tvProducts   = itemView.findViewById<TextView>(R.id.tv_history_products)
            val tvTimeRange  = itemView.findViewById<TextView>(R.id.tv_history_time_range)
            val tvDuration   = itemView.findViewById<TextView>(R.id.tv_history_duration)
            val statusBar    = itemView.findViewById<View>(R.id.view_status_bar)

            tvOrderId.text = order.orderNumber
            tvProducts.text = "${order.items.size} productos"

            when (order.status) {
                "dispatched" -> {
                    tvStatus.text = "✓ Completado"
                    tvStatus.setTextColor(0xFF4ade80.toInt())
                    statusBar.setBackgroundColor(0xFF4ade80.toInt())
                    val startTime = formatTime(order.createdAt)
                    val endTime   = formatTime(order.dispatchedAt ?: order.createdAt)
                    tvTimeRange.text = "$startTime → $endTime"
                    tvDuration.text  = calcDuration(order.createdAt, order.dispatchedAt)
                }
                "cancelled"  -> {
                    tvStatus.text = "✗ Cancelado"
                    tvStatus.setTextColor(0xFFf87171.toInt())
                    statusBar.setBackgroundColor(0xFFf87171.toInt())
                    tvTimeRange.text = formatTime(order.createdAt)
                    tvDuration.text  = "—"
                }
                else -> {
                    tvStatus.text = "● En progreso"
                    tvStatus.setTextColor(0xFFfbbf24.toInt())
                    statusBar.setBackgroundColor(0xFFfbbf24.toInt())
                    tvTimeRange.text = formatTime(order.createdAt)
                    tvDuration.text  = "activo"
                }
            }

            binding.llTodayOrders.addView(itemView)
        }
    }

    // ── HELPERS ──────────────────────────────────────────────────────────────

    private fun formatDisplayName(email: String?): String {
        if (email.isNullOrBlank()) return "Operario"
        val local = email.substringBefore("@")
        return local.split(Regex("[._-]"))
            .joinToString(" ") { it.replaceFirstChar { c -> c.uppercase() } }
    }

    private fun getInitials(name: String): String {
        val parts = name.trim().split(" ")
        return when {
            parts.size >= 2 -> "${parts[0].first()}${parts[1].first()}".uppercase()
            parts.isNotEmpty() -> parts[0].take(2).uppercase()
            else -> "OP"
        }
    }

    private fun formatRole(role: String?): String = when (role) {
        "admin"      -> "Administrador"
        "supervisor" -> "Supervisor de Bodega"
        "operario"   -> "Operario de Picking"
        else          -> "Operario"
    }

    private fun isToday(dateStr: String): Boolean {
        return try {
            val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
            val date = sdf.parse(dateStr.take(19)) ?: return false
            val cal = Calendar.getInstance()
            val today = Calendar.getInstance()
            cal.time = date
            cal.get(Calendar.DAY_OF_YEAR) == today.get(Calendar.DAY_OF_YEAR) &&
            cal.get(Calendar.YEAR) == today.get(Calendar.YEAR)
        } catch (e: Exception) { false }
    }

    private fun formatTime(dateStr: String?): String {
        if (dateStr == null) return "—"
        return try {
            val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
            val date = sdf.parse(dateStr.take(19)) ?: return "—"
            SimpleDateFormat("HH:mm", Locale.getDefault()).format(date)
        } catch (e: Exception) { "—" }
    }

    private fun calcDuration(start: String, end: String?): String {
        if (end == null) return "—"
        return try {
            val sdf = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.getDefault())
            val s = sdf.parse(start.take(19))?.time ?: return "—"
            val e = sdf.parse(end.take(19))?.time ?: return "—"
            val mins = ((e - s) / 60000).toInt()
            when {
                mins < 1   -> "< 1 min"
                mins < 60  -> "$mins min"
                else        -> "${mins / 60}h ${mins % 60}min"
            }
        } catch (ex: Exception) { "—" }
    }



    override fun onResume() {
        super.onResume()
        // Refrescar datos al volver al tab Inicio
        orderVm.loadPendingOrders()
        setupGreeting()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        stopActiveTimer()
        _binding = null
    }
}
