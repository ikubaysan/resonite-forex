import os
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from time import sleep
import logging
from enum import Enum

class Interval(Enum):
    ONE_MINUTE = "1"
    THREE_MINUTES = "3"
    FIVE_MINUTES = "5"
    FIFTEEN_MINUTES = "15"
    THIRTY_MINUTES = "30"
    ONE_HOUR = "60"
    TWO_HOURS = "120"
    FOUR_HOURS = "240"
    ONE_DAY = "D"
    ONE_WEEK = "W"

class TradingViewWidget:
    def __init__(self, symbol: str, interval: str):
        self.symbol = symbol
        self.interval = interval

    def generate_html(self) -> str:
        sanitized_symbol = self.symbol.replace(':', '')
        return f'''
        <div id="tradingview_{sanitized_symbol}_{self.interval}" class="tradingview-widget-container" style="height:500px;width:500px">
            <div class="tradingview-widget-container__widget"></div>
            <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js">
            {{
            "autosize": true,
            "symbol": "{self.symbol}",
            "interval": "{self.interval}",
            "timezone": "Etc/UTC",
            "theme": "dark",
            "style": "1",
            "locale": "en",
            "enable_publishing": false,
            "allow_symbol_change": true,
            "container_id": "tradingview_{sanitized_symbol}_{self.interval}"
            }}
            </script>
        </div>'''


class TradingViewScreenshotter:
    def __init__(self, widgets: list[TradingViewWidget], output_folder: str = "screenshots", resolution: tuple[int, int] = (1280, 720)):
        self.widgets = widgets
        self.output_folder = output_folder
        self.resolution = resolution
        self.driver = self._setup_driver()

    def _setup_driver(self) -> webdriver.Chrome:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        driver.set_window_size(*self.resolution)  # Set the window size based on the resolution
        return driver

    def generate_html_file(self, filename: str = "tradingview_widgets.html") -> str:
        html_content = '<html><head><title>TradingView Widgets</title></head><body>'
        for widget in self.widgets:
            html_content += widget.generate_html()
        html_content += '</body></html>'

        with open(filename, 'w') as f:
            f.write(html_content)
        return os.path.abspath(filename)

    def take_screenshots(self, html_file: str):
        self.driver.get(f"file:///{html_file}")
        if not os.path.exists(self.output_folder):
            os.makedirs(self.output_folder)

        # Allow some time for widgets to fully load
        sleep(10)

        for widget in self.widgets:
            sanitized_symbol = widget.symbol.replace(':', '')
            element_id = f"tradingview_{sanitized_symbol}_{widget.interval}"
            element = self.driver.find_element(By.ID, element_id)
            element.screenshot(f"{self.output_folder}/{sanitized_symbol}_{widget.interval}.png")

    def close(self):
        self.driver.quit()

# Define the widgets for different time intervals and currency pairs
symbols = ["OANDA:EURUSD", "OANDA:GBPUSD", "OANDA:USDJPY"]
intervals = [Interval.ONE_HOUR, Interval.FOUR_HOURS, Interval.ONE_DAY]
widgets = [TradingViewWidget(symbol, interval.value) for symbol in symbols for interval in intervals]

# Initialize the screenshotter with the widgets and custom resolution (optional)
screenshotter = TradingViewScreenshotter(widgets, resolution=(1920, 1080))

# Generate HTML file and take screenshots
html_file = screenshotter.generate_html_file()
screenshotter.take_screenshots(html_file)
screenshotter.close()
