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
        element = self.wait_for(locator)
        element.clear()
        element.send_keys(text)

    def text_of(self, locator: Locator) -> str:
        return self.wait_for(locator).text

    def wait_for_url(self, ending: str) -> None:
        WebDriverWait(self.driver, TIMEOUT).until(lambda d: d.current_url.endswith(ending))


def by_id(element_id: str) -> Locator:
    return (By.ID, element_id)
