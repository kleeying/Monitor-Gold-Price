import os, re, pathlib
import requests
from playwright.sync_api import sync_playwright

URL = "https://www.uobgroup.com/online-rates/gold-and-silver-prices.page"
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
# optional extra recipients of the price-drop alert
EXTRA_CHAT_IDS = [
    os.environ.get("TELEGRAM_CHAT_ID_2"),
    os.environ.get("TELEGRAM_CHAT_ID_3"),
]
API = f"https://api.telegram.org/bot{TOKEN}"
STATE = pathlib.Path("state.txt")
THRESHOLD_FILE = pathlib.Path("threshold.txt")

def send(text):
    """Send a message to you (the owner)."""
    r = requests.post(f"{API}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": text}, timeout=30)
    r.raise_for_status()

def send_extras(text):
    """Send a message to each extra recipient that has been set up."""
    for number, chat_id in enumerate(EXTRA_CHAT_IDS, start=2):
        if not chat_id:
            continue
        try:
            r = requests.post(f"{API}/sendMessage",
                              data={"chat_id": chat_id, "text": text}, timeout=30)
            r.raise_for_status()
        except Exception as e:
            print(f"Could not send to person {number}: {type(e).__name__}")

def read_commands():
    """Read new messages sent to the bot. Returns (new_threshold, status_requested)."""
    r = requests.get(f"{API}/getUpdates", timeout=30)
    r.raise_for_status()
    updates = r.json().get("result", [])
    new_threshold, status = None, False
    for u in updates:
        msg = u.get("message") or {}
        # only the owner can give commands; everyone else is ignored
        if str(msg.get("chat", {}).get("id")) != str(CHAT_ID):
            continue
        text = (msg.get("text") or "").strip()
        m = re.match(r"^/set(?:@\w+)?\s+([\d,]+(?:\.\d+)?)$", text, re.I)
        if m:
            new_threshold = float(m.group(1).replace(",", ""))
        elif re.match(r"^/status(?:@\w+)?$", text, re.I):
            status = True
    if updates:  # mark these messages as read
        requests.get(f"{API}/getUpdates",
                     params={"offset": updates[-1]["update_id"] + 1}, timeout=30)
    return new_threshold, status

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

# 1. Work out the current alert price
new_threshold, status_requested = read_commands()
if THRESHOLD_FILE.exists():
    threshold = float(THRESHOLD_FILE.read_text().strip())
else:
    threshold = float(os.environ.get("PRICE_THRESHOLD") or 0)

previous = STATE.read_text().strip() if STATE.exists() else "above"

if new_threshold is not None:
    threshold = new_threshold
    previous = "above"  # re-arm, so an alert is sent if price is already below
    send(f"Alert price set to SGD {threshold:,.2f}.")
THRESHOLD_FILE.write_text(str(threshold))

# 2. Check the price
price = get_price()
print(f"Bank sells: {price}  Threshold: {threshold}")
current = "below" if price < threshold else "above"

if status_requested:
    send(f"UOB Argor cast bar 100g: bank sells SGD {price:,.2f}.\n"
         f"Your alert price: SGD {threshold:,.2f}.")

# 3. Send the price-drop alert to everyone
if current == "below" and previous != "below":
    alert = (f"UOB Argor cast bar 100g: bank sells SGD {price:,.2f}, "
             f"below the alert price of SGD {threshold:,.2f}.\n{URL}")
    send(alert)
    send_extras(alert)

STATE.write_text(current)
