import os
import re
import base64
import yaml
import requests
from loguru import logger
from tqdm import tqdm
from retry import retry
from concurrent.futures import ThreadPoolExecutor
from pre_check import pre_check

# 用于存放不同类型订阅的全局列表
new_sub_list = []
new_clash_list = []
new_v2_list = []

# 从环境变量获取 Telegram 配置
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
TG_CHAT_ID = os.getenv("TG_CHAT_ID")


@logger.catch
def yaml_check(path_yaml):
    if os.path.isfile(path_yaml):
        with open(path_yaml, encoding="utf-8") as f:
            dict_url = yaml.load(f, Loader=yaml.FullLoader)
        logger.info(f"读取订阅文件成功：{path_yaml}")
    else:
        dict_url = {
            "机场订阅": [],
            "clash订阅": [],
            "v2订阅": []
        }
        logger.info(f"订阅文件不存在，初始化新的订阅字典")
    return dict_url


@logger.catch
def get_config():
    with open('./config.yaml', encoding="utf-8") as f:
        data = yaml.load(f, Loader=yaml.FullLoader)
    tg_channels = data.get('tgchannel', [])
    channel_urls = [f'https://t.me/s/{url.split("/")[-1]}' for url in tg_channels]
    logger.info(f"从 config.yaml 读取 TG 频道列表，数量：{len(channel_urls)}")
    return channel_urls


@logger.catch
def get_channel_http(channel_url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Cache-Control': 'max-age=0',
        'Referer': channel_url,
    }

    try:
        resp = requests.get(channel_url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.text
        url_list = re.findall(r"https?://[-A-Za-z0-9+&@#/%?=~_|!:,.;]+[-A-Za-z0-9+&@#/%=~_|]", data)
        logger.info(f"{channel_url} 获取成功，提取链接数: {len(url_list)}")
    except requests.exceptions.RequestException as e:
        logger.warning(f"{channel_url} 请求失败: {e}")
        url_list = []
    except Exception as e:
        logger.error(f"{channel_url} 未知错误: {e}")
        url_list = []
    return url_list


def filter_base64(text):
    protocols = ['ss://', 'ssr://', 'vmess://', 'trojan://']
    return any(proto in text for proto in protocols)


@retry(tries=3, delay=5, backoff=2)
def sub_check(url, progress_bar, semaphore):
    headers = {'User-Agent': 'ClashforWindows/0.18.1'}

    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            info = res.headers.get('subscription-userinfo')
            if info:
                new_sub_list.append(url)
                return

            if 'proxies:' in res.text:
                new_clash_list.append(url)
                return

            try:
                snippet = res.text.strip()[:64]
                padding = '=' * (-len(snippet) % 4)
                decoded_bytes = base64.b64decode(snippet + padding)
                decoded_text = decoded_bytes.decode('utf-8', errors='ignore')
                if filter_base64(decoded_text):
                    new_v2_list.append(url)
            except base64.binascii.Error as e:
                logger.warning(f"Base64 解码错误 {url}: {e}")
    except requests.exceptions.RequestException as e:
        logger.debug(f"订阅检测失败 {url}: {e}")
    finally:
        with semaphore:
            progress_bar.update(1)


def save_subscriptions_as_txt(file_path, subscriptions_dict):
    with open(file_path, 'w', encoding='utf-8') as f:
        for category in ['机场订阅', 'clash订阅', 'v2订阅']:
            f.write(f"=== {category} ===\n")
            for url in subscriptions_dict.get(category, []):
                f.write(url + '\n')
            f.write('\n')


def send_telegram_file(bot_token, chat_id, file_path):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        with open(file_path, "rb") as f:
            files = {'document': f}
            data = {'chat_id': chat_id}
            response = requests.post(url, files=files, data=data)
        if response.status_code == 200:
            logger.success("✅ 文件发送成功")
        else:
            logger.error(f"❌ 文件发送失败: {response.text}")
    except Exception as e:
        logger.error(f"发送文件异常: {e}")


def main():
    path_yaml = pre_check()
    dict_url = yaml_check(path_yaml)
    tg_channels = get_config()

    logger.info('开始抓取 Telegram 频道订阅链接...')
    all_urls = []
    for channel_url in tg_channels:
        urls = get_channel_http(channel_url)
        all_urls.extend(urls)

    logger.info(f'总共抓取到订阅链接 {len(all_urls)} 条，开始筛选...')
    
    semaphore = threading.Semaphore(32)
    progress_bar = tqdm(total=len(all_urls), desc='订阅筛选')

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(sub_check, url, progress_bar, semaphore) for url in all_urls]
        for future in futures:
            future.result()

    progress_bar.close()
    logger.info('筛选完成，准备更新订阅内容')

    dict_url['机场订阅'] = list(set(new_sub_list + dict_url.get('机场订阅', [])))
    dict_url['clash订阅'] = list(set(new_clash_list + dict_url.get('clash订阅', [])))
    dict_url['v2订阅'] = list(set(new_v2_list + dict_url.get('v2订阅', [])))

    path_txt = os.path.splitext(path_yaml)[0] + '.txt'
    save_subscriptions_as_txt(path_txt, dict_url)
    logger.success(f'订阅文本文件已保存：{path_txt}')

    send_telegram_file(
        bot_token=TG_BOT_TOKEN,
        chat_id=TG_CHAT_ID,
        file_path=path_txt
    )


if __name__ == '__main__':
    # 配置日志级别
    if os.getenv("GITHUB_ACTIONS"):
        logger.remove()
        logger.add(sys.stderr, level="INFO")  # GitHub Actions 只输出 INFO 及以上日志
    else:
        logger.remove()
        logger.add(sys.stderr, level="DEBUG")  # 开发环境输出 DEBUG 级别日志

    main()
