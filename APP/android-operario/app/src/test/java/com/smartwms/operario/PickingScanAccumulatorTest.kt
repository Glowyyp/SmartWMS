package com.smartwms.operario

import com.smartwms.operario.ui.PickingScanAccumulator
import com.smartwms.operario.ui.PickingScanAccumulator.OrderItemSpec
import com.smartwms.operario.ui.PickingScanAccumulator.ScanResult
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

class PickingScanAccumulatorTest {

    @Test
    fun fiveConsecutiveScansAccumulateOneByOneWithoutDuplicates() {
        val acc = PickingScanAccumulator()
        val items = listOf(OrderItemSpec("SKU-00567", "Teclado Mecánico RGB", 5))

        for (expected in 1..5) {
            val res = acc.recordScan("SKU-00567", items)
            assertTrue("Scan #$expected debe registrarse", res is ScanResult.Added)
            val added = res as ScanResult.Added
            assertEquals("SKU-00567", added.sku)
            assertEquals(expected, added.newQuantity)
            assertEquals(5, added.requiredQuantity)
            assertEquals(expected == 5, added.orderComplete)
            // Un único registro acumulado en el mapa
            assertEquals(1, acc.snapshot().size)
            assertEquals(expected, acc.getQuantity("SKU-00567"))
        }

        // Un sexto escaneo no debe exceder la cantidad requerida
        val overflow = acc.recordScan("SKU-00567", items)
        assertTrue(overflow is ScanResult.AlreadyComplete)
        assertEquals(5, acc.getQuantity("SKU-00567"))
    }

    @Test
    fun twoHundredScansAccumulateExactQuantity() {
        val acc = PickingScanAccumulator()
        val items = listOf(OrderItemSpec("SKU-00412", "Tornillo M8 Acero", 200))

        for (i in 1..200) {
            val res = acc.recordScan(if (i % 2 == 0) "sku-00412" else " SKU-00412 ", items)
            assertTrue(res is ScanResult.Added)
            assertEquals(i, (res as ScanResult.Added).newQuantity)
        }

        assertEquals(1, acc.snapshot().size)
        assertEquals(200, acc.getQuantity("SKU-00412"))
        assertTrue(acc.isOrderComplete(items))
        assertTrue(acc.recordScan("SKU-00412", items) is ScanResult.AlreadyComplete)
    }

    @Test
    fun rapidConcurrentScansDoNotLoseOrDuplicateCounts() {
        val acc = PickingScanAccumulator()
        val items = listOf(OrderItemSpec("SKU-BULK", "Producto Masivo", 200))
        val pool = Executors.newFixedThreadPool(8)
        val latch = CountDownLatch(250)
        val addedCount = AtomicInteger(0)
        val completeCount = AtomicInteger(0)

        repeat(250) {
            pool.submit {
                try {
                    when (acc.recordScan("SKU-BULK", items)) {
                        is ScanResult.Added -> addedCount.incrementAndGet()
                        is ScanResult.AlreadyComplete -> completeCount.incrementAndGet()
                        else -> fail("Resultado inesperado en escaneo concurrente")
                    }
                } finally {
                    latch.countDown()
                }
            }
        }

        latch.await()
        pool.shutdown()

        assertEquals(200, addedCount.get())
        assertEquals(50, completeCount.get())
        assertEquals(200, acc.getQuantity("SKU-BULK"))
        assertEquals(1, acc.snapshot().size)
    }

    @Test
    fun invalidAndEmptyCodesDoNotMutateState() {
        val acc = PickingScanAccumulator()
        val items = listOf(OrderItemSpec("SKU-001", "Mouse", 3))

        assertTrue(acc.recordScan("   ", items) is ScanResult.EmptyCode)
        assertTrue(acc.recordScan("SKU-999", items) is ScanResult.InvalidCode)
        assertTrue(acc.snapshot().isEmpty())
    }
}
