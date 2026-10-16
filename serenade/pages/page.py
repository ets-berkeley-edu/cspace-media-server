"""What every page object shares, as in the team's other Selenium suites: waits, clicks and typing by locator."""
from __future__ import annotations

from selenium.common.exceptions import ElementClickInterceptedException, StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.wait import WebDriverWait

Locator = tuple[str, str]
TIMEOUT = 10
# The open dialog (Vuetify puts a dialog's content in an overlay at the end of the page).
DIALOG = "//div[contains(@class, 'v-overlay--active')]//div[contains(@class, 'v-overlay__content')]"


class Page:
    def __init__(self, driver: WebDriver, base_url: str):
        self.driver = driver
        self.base_url = base_url

    def open(self, path: str = "") -> None:
        self.driver.get(self.base_url + path)

    def wait_for(self, locator: Locator, timeout: float = TIMEOUT) -> WebElement:
        element: WebElement = WebDriverWait(self.driver, timeout).until(ec.visibility_of_element_located(locator))
        return element

    def wait_for_text(self, locator: Locator, text: str, timeout: float = TIMEOUT) -> WebElement:
        """Waits until the element shows the text (pages fill in after their data arrives)."""
        WebDriverWait(self.driver, timeout).until(ec.text_to_be_present_in_element(locator, text))
        return self.wait_for(locator)

    def wait_for_value(self, locator: Locator, text: str, timeout: float = TIMEOUT) -> str:
        """Waits until a field's value holds the text; returns the value."""
        WebDriverWait(self.driver, timeout).until(ec.text_to_be_present_in_element_value(locator, text))
        return self.value_of(locator)

    def wait_until_gone(self, locator: Locator, timeout: float = TIMEOUT) -> None:
        WebDriverWait(self.driver, timeout).until(ec.invisibility_of_element_located(locator))

    def wait_for_picture(self, locator: Locator, timeout: float = TIMEOUT) -> None:
        """Waits until every image the locator finds has loaded a picture (not a broken image)."""
        def loaded(driver: WebDriver) -> bool:
            images = driver.find_elements(*locator)
            return bool(images) and all(driver.execute_script(
                "return arguments[0].complete && arguments[0].naturalWidth > 0", image) for image in images)

        WebDriverWait(self.driver, timeout, ignored_exceptions=(StaleElementReferenceException,)).until(loaded)

    def click(self, locator: Locator) -> None:
        """Clicks the element once it can take the click. Just after a page opens, its layout is still settling (the
        side menu briefly covers the content), and Chrome refuses a click that would land on another element: then it
        waits and tries again, until the timeout. A refused click clicks nothing, so trying again is safe."""
        def clicked(driver: WebDriver) -> bool:
            element = ec.element_to_be_clickable(locator)(driver)
            if not element:
                return False
            element.click()
            return True

        WebDriverWait(self.driver, TIMEOUT, ignored_exceptions=(ElementClickInterceptedException,
                                                                 StaleElementReferenceException)).until(clicked)

    def type(self, locator: Locator, text: str) -> None:
        """Replaces what the field holds with the text."""
        element = self.wait_for(locator)
        self._empty(element)
        element.send_keys(text)

    def _empty(self, element: WebElement) -> None:
        """Empties a field so the page sees it: Selenium's clear() changes the value without the input event Vue's
        v-model listens for, so the page would keep the old text (and typing would add to it)."""
        self.driver.execute_script(
            "arguments[0].value = ''; arguments[0].dispatchEvent(new Event('input', {bubbles: true}))", element)

    def add_text(self, locator: Locator, text: str) -> None:
        """Types at the end of what the field already holds."""
        self.wait_for(locator).send_keys(text)

    def paste(self, locator: Locator, text: str) -> None:
        """Puts the text in a field as a paste would: typed, then the field's paste event. (Selenium can't use the
        clipboard the same way on every computer; the page reacts to the event, reading what the field then holds.)"""
        element = self.wait_for(locator)
        self._empty(element)
        element.send_keys(text)
        self.driver.execute_script(
            "arguments[0].dispatchEvent(new Event('paste', {bubbles: true, cancelable: true}))", element)

    def choose_file(self, locator: Locator, path: str) -> None:
        """Gives a file input a file (the input itself is hidden behind its field, so it's found, not waited for)."""
        WebDriverWait(self.driver, TIMEOUT).until(ec.presence_of_element_located(locator)).send_keys(path)

    def text_of(self, locator: Locator) -> str:
        return self.wait_for(locator).text

    def all_text_of(self, locator: Locator) -> str:
        """The element's whole text, including what's only for screen readers (a shortened CSID's whole CSID)."""
        return str(self.wait_for(locator).get_attribute("textContent"))

    def value_of(self, locator: Locator) -> str:
        return str(self.wait_for(locator).get_attribute("value"))

    def count(self, locator: Locator) -> int:
        return len(self.driver.find_elements(*locator))

    def focused_id(self) -> str:
        return str(self.driver.switch_to.active_element.get_attribute("id"))

    def wait_for_url(self, ending: str) -> None:
        WebDriverWait(self.driver, TIMEOUT).until(lambda d: d.current_url.endswith(ending))


def by_id(element_id: str) -> Locator:
    return (By.ID, element_id)


def dialog_button(text: str) -> Locator:
    """A button of the open dialog, by its words."""
    return (By.XPATH, f"{DIALOG}//button[normalize-space()='{text}']")


def messages_of(field_id: str) -> Locator:
    """The hint or the error message under a Vuetify field."""
    return (By.XPATH, f"//*[@id='{field_id}']/ancestor::div[contains(concat(' ', @class, ' '), ' v-input ')][1]"
                      "//div[contains(@class, 'v-messages')]")


def shortened(csid: str) -> str:
    """A CSID as the admin app shortens it in a table (admin/src/words.ts: short)."""
    return f"{csid[:8]}…{csid[-6:]}" if len(csid) > 20 else csid
