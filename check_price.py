import os, re, pathlib
import requests
from playwright.sync_api import sync_playwright

URL = "https://www.uobgroup.com/online-rates/gold-and-silver-prices.page"
THRESHOLD = float(os.environ["PRICE_THRESHOLD"])
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
STATE = pathlib.Path("state.txt")

def send(text):
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text}, timeout=30)
    r.raise_for_status()

def get_price():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
            locale="en-SG")
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        # wait until the price table has been filled in
        page.wait_for_function(
            "document.querySelectorAll('table tr td').length > 8", timeout=60000)
        rows = page.eval_on_selector_all(
            "table tr",
            "rs => rs.map(r => Array.from(r.querySelectorAll('td,th'))"
            ".map(c => c.innerText.trim()))")
        browser.close()

    sell_col = 2  # DESCRIPTION, UNIT, BANK SELLS, BANK BUYS
    for cells in rows:
        print(cells)  # shown in the run log, useful for troubleshooting
        for i, c in enumerate(cells):
            if "BANK SELLS" in c.upper():
                sell_col = i
    for cells in rows:
        label = " ".join(cells[:2]).upper()
        if ("ARGOR" in label and "CAST" in label
                and re.search(r"\b100\s*(GRAMS?|GM|G)\b", label)):
            return float(re.sub(r"[^\d.]", "", cells[sell_col]))
    raise RuntimeError("Argor cast bar 100g row not found - see rows printed above")

price = get_price()
print(f"Bank sells: {price}  Threshold: {THRESHOLD}")

previous = STATE.read_text().strip() if STATE.exists() else "above"
current = "below" if price < THRESHOLD else "above"

if current == "below" and previous != "below":
    send(f"UOB Argor cast bar 100g: bank sells SGD {price:,.2f}, "
         f"below your alert price of SGD {THRESHOLD:,.2f}.\n{URL}")

STATE.write_text(current)
