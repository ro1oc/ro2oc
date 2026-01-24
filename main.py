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

valid_subscriptions = set()

# ================== 工具函数 ==================

def ensure_sub_dir():
    os.makedirs("sub", exist_ok=True)

def gen_output_filename():
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return os.path.join("sub", f"{ts}.txt")

@logger.catch
def load_sub_yaml(path_yaml):
    if os.path.isfile(path_yaml):
        with open(path_yaml, encoding="utf-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    return {}

@logger.catch
def get_config():
    with open("./config.yaml", encoding="utf-8") as f:
        data = yaml.load(f, Loader=yaml.FullLoader)
    urls = []
    for url in data.get("tgchannel", []):
        name = url.split("/")[-1]
        urls.append(f"https://t.me/s/{name}")
    return urls

@logger.catch
def get_channel_http(channel_url):
    try:
        resp = requests.get(channel_url, timeout=15)
        all_urls = re.findall(re_str, resp.text)
        return [
            u for u in all_urls
            if "//t.me/" not in u and "cdn-telegram.org" not in u
        ]
    except Exception:
        return []

def get_url_from_channel():
    urls = []
    for channel in get_config():
        urls.extend(get_channel_http(channel))
    return urls

def get_url_from_yaml(yaml_file):
    data = load_sub_yaml(yaml_file)
    return re.findall(re_str, str(data))

# ================== 核心检测逻辑 ==================

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

def filter_valid_subscriptions(url_list):
    logger.info("开始检测订阅是否可解析节点")
    bar = tqdm(total=len(url_list), desc="检测订阅")
    threads = []

    for url in url_list:
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

    # 订阅来源：TG + 现有 yaml
    yaml_today = pre_check()
    yaml_all = get_sub_all()

    url_list = set()
    url_list.update(get_url_from_channel())
    url_list.update(get_url_from_yaml(yaml_today))
    url_list.update(get_url_from_yaml(yaml_all))

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
