"""Consent-gated Playwright browser automation for Ozzy.

Uses a dedicated persistent browser profile (never the user's normal Chrome/Edge
profile), semantic locators, bounded actions, and no direct filesystem access.
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

ALLOWED_BROWSERS = {"msedge", "chrome", "chromium", "firefox"}
CLICK_LOCATORS = {"role", "text", "label", "placeholder", "alt_text", "title", "test_id"}
FILL_LOCATORS = {"role", "label", "placeholder"}
SELECT_LOCATORS = {"role", "label"}
CHECK_LOCATORS = {"role", "label"}
ALLOWED_KEYS = {
    "Enter", "Tab", "Escape", "ArrowDown", "ArrowUp", "ArrowLeft", "ArrowRight",
    "Control+A", "Control+L", "Home", "End", "PageDown", "PageUp",
}
DANGEROUS_TARGET = re.compile(
    r"\b(pay|payment|purchase|buy|checkout|place order|delete|remove|send|publish|post|"
    r"transfer|approve|unsubscribe|cancel subscription|confirm purchase|submit payment)\b",
    re.IGNORECASE,
)
SENSITIVE_FIELD = re.compile(
    r"(password|passwd|passcode|one.?time.?code|otp|verification.?code|security.?code|"
    r"api.?key|access.?token|refresh.?token|secret|credential|"
    r"credit.?card|debit.?card|card.?number|cvv|cvc|iban|routing.?number|account.?number|"
    r"cc-number|cc-csc|cc-exp)",
    re.IGNORECASE,
)


def validate_browser(browser: Any) -> str:
    value = str(browser or "msedge").strip().lower()
    if value not in ALLOWED_BROWSERS:
        raise ValueError("Browser must be one of: msedge, chrome, chromium, firefox.")
    return value



def _browser_type(playwright, browser: str):
    """Choose the Playwright engine. Firefox requires Playwright's patched build."""
    return playwright.firefox if browser == "firefox" else playwright.chromium


def _profile_dir_for_browser(profile_dir: Path | str, browser: str) -> Path:
    """Keep Firefox storage separate while preserving the existing Chromium profile path."""
    base = Path(profile_dir).expanduser().resolve()
    return base.with_name(f"{base.name}-firefox") if browser == "firefox" else base


def _browser_launch_options(browser: str) -> dict[str, Any]:
    if browser == "firefox":
        return {"headless": False, "viewport": None}
    options: dict[str, Any] = {
        "headless": False,
        "viewport": None,
        "args": ["--no-first-run", "--no-default-browser-check"],
    }
    if browser != "chromium":
        options["channel"] = browser
    return options


def validate_url(url: Any, *, allow_blank: bool = False) -> str:
    value = str(url or "").strip()
    if allow_blank and not value:
        return "about:blank"
    if not value:
        raise ValueError("A website URL is required.")
    if len(value) > 2048:
        raise ValueError("The website URL is too long.")
    parsed = urlsplit(value)
    if parsed.scheme:
        if parsed.scheme.lower() not in {"http", "https"}:
            raise ValueError("For safety, browser navigation is limited to http:// and https:// websites.")
    else:
        value = "https://" + value
        parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("For safety, browser navigation is limited to http:// and https:// websites.")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing embedded usernames or passwords are not allowed.")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, parsed.fragment))


def validate_page_text(text: Any) -> str:
    if not isinstance(text, str):
        raise ValueError("Text to fill must be a string.")
    if len(text) > 3000:
        raise ValueError("Browser text input is limited to 3,000 characters per action.")
    if "\x00" in text:
        raise ValueError("Text contains an invalid null character.")
    return text


def is_sensitive_field(metadata: dict[str, Any]) -> bool:
    values = " ".join(str(metadata.get(key) or "") for key in ("type", "name", "id", "autocomplete", "ariaLabel", "placeholder", "label"))
    return str(metadata.get("type", "")).lower() == "password" or bool(SENSITIVE_FIELD.search(values))


def is_protected_click_target(value: Any) -> bool:
    target = str(value or "")
    return bool(DANGEROUS_TARGET.search(target) or SENSITIVE_FIELD.search(target))


def _public_url(url: str) -> str:
    """Avoid echoing query strings/fragments (which can contain session tokens)."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"}:
            return url
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "" if parsed.query else "", "")) + ("?…" if parsed.query else "")
    except Exception:
        return "(URL unavailable)"


class BrowserController:
    """One async Playwright controller owned by one Ozzy Live session."""

    def __init__(self, profile_dir: Path | str):
        self.profile_dir = Path(profile_dir).expanduser().resolve()
        self._playwright = None
        self._context = None
        self._page = None
        self._browser_name: str | None = None
        self._enabled = False
        self._lock = asyncio.Lock()

    def resume_actions(self) -> None:
        self._enabled = True

    def stop_actions(self) -> None:
        self._enabled = False

    def _check_enabled(self) -> None:
        if not self._enabled:
            raise RuntimeError("Browser automation is disabled. Enable PC Control in Ozzy's Advanced Options first.")

    async def close(self) -> None:
        self._enabled = False
        async with self._lock:
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception:
                    pass
            self._context = None
            self._page = None
            self._browser_name = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
            self._playwright = None

    async def _ensure_started(self, browser: str = "msedge") -> None:
        self._check_enabled()
        browser = validate_browser(browser)
        if self._context is not None:
            if self._browser_name != browser:
                raise RuntimeError(
                    f"Ozzy's managed browser is already running as {self._browser_name}. "
                    "Close the current browser session before selecting a different browser."
                )
            return

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed in Ozzy's active Python environment. "
                "Run .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt, then restart Ozzy."
            ) from exc

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._playwright = await async_playwright().start()
            launch_options: dict[str, Any] = {
                "headless": False,
                "viewport": None,
                "args": ["--no-first-run", "--no-default-browser-check"],
            }
            if browser != "chromium":
                launch_options["channel"] = browser
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir), **launch_options
            )
            self._context.on("page", self._remember_page)
            self._browser_name = browser
            pages = self._context.pages
            self._page = pages[-1] if pages else await self._context.new_page()
            self._page.set_default_timeout(6000)
        except Exception as exc:
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception:
                    pass
            self._context = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
            self._playwright = None
            self._browser_name = None
            detail = str(exc).splitlines()[0][:240]
            if browser == "firefox":
                hint = (
                    "Install Playwright's Firefox build with "
                    r".\.venv\Scripts\python.exe -m playwright install firefox. "
                    "Ozzy uses a separate managed Firefox profile; it does not attach to your normal Firefox profile."
                )
            elif browser == "chromium":
                hint = r"Install Playwright Chromium with .\.venv\Scripts\python.exe -m playwright install chromium."
            else:
                hint = f"Make sure {browser.title()} is installed, then try browser='chromium' after installing Playwright Chromium."
            raise RuntimeError(f"Could not launch the managed {browser} browser. {hint} Details: {detail}") from exc

    def _remember_page(self, page) -> None:
        if not page.is_closed():
            self._page = page

    async def _get_page(self):
        self._check_enabled()
        if self._context is None:
            raise RuntimeError("No managed browser is open yet. Ask Ozzy to open a website first.")
        pages = [page for page in self._context.pages if not page.is_closed()]
        if self._page is None or self._page.is_closed():
            self._page = pages[-1] if pages else await self._context.new_page()
        if self._page not in pages and pages:
            self._page = pages[-1]
        return self._page

    async def _locator(self, page, by: str, value: str, role: str | None = None, exact: bool = True):
        by = str(by or "").strip().lower()
        value = str(value or "").strip()
        if not value or len(value) > 180:
            raise ValueError("A locator value between 1 and 180 characters is required.")
        if by == "role":
            role = str(role or "").strip().lower()
            if not role:
                raise ValueError("When locating by role, provide a role such as button, link, textbox, or checkbox.")
            return page.get_by_role(role, name=value, exact=bool(exact))
        if by == "text":
            return page.get_by_text(value, exact=bool(exact))
        if by == "label":
            return page.get_by_label(value, exact=bool(exact))
        if by == "placeholder":
            return page.get_by_placeholder(value, exact=bool(exact))
        if by == "alt_text":
            return page.get_by_alt_text(value, exact=bool(exact))
        if by == "title":
            return page.get_by_title(value, exact=bool(exact))
        if by == "test_id":
            return page.get_by_test_id(value)
        raise ValueError(f"Unsupported locator type: {by}")

    async def _unique_visible_enabled(self, locator):
        count = await locator.count()
        if count == 0:
            raise RuntimeError("No matching page element was found. Inspect the page and try a more precise label or role.")
        if count != 1:
            raise RuntimeError(f"The locator matches {count} elements. Be more specific; Ozzy will not guess which one you mean.")
        if not await locator.is_visible():
            raise RuntimeError("The matching page element is not visible.")
        if not await locator.is_enabled():
            raise RuntimeError("The matching page element is disabled.")

    async def open(self, url: Any, browser: Any = "msedge") -> dict[str, Any]:
        async with self._lock:
            self._check_enabled()
            target = validate_url(url)
            await self._ensure_started(browser)
            page = await self._get_page()
            await page.goto(target, wait_until="domcontentloaded", timeout=20000)
            return {"ok": True, "title": (await page.title())[:200], "url": _public_url(page.url), "message": "Opened the website in Ozzy's managed browser."}

    async def inspect(self) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            try:
                body_text = await page.locator("body").inner_text(timeout=4000)
            except Exception:
                body_text = ""
            body_text = body_text.strip()[:9000]
            elements = await page.locator(
                "button:visible, a:visible, input:visible, textarea:visible, select:visible, "
                "[role=button]:visible, [role=link]:visible"
            ).evaluate_all(
                """nodes => nodes.slice(0, 70).map(el => {
                    const tag = (el.tagName || '').toLowerCase();
                    const name = (el.getAttribute('aria-label') || el.innerText || el.getAttribute('placeholder') || el.getAttribute('title') || '').trim();
                    let href = '';
                    if (tag === 'a' && el.href) {
                        try { const u = new URL(el.href); href = u.origin + u.pathname; } catch (_) {}
                    }
                    return {
                        tag,
                        role: el.getAttribute('role') || '',
                        name: name.slice(0, 140),
                        placeholder: (el.getAttribute('placeholder') || '').slice(0, 100),
                        inputType: (el.getAttribute('type') || '').slice(0, 30),
                        disabled: Boolean(el.disabled),
                        href
                    };
                })"""
            )
            return {
                "ok": True,
                "title": (await page.title())[:200],
                "url": _public_url(page.url),
                "text": body_text,
                "interactive_elements": elements,
                "message": "Read visible page text and a bounded list of visible interactive elements. No form field values were read.",
            }

    async def click(self, args: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            by, value = args.get("by"), args.get("value")
            if is_protected_click_target(value):
                raise RuntimeError("This control appears to perform a sensitive or irreversible action. Ozzy will not activate it; please take over manually.")
            if str(by).lower() not in CLICK_LOCATORS:
                raise ValueError(f"Click locator must be one of: {', '.join(sorted(CLICK_LOCATORS))}.")
            locator = await self._locator(page, by, value, args.get("role"), args.get("exact", True))
            await self._unique_visible_enabled(locator)
            await locator.click(timeout=6000)
            return {"ok": True, "title": (await page.title())[:200], "url": _public_url(page.url), "message": f"Clicked the uniquely matched {by} target. Inspect the page to verify the result."}

    async def fill(self, args: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            by = str(args.get("by") or "").lower()
            if by not in FILL_LOCATORS:
                raise ValueError(f"Fill locator must be one of: {', '.join(sorted(FILL_LOCATORS))}.")
            text = validate_page_text(args.get("text", ""))
            locator = await self._locator(page, by, args.get("value"), args.get("role"), args.get("exact", True))
            await self._unique_visible_enabled(locator)
            metadata = await locator.evaluate(
                """el => ({
                    tagName: (el.tagName || '').toLowerCase(),
                    type: el.getAttribute('type') || '',
                    name: el.getAttribute('name') || '',
                    id: el.id || '',
                    autocomplete: el.getAttribute('autocomplete') || '',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    placeholder: el.getAttribute('placeholder') || '',
                    label: el.labels ? Array.from(el.labels).map(x => x.innerText).join(' ') : ''
                })"""
            )
            if is_sensitive_field(metadata):
                raise RuntimeError("This looks like a password, verification-code, or payment field. Ozzy will not fill it.")
            editable = await locator.evaluate("el => Boolean(el.isContentEditable)")
            allowed_input_types = {"", "text", "search", "email", "url", "tel", "number", "date", "month", "time", "datetime-local", "week"}
            if metadata.get("tagName") == "input" and str(metadata.get("type") or "").lower() not in allowed_input_types:
                raise RuntimeError("The matched input type is not supported for text filling.")
            if metadata.get("tagName") not in {"input", "textarea"} and not editable:
                raise RuntimeError("The matched element is not a supported text field.")
            await locator.fill(text, timeout=6000)
            return {"ok": True, "message": "Filled the uniquely matched text field. The entered value was not read back."}

    async def select(self, args: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            by = str(args.get("by") or "").lower()
            if by not in SELECT_LOCATORS:
                raise ValueError("Select locator must be role or label.")
            locator = await self._locator(page, by, args.get("value"), args.get("role"), args.get("exact", True))
            await self._unique_visible_enabled(locator)
            tag = await locator.evaluate("el => (el.tagName || '').toLowerCase()")
            if tag != "select":
                raise RuntimeError("The matched element is not a native select/dropdown control.")
            option = str(args.get("option") or "").strip()
            if is_protected_click_target(args.get("value")) or is_protected_click_target(option):
                raise RuntimeError("This dropdown appears related to a sensitive or irreversible action. Ozzy will not change it.")
            if SENSITIVE_FIELD.search(str(args.get("value") or "")) or SENSITIVE_FIELD.search(option):
                raise RuntimeError("This dropdown may contain credential or payment information. Ozzy will not change it.")
            if not option or len(option) > 160:
                raise ValueError("Provide an option label or value up to 160 characters.")
            option_type = str(args.get("option_type") or "label").lower()
            if option_type not in {"label", "value"}:
                raise ValueError("option_type must be label or value.")
            await locator.select_option(**{option_type: option}, timeout=6000)
            return {"ok": True, "message": "Selected the requested dropdown option."}

    async def check(self, args: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            by = str(args.get("by") or "").lower()
            if by not in CHECK_LOCATORS:
                raise ValueError("Checkbox locator must be role or label.")
            if is_protected_click_target(args.get("value")):
                raise RuntimeError("This control appears related to a sensitive or irreversible action. Ozzy will not change it.")
            locator = await self._locator(page, by, args.get("value"), args.get("role") or "checkbox", args.get("exact", True))
            await self._unique_visible_enabled(locator)
            role = await locator.get_attribute("type")
            if role not in {"checkbox", "radio"}:
                actual_role = await locator.get_attribute("role")
                if actual_role not in {"checkbox", "radio"}:
                    raise RuntimeError("The matched element is not a checkbox or radio control.")
            if bool(args.get("checked", True)):
                await locator.check(timeout=6000)
            else:
                await locator.uncheck(timeout=6000)
            return {"ok": True, "message": "Updated the checkbox/radio selection."}

    async def press(self, key: Any) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            key = str(key or "").strip()
            if key not in ALLOWED_KEYS:
                raise ValueError(f"Keyboard key must be one of: {', '.join(sorted(ALLOWED_KEYS))}.")
            await page.keyboard.press(key)
            return {"ok": True, "message": f"Pressed {key} in the managed browser."}

    async def scroll(self, direction: Any, amount: Any = 2) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            direction = str(direction or "").lower()
            if direction not in {"up", "down"}:
                raise ValueError("Scroll direction must be up or down.")
            if isinstance(amount, bool) or not isinstance(amount, int) or not 1 <= amount <= 8:
                raise ValueError("Scroll amount must be a whole number between 1 and 8.")
            delta = amount * 420 * (1 if direction == "down" else -1)
            await page.mouse.wheel(0, delta)
            return {"ok": True, "message": f"Scrolled {direction} by {amount} step(s)."}

    async def new_tab(self, url: Any = "") -> dict[str, Any]:
        async with self._lock:
            self._check_enabled()
            if self._context is None:
                await self._ensure_started("msedge")
            self._page = await self._context.new_page()
            target = validate_url(url, allow_blank=True)
            if target != "about:blank":
                await self._page.goto(target, wait_until="domcontentloaded", timeout=20000)
            return {"ok": True, "url": _public_url(self._page.url), "message": "Opened a new managed browser tab."}

    async def list_tabs(self) -> dict[str, Any]:
        async with self._lock:
            self._check_enabled()
            if self._context is None:
                raise RuntimeError("No managed browser is open yet.")
            tabs = []
            for index, page in enumerate(self._context.pages):
                if not page.is_closed():
                    tabs.append({"index": index, "title": (await page.title())[:160], "url": _public_url(page.url), "active": page == self._page})
            return {"ok": True, "tabs": tabs, "message": f"Found {len(tabs)} managed browser tab(s)."}

    async def switch_tab(self, index: Any) -> dict[str, Any]:
        async with self._lock:
            self._check_enabled()
            if self._context is None:
                raise RuntimeError("No managed browser is open yet.")
            if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(self._context.pages):
                raise ValueError("Tab index is out of range.")
            page = self._context.pages[index]
            if page.is_closed():
                raise RuntimeError("That browser tab is already closed.")
            self._page = page
            await page.bring_to_front()
            return {"ok": True, "title": (await page.title())[:160], "url": _public_url(page.url), "message": f"Switched to tab {index}."}

    async def navigate(self, url: Any) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            target = validate_url(url)
            await page.goto(target, wait_until="domcontentloaded", timeout=20000)
            return {"ok": True, "title": (await page.title())[:200], "url": _public_url(page.url), "message": "Navigated the managed browser to the requested website."}

    async def history(self, action: str) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            if action == "back":
                await page.go_back(wait_until="domcontentloaded", timeout=12000)
            elif action == "forward":
                await page.go_forward(wait_until="domcontentloaded", timeout=12000)
            elif action == "refresh":
                await page.reload(wait_until="domcontentloaded", timeout=15000)
            else:
                raise ValueError("Unsupported browser history action.")
            return {"ok": True, "title": (await page.title())[:200], "url": _public_url(page.url), "message": f"Browser {action} completed. Inspect the page to verify it."}

    async def screenshot(self) -> dict[str, Any]:
        async with self._lock:
            page = await self._get_page()
            image_bytes = await page.screenshot(type="jpeg", quality=65, full_page=False, timeout=8000)
            return {"ok": True, "message": "Captured the managed browser viewport for Gemini inspection. The image was not saved to disk.", "image_bytes": image_bytes}

    async def execute_action(self, name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
        self._check_enabled()
        args = args or {}
        if name == "browser_open":
            return await self.open(args.get("url"), args.get("browser", "msedge"))
        if name == "browser_inspect":
            return await self.inspect()
        if name == "browser_click":
            return await self.click(args)
        if name == "browser_fill":
            return await self.fill(args)
        if name == "browser_select":
            return await self.select(args)
        if name == "browser_check":
            return await self.check(args)
        if name == "browser_press":
            return await self.press(args.get("key"))
        if name == "browser_scroll":
            return await self.scroll(args.get("direction"), args.get("amount", 2))
        if name == "browser_new_tab":
            return await self.new_tab(args.get("url", ""))
        if name == "browser_list_tabs":
            return await self.list_tabs()
        if name == "browser_switch_tab":
            return await self.switch_tab(args.get("index"))
        if name == "browser_navigate":
            return await self.navigate(args.get("url"))
        if name == "browser_back":
            return await self.history("back")
        if name == "browser_forward":
            return await self.history("forward")
        if name == "browser_refresh":
            return await self.history("refresh")
        if name == "browser_screenshot":
            return await self.screenshot()
        raise ValueError(f"Unsupported browser-control action: {name}")
