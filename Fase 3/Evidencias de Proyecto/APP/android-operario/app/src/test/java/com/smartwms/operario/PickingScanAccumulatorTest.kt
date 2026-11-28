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
    fun singleScanCompletesAllFiveHundredUnitsOfSku() {
        val acc = PickingScanAccumulator()
        val items = listOf(OrderItemSpec("SKU-00412", "Tornillo M8 Acero", 500))

        val res = acc.recordScan("SKU-00412", items)
        assertTrue("Un solo escaneo debe completar el SKU", res is ScanResult.Added)
        val added = res as ScanResult.Added
        assertEquals("SKU-00412", added.sku)
        assertEquals(500, added.addedQuantity)
        assertEquals(500, added.newQuantity)
        assertEquals(500, added.requiredQuantity)
        assertTrue(added.orderComplete)
        assertEquals(1, acc.snapshot().size)
        assertEquals(500, acc.getQuantity("SKU-00412"))

        // Un segundo escaneo del mismo SKU ya completado no duplica ni excede 500
        val second = acc.recordScan("SKU-00412", items)
        assertTrue(second is ScanResult.AlreadyComplete)
        assertEquals(500, acc.getQuantity("SKU-00412"))
    }

    @Test
    fun manualLowercaseSkuCompletesMultiItemOrderOneSkuPerEntry() {
        val acc = PickingScanAccumulator()
        val items = listOf(
            OrderItemSpec("SKU-00567", "Teclado Mecánico RGB", 500),
            OrderItemSpec("SKU-00891", "Cable USB-C 2m", 120)
        )

        val first = acc.recordScan(" sku-00567 ", items)
        assertTrue(first is ScanResult.Added)
        val added1 = first as ScanResult.Added
        assertEquals("SKU-00567", added1.sku)
        assertEquals(500, added1.newQuantity)
        assertFalse(added1.orderComplete)

        val second = acc.recordScan("SKU-00891", items)
        assertTrue(second is ScanResult.Added)
        val added2 = second as ScanResult.Added
        assertEquals("SKU-00891", added2.sku)
        assertEquals(120, added2.newQuantity)
        assertTrue(added2.orderComplete)

        assertEquals(2, acc.snapshot().size)
        assertEquals(500, acc.getQuantity("SKU-00567"))
        assertEquals(120, acc.getQuantity("SKU-00891"))
    }

    @Test
    fun concurrentScansOfSameSkuCompleteExactlyOnce() {
        val acc = PickingScanAccumulator()
        val items = listOf(OrderItemSpec("SKU-BULK", "Producto Masivo", 500))
        val pool = Executors.newFixedThreadPool(8)
        val latch = CountDownLatch(20)
        val addedCount = AtomicInteger(0)
        val alreadyCompleteCount = AtomicInteger(0)

        repeat(20) {
            pool.submit {
                try {
                    when (acc.recordScan("SKU-BULK", items)) {
                        is ScanResult.Added -> addedCount.incrementAndGet()
                        is ScanResult.AlreadyComplete -> alreadyCompleteCount.incrementAndGet()
                        else -> fail("Resultado inesperado en escaneo concurrente")
                    }
                } finally {
                    latch.countDown()
                }
            }
        }

        latch.await()
        pool.shutdown()

        assertEquals(1, addedCount.get())
        assertEquals(19, alreadyCompleteCount.get())
        assertEquals(500, acc.getQuantity("SKU-BULK"))
        assertEquals(1, acc.snapshot().size)
    }

    @Test
    fun invalidAndEmptyCodesDoNotMutateState() {
        val acc = PickingScanAccumulator()
        val items = listOf(OrderItemSpec("SKU-001", "Mouse", 500))

        assertTrue(acc.recordScan("   ", items) is ScanResult.EmptyCode)
        assertTrue(acc.recordScan("SKU-999", items) is ScanResult.InvalidCode)
        assertTrue(acc.snapshot().isEmpty())
    }
}
