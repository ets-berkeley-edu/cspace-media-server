"""What every page object shares, as in the team's other Selenium suites: waits, clicks and typing by locator."""
from __future__ import annotations

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

    def wait_for(self, locator: Locator) -> WebElement:
        element: WebElement = WebDriverWait(self.driver, TIMEOUT).until(ec.visibility_of_element_located(locator))
        return element

    def click(self, locator: Locator) -> None:
        WebDriverWait(self.driver, TIMEOUT).until(ec.element_to_be_clickable(locator)).click()

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
