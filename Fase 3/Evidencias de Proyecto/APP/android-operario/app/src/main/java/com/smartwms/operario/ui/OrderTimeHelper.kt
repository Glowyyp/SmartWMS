package com.smartwms.operario.ui

import com.smartwms.operario.data.api.WorkOrder
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.util.Locale

/**
 * Utilidades de fecha/hora conscientes de zona horaria (UTC -> zona local del dispositivo).
 * Evita que pedidos completados en la noche (ej. 22:00 UTC-3 = 01:00 UTC del día siguiente)
 * queden fuera de "Pedidos de hoy".
 */
object OrderTimeHelper {

    private val timeFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("HH:mm", Locale.getDefault())
    private val dateTimeFormatter: DateTimeFormatter = DateTimeFormatter.ofPattern("dd/MM/yyyy HH:mm", Locale.getDefault())

    fun parseToZoned(dateStr: String?, zoneId: ZoneId = ZoneId.systemDefault()): ZonedDateTime? {
        val raw = dateStr?.trim().orEmpty()
        if (raw.isEmpty()) return null

        // 1. ISO-8601 con offset explícito (+00:00, -03:00, Z)
        try {
            return OffsetDateTime.parse(raw).atZoneSameInstant(zoneId)
        } catch (_: Exception) {
        }

        // 2. Instant UTC con sufijo Z
        try {
            return Instant.parse(raw).atZone(zoneId)
        } catch (_: Exception) {
        }

        // 3. Timestamp sin offset (SQLite / naive UTC): asumir UTC y convertir a zona local
        val normalized = raw.replace(' ', 'T').take(19)
        return try {
            LocalDateTime.parse(normalized)
                .atZone(ZoneOffset.UTC)
                .withZoneSameInstant(zoneId)
        } catch (_: Exception) {
            null
        }
    }

    fun isSameLocalDate(
        dateStr: String?,
        targetDate: LocalDate = LocalDate.now(),
        zoneId: ZoneId = ZoneId.systemDefault()
    ): Boolean {
        val zoned = parseToZoned(dateStr, zoneId) ?: return false
        return zoned.toLocalDate() == targetDate
    }

    /**
     * Un pedido corresponde a "Pedidos de hoy" si fue completado/despachado hoy,
     * cancelado hoy o creado hoy en la zona horaria local.
     */
    fun isOrderFromToday(
        order: WorkOrder,
        today: LocalDate = LocalDate.now(),
        zoneId: ZoneId = ZoneId.systemDefault()
    ): Boolean {
        return isSameLocalDate(order.dispatchedAt, today, zoneId) ||
            isSameLocalDate(order.cancelledAt, today, zoneId) ||
            isSameLocalDate(order.createdAt, today, zoneId)
    }

    fun formatLocalTime(dateStr: String?, zoneId: ZoneId = ZoneId.systemDefault()): String {
        val zoned = parseToZoned(dateStr, zoneId) ?: return "—"
        return zoned.format(timeFormatter)
    }

    fun formatLocalDateTime(dateStr: String?, zoneId: ZoneId = ZoneId.systemDefault()): String {
        val zoned = parseToZoned(dateStr, zoneId) ?: return "—"
        return zoned.format(dateTimeFormatter)
    }

    fun calcDuration(startStr: String?, endStr: String?, zoneId: ZoneId = ZoneId.systemDefault()): String {
        val start = parseToZoned(startStr, zoneId) ?: return "—"
        val end = parseToZoned(endStr, zoneId) ?: return "—"
        val mins = Duration.between(start, end).toMinutes().coerceAtLeast(0)
        return when {
            mins < 1L -> "< 1 min"
            mins < 60L -> "$mins min"
            else -> "${mins / 60}h ${mins % 60}min"
        }
    }
}
