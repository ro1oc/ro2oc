import re
import os
import yaml
import threading
import base64
import requests
import datetime

from loguru import logger
from tqdm import tqdm
from retry import retry
from urllib.parse import quote, urlencode
from pre_check import pre_check, get_sub_all

# 订阅链接相关的全局变量
new_sub_list = []
new_clash_list = []
new_v2_list = []
play_list = []
airport_list = []

# 正则匹配订阅链接的模式
re_str = "https?://[-A-Za-z0-9+&@#/%?=~_|!:,.;]+[-A-Za-z0-9+&@#/%=~_|]"
# 控制最大并发数为32
thread_max_num = threading.Semaphore(32)

# 检查节点的URL格式
check_node_url_str = "https://{}/sub?target={}&url={}&insert=false&config=config%2FACL4SSR.ini"
check_url_list = ['api.dler.io', 'sub.xeton.dev', 'sub.id9.cc', 'sub.maoxiongnet.com']

@logger.catch
def load_sub_yaml(path_yaml):
    if os.path.isfile(path_yaml):  # 文件存在
        with open(path_yaml, encoding="UTF-8") as f:
            dict_url = yaml.load(f, Loader=yaml.FullLoader)
    else:
        dict_url = {
            "机场订阅": [],
            "clash订阅": [],
            "v2订阅": [],
            "开心玩耍": []
        }
    logger.info('读取文件成功')
    return dict_url

@logger.catch
def get_config():
    with open('./config.yaml', encoding="UTF-8") as f:
        data = yaml.load(f, Loader=yaml.FullLoader)
    list_tg = data['tgchannel']
    new_list = []
    for url in list_tg:
        a = url.split("/")[-1]
        url = 'https://t.me/s/' + a
        new_list.append(url)
    return new_list

@logger.catch
def get_channel_http(channel_url):
    url_list = []
    try:
        with requests.post(channel_url) as resp:
            data = resp.text
        all_url_list = re.findall(re_str, data)  # 使用正则表达式查找订阅链接并创建列表
        filter_string_list = ["//t.me/", "cdn-telegram.org"]
        url_list = [item for item in all_url_list if not any(filter_string in item for filter_string in filter_string_list)]
        logger.info(channel_url + '\t获取成功\t数据量:' + str(len(url_list)))
    except Exception as e:
        logger.warning(channel_url + '\t获取失败')
        logger.error(channel_url + e)
    finally:
        return url_list

def filter_base64(text):
    ss = ['ss://', 'ssr://', 'vmess://', 'trojan://']
    for i in ss:
        if i in text:
            return True
    return False

@logger.catch
def url_check_valid(target, url, bar):
    with thread_max_num:
        @retry(tries=2)
        def start_check_url(url):
            url_encode = quote(url, safe='')
            global airport_list
            for check_url in check_url_list:
                try:
                    check_url_string = check_node_url_str.format(check_url, target, url_encode)
                    res = requests.get(check_url_string, timeout=15)  # 设置超时为15秒
                    if res.status_code == 200:
                        airport_list.append(url)
                        break
                except Exception as e:
                    pass
        try:
            start_check_url(url)
        except:
            pass
        bar.update(1)

@logger.catch
def sub_check(url, bar):
    headers = {'User-Agent': 'ClashforWindows/0.18.1'}
    with thread_max_num:
        @retry(tries=2)
        def start_check(url):
            res = requests.get(url, headers=headers, timeout=10)  # 设置超时
            if res.status_code == 200:
                global new_sub_list, new_clash_list, new_v2_list, play_list
                try:  # 检查是否包含流量信息
                    info = res.headers['subscription-userinfo']
                    info_num = re.findall(r'\d+', info)
                    if info_num:
                        upload = int(info_num[0])
                        download = int(info_num[1])
                        total = int(info_num[2])
                        unused = (total - upload - download) / 1024 / 1024 / 1024
                        unused_rounded = round(unused, 2)
                        if unused_rounded > 0:
                            new_sub_list.append(url)
                            play_list.append(f'可用流量: {unused_rounded} GB  {url}')
                except:
                    # 判断是否为 Clash 配置
                    try:
                        if 'proxies:' in res.text:
                            new_clash_list.append(url)
                    except:
                        # 判断是否为 V2Ray 配置
                        try:
                            text = res.text[:64]
                            text = base64.b64decode(text)
                            text = str(text)
                            if filter_base64(text):  # SS/SSR/V2Ray/Trojan
                                new_v2_list.append(url)
                        except:
                            pass
            bar.update(1)

        try:
            start_check(url)
        except:
            pass
        bar.update(1)

def save_nodes_to_file(nodes):
    today_date = datetime.datetime.today().strftime('%Y-%m-%d')
    directory = 'today_sub'
    
    # 创建目录
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    # 写入文件
    file_path = os.path.join(directory, f"{today_date}.txt")
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(nodes))
    
    logger.info(f"节点已保存到 {file_path}")

def get_url_form_channel():
    list_tg = get_config()
    logger.info('读取config成功')
    url_list = []

    for channel_url in list_tg:
        temp_list = get_channel_http(channel_url)
        if len(temp_list) > 0:
            url_list.extend(temp_list)

    return url_list

def get_url_form_yaml(yaml_file):
    dict_url = load_sub_yaml(yaml_file)

    sub_list = dict_url['机场订阅']
    clash_list = dict_url['clash订阅']
    v2_list = dict_url['v2订阅']
    play_list = dict_url['开心玩耍']

    url_list = []
    url_list.extend(sub_list)
    url_list.extend(clash_list)
    url_list.extend(v2_list)
    url_list.extend(play_list)
    url_list = re.findall(re_str, str(url_list))

    return url_list

def start_check(url_list):
    logger.info('开始筛选---')
    
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
    url_file = path_yaml.replace('.yaml', '_url_check.txt')
    list_str = '\n'.join(str(item) for item in url_list)
    with open(url_file, 'w') as f:
        f.write(list_str)

def write_sub_store(yaml_file):
    logger.info('写入 sub_store 文件--')
    dict_url = load_sub_yaml(yaml_file)

    play_list = dict_url['开心玩耍']
    url_list = []
    play_url_list = re.findall(re_str, str(play_list))
    title_str = "-- play_list --\n\n\n"
    play_list_str = '\n'.join(str(item) for item in play_url_list)
    write_str = title_str + play_list_str

    sub_list = dict_url['机场订阅']
    sub_url_list = re.findall(re_str, str(sub_list))
    title_str = "\n\n\n-- sub_list --\n\n\n"
    play_list_str = '\n'.join(str(item) for item in sub_url_list)
    write_str = write_str + title_str + play_list_str

    url_file = yaml_file.replace('.yaml', '_sub_store.txt')
    with open(url_file, 'w') as f:
        f.write(write_str)

    write_url_config(url_file, play_url_list, 'loon')
    write_url_config(url_file, sub_url_list, 'clash')

def write_url_config(url_file, url_list, target):
    logger.info('检测订阅节点有效性')
    global airport_list
    airport_list = []

    bar = tqdm(total=len(url_list), desc='节点检测：')
    thread_list = []
    for url in url_list:
        t = threading.Thread(target=url_check_valid, args=(target, url, bar))
        thread_list.append(t)
        t.setDaemon(True)
        t.start()
    for t in thread_list:
        t.join()
    bar.close()
    logger.info('检测订阅节点有效性完成')

    write_str = '\n'.join(str(item) for item in airport_list)
    with open(url_file, 'a') as f:
        f.write(write_str)

def update_today_sub():
    url_list = get_url_form_channel()
    path_yaml = pre_check()
    sub_update(url_list, path_yaml)

    # 收集所有抓取到的节点
    all_nodes = []
    all_nodes.extend(new_sub_list)
    all_nodes.extend(new_clash_list)
    all_nodes.extend(new_v2_list)
    all_nodes.extend(play_list)

    # 移除重复节点
    all_nodes = list(set(all_nodes))

    # 保存节点到文件
    save_nodes_to_file(all_nodes)

# 主程序入口
if __name__ == '__main__':
    update_today_sub()
    merge_sub()
