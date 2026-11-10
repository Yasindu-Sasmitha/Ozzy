import unittest

import browser_control


class BrowserControlValidationTests(unittest.TestCase):
    def test_validates_http_and_https_urls(self):
        self.assertEqual(browser_control.validate_url("example.com"), "https://example.com/")
        self.assertEqual(browser_control.validate_url("http://localhost:3000/test"), "http://localhost:3000/test")

    def test_rejects_unsafe_url_schemes(self):
        for value in ("javascript:alert(1)", "file:///C:/Windows/win.ini", "data:text/html,hello", "chrome://settings"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    browser_control.validate_url(value)

    def test_rejects_embedded_url_credentials(self):
        with self.assertRaises(ValueError):
            browser_control.validate_url("https://user:pass@example.com")

    def test_blank_new_tab_is_allowed(self):
        self.assertEqual(browser_control.validate_url("", allow_blank=True), "about:blank")

    def test_browser_allow_list(self):
        self.assertEqual(browser_control.validate_browser("CHROME"), "chrome")
        for value in ("firefox", "edge", "powershell"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    browser_control.validate_browser(value)

    def test_rejects_long_or_invalid_fill_text(self):
        with self.assertRaises(ValueError):
            browser_control.validate_page_text("x" * 3001)
        with self.assertRaises(ValueError):
            browser_control.validate_page_text("hello\x00world")

    def test_detects_sensitive_fields(self):
        self.assertTrue(browser_control.is_sensitive_field({"type": "password"}))
        self.assertTrue(browser_control.is_sensitive_field({"name": "one_time_code"}))
        self.assertTrue(browser_control.is_sensitive_field({"autocomplete": "cc-number"}))
        self.assertFalse(browser_control.is_sensitive_field({"type": "text", "name": "search"}))

    def test_blocks_high_impact_click_targets(self):
        for value in ("Send", "Delete account", "Place order", "Confirm purchase"):
            with self.subTest(value=value):
                self.assertTrue(browser_control.is_protected_click_target(value))
        self.assertFalse(browser_control.is_protected_click_target("Search"))
        self.assertFalse(browser_control.is_protected_click_target("Read more"))


class BrowserControlConsentTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_tools_are_disabled_by_default(self):
        controller = browser_control.BrowserController("/tmp/ozzy-browser-test-profile")
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await controller.execute_action("browser_inspect", {})
        await controller.close()

    async def test_stop_disables_browser_tools(self):
        controller = browser_control.BrowserController("/tmp/ozzy-browser-test-profile")
        controller.resume_actions()
        controller.stop_actions()
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            await controller.execute_action("browser_inspect", {})
        await controller.close()


if __name__ == "__main__":
    unittest.main()
