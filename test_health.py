"""Verdict tests for a sample NVMe health log. They do not open a disk."""

import unittest

import ssd_health


def sample_log(
    warning: int = 0,
    temp_k: int = 325,
    spare: int = 100,
    threshold: int = 5,
    used: int = 2,
    media: int = 0,
    critical_minutes: int = 0,
) -> bytes:
    log = bytearray(512)
    log[0] = warning
    log[1:3] = int(temp_k).to_bytes(2, "little")
    log[3] = spare
    log[4] = threshold
    log[5] = used
    log[160:168] = int(media).to_bytes(8, "little")
    log[196:200] = int(critical_minutes).to_bytes(4, "little")
    return bytes(log)


class HealthLogTests(unittest.TestCase):
    def test_healthy_log_is_ok(self):
        health = ssd_health.parse_health_log(sample_log())
        level, reasons = ssd_health.judge(health)
        self.assertEqual(health["temperature_c"], 52)
        self.assertEqual(health["available_spare"], 100)
        self.assertEqual(health["spare_threshold"], 5)
        self.assertEqual(health["percent_used"], 2)
        self.assertEqual(health["media_errors"], 0)
        self.assertEqual(level, "ok")
        self.assertIn("does not report a failure", reasons[0])

    def test_critical_warning_media_errors_and_wear(self):
        health = ssd_health.parse_health_log(
            sample_log(warning=0x04, media=3, used=95, temp_k=80 + 273)
        )
        level, reasons = ssd_health.judge(health)
        self.assertEqual(level, "critical")
        self.assertTrue(any("reliability" in reason for reason in reasons))
        self.assertTrue(any("media errors: 3" in reason for reason in reasons))
        self.assertTrue(any("life used 95%" in reason for reason in reasons))
        self.assertTrue(any("temperature is 80 C" in reason for reason in reasons))

    def test_spare_at_limit_is_critical(self):
        health = ssd_health.parse_health_log(sample_log(spare=5, threshold=5))
        level, reasons = ssd_health.judge(health)
        self.assertEqual(level, "critical")
        self.assertTrue(any("spare space 5%" in reason for reason in reasons))

    def test_warm_drive_is_a_warning(self):
        health = ssd_health.parse_health_log(sample_log(temp_k=70 + 273))
        level, reasons = ssd_health.judge(health)
        self.assertEqual(level, "warning")
        self.assertTrue(any("temperature is 70 C" in reason for reason in reasons))

    def test_critical_temperature_time_is_a_warning(self):
        health = ssd_health.parse_health_log(sample_log(critical_minutes=12))
        level, reasons = ssd_health.judge(health)
        self.assertEqual(level, "warning")
        self.assertTrue(any("12 minutes" in reason for reason in reasons))

    def test_smartctl_without_a_health_log_is_empty(self):
        self.assertIsNone(
            ssd_health.health_from_smartctl({"smart_support": {"available": False}})
        )

    def test_smartctl_nvme_json_uses_the_same_verdict(self):
        health = ssd_health.health_from_smartctl(
            {
                "nvme_smart_health_information_log": {
                    "critical_warning": 0,
                    "temperature": 53,
                    "available_spare": 100,
                    "available_spare_threshold": 5,
                    "percentage_used": 2,
                    "media_errors": 0,
                    "power_on_hours": 10,
                    "critical_comp_time": 0,
                }
            }
        )
        level, reasons = ssd_health.verdict(health)
        self.assertEqual(health["temperature_c"], 53)
        self.assertEqual(health["percent_used"], 2)
        self.assertEqual(health["media_errors"], 0)
        self.assertEqual(level, "ok")
        self.assertIn("does not report a failure", reasons[0])

    def test_ata_pending_sectors_are_critical(self):
        health = ssd_health.health_from_smartctl(
            {
                "smart_status": {"passed": True},
                "temperature": {"current": 40},
                "ata_smart_attributes": {
                    "table": [
                        {"id": 5, "name": "Reallocated_Sector_Ct", "value": 100, "raw": {"value": 4}},
                        {"id": 197, "name": "Current_Pending_Sector", "value": 100, "raw": {"value": 2}},
                        {"id": 231, "name": "SSD_Life_Left", "value": 90, "raw": {"value": 90}},
                    ]
                },
            }
        )
        level, reasons = ssd_health.verdict(health)
        self.assertEqual(health["media_errors"], 2)
        self.assertEqual(health["percent_used"], 10)
        self.assertEqual(level, "critical")
        self.assertTrue(any("media errors: 2" in reason for reason in reasons))
        self.assertTrue(any("reallocated sectors: 4" in reason for reason in reasons))

    def test_phone_on_a_cable_has_no_health_log(self):
        block = ssd_health.phone_block("iPhone")
        self.assertIn("Phone: iPhone", block)
        self.assertTrue(any(ssd_health.PHONE_CABLE in line for line in block))

    def test_health_percent_ignores_a_slow_read(self):
        health = ssd_health.parse_health_log(sample_log())
        self.assertEqual(ssd_health.health_percent(health), 98)
        level, text = ssd_health.performance_rating(319, 79)
        self.assertEqual(level, "critical")
        self.assertIn("not the usual speed", text)
        self.assertEqual(ssd_health.health_percent(health), 98)

    def test_media_errors_cap_health_at_10(self):
        health = ssd_health.parse_health_log(sample_log(media=2, used=2))
        self.assertEqual(ssd_health.health_percent(health), 10)

    def test_performance_bands(self):
        self.assertEqual(ssd_health.performance_rating(40, 10)[0], "ok")
        self.assertEqual(ssd_health.performance_rating(100, 10)[0], "warning")
        self.assertEqual(ssd_health.performance_rating(None, None)[0], None)

    def test_remaining_life_estimate(self):
        self.assertEqual(ssd_health.remaining_life_hours(2, 3273), 3273 * 98 / 2)

    def test_forecast_connects_wear_and_restarts(self):
        lines = ssd_health.forecast_lines(98, "critical", 292, [], True, True)
        text = "\n".join(lines)
        self.assertIn("wear score is still high", text)
        self.assertIn("unexpected restarts", text)
        self.assertIn("power source changed", text)
        self.assertIn("slowed by firmware", text)

    def test_history_notes_a_slower_read(self):
        notes = ssd_health.worse_than({"read_ms": "100", "media": "0", "temp_max": "80"}, 319, 0, 80)
        self.assertTrue(any("worse than the last saved check" in note for note in notes))

    def test_warranty_pages_for_seagate_and_adata(self):
        seagate = "\n".join(ssd_health.warranty_lines("Seagate ZP1000CV30002", "6479_A79B"))
        self.assertIn("Warranty expiry: not stored on this drive.", seagate)
        self.assertIn("https://www.seagate.com/support/warranty-and-replacements/", seagate)
        adata = "\n".join(ssd_health.warranty_lines("ADATA SU650", "ABC123"))
        self.assertIn("https://www.adata.com/global/support/warranty/", adata)
        self.assertNotIn("98%", seagate)

    def test_android_health_fields(self):
        level, reasons, details = ssd_health.android_health("0x01 0x01", "0x01")
        self.assertEqual(level, "ok")
        self.assertTrue(any("do not report a failure" in reason for reason in reasons))
        self.assertIn("Wear type A: 0-10%", details)

        level, reasons, _details = ssd_health.android_health("0x0B 0x01", "0x03")
        self.assertEqual(level, "critical")
        self.assertTrue(reasons)

        self.assertEqual(ssd_health.android_health("", "")[0], "none")


if __name__ == "__main__":
    unittest.main()
