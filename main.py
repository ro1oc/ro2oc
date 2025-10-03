import sys
import os
import re
import base64
import yaml
import requests
import threading
from loguru import logger
from tqdm import tqdm
from retry import retry
from concurrent.futures import ThreadPoolExecutor
from pre_check import pre_check

# Global lists for different subscription types
new_sub_list = []
new_clash_list = []
new_v2_list = []

# Load environment variables
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")


def validate_env_variables():
    """Validate required environment variables."""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        logger.error("Environment variables TG_BOT_TOKEN and TG_CHAT_ID must be set.")
        sys.exit(1)


@logger.catch
def load_yaml_file(file_path):
    """Load YAML file and return its content as a dictionary."""
    try:
        if os.path.isfile(file_path):
            with open(file_path, encoding="utf-8") as f:
                data = yaml.load(f, Loader=yaml.FullLoader)
            logger.info(f"Loaded YAML file successfully: {file_path}")
        else:
            data = {"机场订阅": [], "clash订阅": [], "v2订阅": []}
            logger.info(f"YAML file not found, initialized empty dictionary.")
        return data
    except Exception as e:
        logger.error(f"Failed to load YAML file: {file_path}, Error: {e}")
        sys.exit(1)


@logger.catch
def save_yaml_file(file_path, data):
    """Save dictionary data to a YAML file."""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True)
        logger.info(f"Saved YAML file successfully: {file_path}")
    except Exception as e:
        logger.error(f"Failed to save YAML file: {file_path}, Error: {e}")
        sys.exit(1)


@logger.catch
def fetch_tg_channels_from_config():
    """Fetch Telegram channels from config file."""
    try:
        with open('./config.yaml', encoding="utf-8") as f:
            data = yaml.load(f, Loader=yaml.FullLoader)
        tg_channels = data.get('tgchannel', [])
        logger.info(f"Loaded {len(tg_channels)} Telegram channels from config.yaml")
        return [f'https://t.me/s/{url.split("/")[-1]}' for url in tg_channels]
    except Exception as e:
        logger.error(f"Failed to load config.yaml: {e}")
        sys.exit(1)


@logger.catch
def fetch_channel_links(channel_url):
    """Fetch links from a Telegram channel."""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36'
    }
    try:
        resp = requests.get(channel_url, headers=headers, timeout=10)
        resp.raise_for_status()
        links = re.findall(r"https?://[-A-Za-z0-9+&@#/%?=~_|!:,.;]+[-A-Za-z0-9+&@#/%=~_|]", resp.text)
        logger.info(f"Fetched {len(links)} links from {channel_url}")
        return links
    except requests.RequestException as e:
        logger.warning(f"Failed to fetch links from {channel_url}: {e}")
        return []


def is_base64_encoded(text):
    """Check if the text is valid Base64."""
    try:
        decoded_bytes = base64.b64decode(text, validate=True)
        decoded_text = decoded_bytes.decode('utf-8', errors='ignore')
        return any(proto in decoded_text for proto in ['ss://', 'ssr://', 'vmess://', 'trojan://'])
    except Exception:
        return False


@retry(tries=3, delay=5, backoff=2)
def classify_subscription(url):
    """Classify subscription URL."""
    headers = {'User-Agent': 'ClashforWindows/0.18.1'}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code != 200:
            return

        if 'subscription-userinfo' in res.headers:
            new_sub_list.append(url)
        elif 'proxies:' in res.text:
            new_clash_list.append(url)
        elif is_base64_encoded(res.text.strip()[:64]):
            new_v2_list.append(url)
    except Exception as e:
        logger.debug(f"Error checking URL {url}: {e}")


def save_subscriptions_to_txt(file_path, subscriptions):
    """Save subscriptions to a text file."""
    try:
        with open(file_path, 'w', encoding="utf-8") as f:
            for category, urls in subscriptions.items():
                f.write(f"=== {category} ===\n")
                for url in urls:
                    f.write(url + '\n')
                f.write('\n')
        logger.info(f"Saved subscriptions to text file: {file_path}")
    except Exception as e:
        logger.error(f"Failed to save subscriptions to text file: {e}")


def send_telegram_file(bot_token, chat_id, file_path):
    """Send a file via Telegram."""
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            files = {'document': f}
            data = {'chat_id': chat_id}
            response = requests.post(url, files=files, data=data)
        if response.status_code == 200:
            logger.success("File sent successfully via Telegram.")
        else:
            logger.error(f"Failed to send file via Telegram: {response.text}")
    except Exception as e:
        logger.error(f"Error sending file via Telegram: {e}")


def main():
    validate_env_variables()

    path_yaml = pre_check()
    dict_url = load_yaml_file(path_yaml)
    tg_channels = fetch_tg_channels_from_config()

    logger.info("Fetching Telegram channel links...")
    all_urls = []
    for channel_url in tg_channels:
        all_urls.extend(fetch_channel_links(channel_url))

    logger.info(f"Fetched {len(all_urls)} links. Classifying subscriptions...")

    progress_bar = tqdm(total=len(all_urls), desc="Classifying")
    with ThreadPoolExecutor(max_workers=10) as executor:
        for url in all_urls:
            executor.submit(classify_subscription, url)
            progress_bar.update(1)
    progress_bar.close()

    dict_url['机场订阅'].extend(new_sub_list)
    dict_url['clash订阅'].extend(new_clash_list)
    dict_url['v2订阅'].extend(new_v2_list)

    path_txt = os.path.splitext(path_yaml)[0] + '.txt'
    save_subscriptions_to_txt(path_txt, dict_url)

    send_telegram_file(TG_BOT_TOKEN, TG_CHAT_ID, path_txt)


if __name__ == '__main__':
    log_level = os.getenv("LOG_LEVEL", "DEBUG")
    logger.remove()
    logger.add(sys.stderr, level=log_level)
    main()