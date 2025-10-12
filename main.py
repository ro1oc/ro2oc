import re
import os
import yaml
import threading
import base64
import requests
from loguru import logger
from tqdm import tqdm
from retry import retry
from urllib.parse import quote
from pre_check import pre_check, get_sub_all

# 常量配置
RE_STR = r"https?://[-A-Za-z0-9+&@#/%?=~_|!:,.;]+[-A-Za-z0-9+&@#/%=~_|]"
THREAD_MAX_NUM = 32  # 线程数
CHECK_NODE_URL_STR = "https://{}/sub?target={}&url={}&insert=false&config=config%2FACL4SSR.ini"
CHECK_URL_LIST = ['api.dler.io', 'sub.xeton.dev', 'sub.id9.cc', 'sub.maoxiongnet.com']

# 全局数据
new_sub_list = []
new_clash_list = []
new_v2_list = []
play_list = []
airport_list = []
protocol_nodes = []  # 存储抓取到的协议节点


@logger.catch
def load_sub_yaml(path_yaml):
    """加载 YAML 配置文件"""
    if os.path.isfile(path_yaml):
        with open(path_yaml, encoding="UTF-8") as f:
            return yaml.load(f, Loader=yaml.FullLoader)
    return {
        "机场订阅": [],
        "clash订阅": [],
        "v2订阅": [],
        "开心玩耍": []
    }


@logger.catch
def get_config():
    """读取配置文件中的 tgchannel 配置"""
    with open('./config.yaml', encoding="UTF-8") as f:
        data = yaml.load(f, Loader=yaml.FullLoader)
    return ['https://t.me/s/' + url.split("/")[-1] for url in data['tgchannel']]


@logger.catch
def get_channel_http(channel_url):
    """获取频道链接"""
    url_list = []
    try:
        response = requests.post(channel_url)
        data = response.text
        all_url_list = re.findall(RE_STR, data)
        filter_strings = ["//t.me/", "cdn-telegram.org"]
        url_list = [item for item in all_url_list if not any(fs in item for fs in filter_strings)]
        logger.info(f'{channel_url} 获取成功，数据量: {len(url_list)}')

        # 获取频道中的 SS, SSR, Vmess, Vless, Trojan 节点
        for item in url_list:
            if filter_base64(item):
                protocol_nodes.append(item)
    except Exception as e:
        logger.warning(f'{channel_url} 获取失败: {e}')
    return url_list


def filter_base64(text):
    """检查是否为 SS、SSR、Vmess 或 Trojan 类型链接"""
    return any(proto in text for proto in ['ss://', 'ssr://', 'vmess://', 'trojan://', 'vless://'])


@retry(tries=2)
@logger.catch
def url_check_valid(target, url, bar):
    """检查订阅链接是否有效"""
    with threading.Semaphore(THREAD_MAX_NUM):
        for check_url in CHECK_URL_LIST:
            try:
                url_encoded = quote(url, safe='')
                check_url_string = CHECK_NODE_URL_STR.format(check_url, target, url_encoded)
                res = requests.get(check_url_string, timeout=15)

                if res.status_code == 200:
                    airport_list.append(url)
                    break
            except Exception as e:
                logger.warning(f'解析失败: {url}, 错误: {e}')
        bar.update(1)


@retry(tries=2)
@logger.catch
def sub_check(url, bar):
    """检查订阅内容有效性"""
    headers = {'User-Agent': 'ClashforWindows/0.18.1'}
    with threading.Semaphore(THREAD_MAX_NUM):
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                process_subscription(res, url)
            bar.update(1)
        except requests.RequestException as e:
            logger.error(f'{url} 请求失败: {e}')


def process_subscription(res, url):
    """处理订阅响应，分类存储有效链接"""
    global new_sub_list, new_clash_list, new_v2_list, play_list
    try:
        # 有流量信息
        info = res.headers.get('subscription-userinfo')
        if info:
            upload, download, total = map(int, re.findall(r'\d+', info))
            unused = (total - upload - download) / 1024 / 1024 / 1024  # GB
            if unused > 0:
                new_sub_list.append(url)
                play_list.append(f'可用流量: {unused:.2f} GB - {url}')
    except Exception as e:
        # 判断是否为 Clash 或 V2
        if 'proxies:' in res.text:
            new_clash_list.append(url)
        elif filter_base64(res.text[:64]):
            new_v2_list.append(url)


def get_url_form_channel():
    """从配置文件中获取 TG 频道的订阅链接"""
    url_list = []
    for channel_url in get_config():
        url_list.extend(get_channel_http(channel_url))
    return url_list


def get_url_form_yaml(yaml_file):
    """从 YAML 文件中获取订阅链接"""
    dict_url = load_sub_yaml(yaml_file)
    all_urls = []
    all_urls.extend(dict_url['机场订阅'])
    all_urls.extend(dict_url['clash订阅'])
    all_urls.extend(dict_url['v2订阅'])
    all_urls.extend(dict_url['开心玩耍'])
    return re.findall(RE_STR, str(all_urls))


def write_protocol_nodes_to_txt():
    """将协议节点输出到文件"""
    if protocol_nodes:
        with open('./sub/protocol_nodes.txt', 'w', encoding='utf-8') as f:
            f.write("\n".join(protocol_nodes))
        logger.info(f'协议节点已写入到 protocol_nodes.txt 文件，共 {len(protocol_nodes)} 条')


def start_check(url_list):
    """开始检查所有的订阅链接"""
    logger.info('开始筛选订阅链接...')
    bar = tqdm(total=len(url_list), desc='订阅筛选：')
    thread_list = []
    for url in url_list:
        t = threading.Thread(target=sub_check, args=(url, bar))
        thread_list.append(t)
        t.setDaemon(True)
        t.start()
    for t in thread_list:
        t.join()
    bar.close()
    logger.info('筛选完成')


def write_url_list(url_list, path_yaml):
    """将有效的订阅链接写入文件"""
    url_file = path_yaml.replace('.yaml', '_url_check.txt')
    with open(url_file, 'w') as f:
        f.write('\n'.join(str(item) for item in url_list))


def write_sub_store(yaml_file):
    """将订阅链接和状态写入文件"""
    logger.info('写入 sub_store 文件...')
    dict_url = load_sub_yaml(yaml_file)
    play_list = dict_url['开心玩耍']
    sub_list = dict_url['机场订阅']

    url_file = yaml_file.replace('.yaml', '_sub_store.txt')
    with open(url_file, 'w') as f:
        f.write(f"-- play_list --\n\n{'\n'.join(play_list)}\n\n")
        f.write(f"-- sub_list --\n\n{'\n'.join(sub_list)}\n\n")


def sub_update(url_list, path_yaml):
    """更新订阅列表"""
    logger.info('开始更新订阅...')
    if not url_list:
        logger.info('没有需要更新的数据')
        return

    global new_sub_list, new_clash_list, new_v2_list, play_list
    new_sub_list, new_clash_list
