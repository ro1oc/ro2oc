import re
import os
import yaml
import threading
import requests
from datetime import datetime
from urllib.parse import quote
from retry import retry
from loguru import logger
from tqdm import tqdm

from pre_check import pre_check, get_sub_all

# ================== 基础配置 ==================

re_str = r"https?://[-A-Za-z0-9+&@#/%?=~_|!:,.;]+[-A-Za-z0-9+&@#/%=~_|]"
thread_max_num = threading.Semaphore(32)

check_node_url_str = "https://{}/sub?target=clash&url={}&insert=false"
check_url_list = [
    "api.dler.io",
    "sub.xeton.dev",
    "sub.id9.cc",
    "sub.maoxiongnet.com"
]

SUB_KEYWORDS = [
    "sub", "subscribe",
    "clash", "v2ray", "singbox",
    "yaml", "yml", "config",
    "token", "机场", "订阅"
]

SUB_SUFFIX = (".yaml", ".yml", ".txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SubCollector/1.0)"
}

valid_subscriptions = set()

# ================== 目录与输出 ==================

def ensure_sub_dir():
    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    os.makedirs(os.path.join("sub", year, month), exist_ok=True)

def gen_output_filename():
    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    ts = now.strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join("sub", year, month, f"{ts}.txt")

# ================== 配置读取 ==================

@logger.catch
def load_yaml(path):
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    return {}

@logger.catch
def get_config():
    with open("./config.yaml", encoding="utf-8") as f:
        return yaml.load(f, Loader=yaml.FullLoader)

# ================== TG 抓取 ==================

@logger.catch
def get_channel_http(channel_url):
    try:
        r = requests.get(channel_url, timeout=15, headers=HEADERS)
        urls = re.findall(re_str, r.text)
        return [
            u for u in urls
            if "//t.me/" not in u and "cdn-telegram.org" not in u
        ]
    except Exception:
        return []

def get_url_from_channel():
    cfg = get_config()
    urls = []
    for u in cfg.get("tgchannel", []):
        name = u.split("/")[-1]
        urls.extend(get_channel_http(f"https://t.me/s/{name}"))
    return urls

# ================== YAML 抓取 ==================

def get_url_from_yaml(yaml_file):
    data = load_yaml(yaml_file)
    return re.findall(re_str, str(data))

# ================== 博客 / 论坛抓取 ==================

def extract_subscription_urls(html):
    urls = re.findall(re_str, html)
    result = []
    for u in urls:
        ul = u.lower()
        if any(k in ul for k in SUB_KEYWORDS) or ul.endswith(SUB_SUFFIX):
            result.append(u)
    return result

def extract_internal_links(html, base_url, limit=8):
    urls = re.findall(re_str, html)
    domain = base_url.split("/")[2]
    links = []
    for u in urls:
        if domain in u:
            links.append(u)
        if len(links) >= limit:
            break
    return links

@logger.catch
def crawl_site(site_url):
    collected = set()
    try:
        r = requests.get(site_url, timeout=15, headers=HEADERS)
        html = r.text
    except Exception:
        return collected

    collected.update(extract_subscription_urls(html))

    for link in extract_internal_links(html, site_url):
        try:
            r = requests.get(link, timeout=15, headers=HEADERS)
            collected.update(extract_subscription_urls(r.text))
        except Exception:
            continue

    return collected

def get_url_from_websites():
    cfg = get_config()
    urls = set()
    for site in cfg.get("websites", []):
        urls.update(crawl_site(site))
    return urls

# ================== 核心检测 ==================

@logger.catch
def check_subscription(url, bar):
    with thread_max_num:

        @retry(tries=2)
        def do_check():
            url_encoded = quote(url, safe="")
            for api in check_url_list:
                try:
                    check_url = check_node_url_str.format(api, url_encoded)
                    r = requests.get(check_url, timeout=15)
                    if r.status_code == 200:
                        valid_subscriptions.add(url)
                        return
                except Exception:
                    pass

        try:
            do_check()
        except Exception:
            pass

        bar.update(1)

def filter_valid_subscriptions(urls):
    logger.info("开始检测订阅是否可解析节点")
    bar = tqdm(total=len(urls), desc="检测订阅")
    threads = []

    for url in urls:
        t = threading.Thread(target=check_subscription, args=(url, bar))
        t.daemon = True
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    bar.close()
    logger.info(f"有效订阅数量：{len(valid_subscriptions)}")

# ================== 主流程 ==================

def main():
    ensure_sub_dir()

    yaml_today = pre_check()
    yaml_all = get_sub_all()

    url_list = set()
    url_list.update(get_url_from_channel())
    url_list.update(get_url_from_yaml(yaml_today))
    url_list.update(get_url_from_yaml(yaml_all))
    url_list.update(get_url_from_websites())

    if not url_list:
        logger.warning("未获取到任何订阅链接")
        return

    filter_valid_subscriptions(list(url_list))

    if not valid_subscriptions:
        logger.warning("没有检测到有效订阅")
        return

    output_file = gen_output_filename()
    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(valid_subscriptions)))

    logger.info(f"有效订阅已输出：{output_file}")

# ================== 入口 ==================

if __name__ == "__main__":
    main()
