import re
import os
import yaml
import threading
import base64
import requests
from loguru import logger
from tqdm import tqdm
from retry import retry
from urllib.parse import quote, urlencode
from pre_check import pre_check, get_sub_all
import subprocess
import datetime

# Git 配置、同步和提交
def git_operations():
    try:
        # 配置 Git 用户名和邮箱
        subprocess.run(["git", "config", "--global", "user.name", "ro1oc"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "x2315340@outlook.com"], check=True)

        # 同步远程仓库
        subprocess.run(["git", "checkout", "main"], check=True)
        subprocess.run(["git", "fetch", "origin"], check=True)
        subprocess.run(["git", "pull", "origin", "main"], check=True)

        # 清理工作区：删除未追踪的文件
        subprocess.run(["git", "clean", "-fd"], check=True)
        subprocess.run(["git", "reset", "--hard"], check=True)

        # 提交本地更改
        # 查看本地更改
        status_result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        if status_result.stdout.strip():
            # 如果有更改，提交
            commit_message = "自动更新 " + datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", commit_message], check=True)
            subprocess.run(["git", "push", "origin", "main"], check=True)
        else:
            logger.info("没有未提交的更改。")
    except subprocess.CalledProcessError as e:
        logger.error(f"Git 操作失败: {e}")
        raise


# 当前订阅和节点列表
new_sub_list = []
new_clash_list = []
new_v2_list = []
play_list = []
airport_list = []

re_str = "https?://[-A-Za-z0-9+&@#/%?=~_|!:,.;]+[-A-Za-z0-9+&@#/%=~_|]"
thread_max_num = threading.Semaphore(32)  # 32线程

check_node_url_str = "https://{}/sub?target={}&url={}&insert=false&config=config%2FACL4SSR.ini"
check_url_list = ['api.dler.io', 'sub.xeton.dev', 'sub.id9.cc', 'sub.maoxiongnet.com']

@logger.catch
def load_sub_yaml(path_yaml):
    if os.path.isfile(path_yaml):
        with open(path_yaml, encoding="UTF-8") as f:
            dict_url = yaml.load(f, Loader=yaml.FullLoader)
    else:
        dict_url = {"机场订阅": [], "clash订阅": [], "v2订阅": [], "开心玩耍": []}
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
        all_url_list = re.findall(re_str, data)
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
                    res = requests.get(check_url_string, timeout=15)

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
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                global new_sub_list, new_clash_list, new_v2_list, play_list
                try:
                    info = res.headers['subscription-userinfo']
                    info_num = re.findall('\d+', info)
                    if info_num:
                        upload = int(info_num[0])
                        download = int(info_num[1])
                        total = int(info_num[2])
                        unused = (total - upload - download) / 1024 / 1024 / 1024
                        unused_rounded = round(unused, 2)
                        if unused_rounded > 0:
                            new_sub_list.append(url)
                            play_list.append('可用流量:' + str(unused_rounded) + ' GB                    ' + url)
                except:
                    try:
                        u = re.findall('proxies:', res.text)[0]
                        if u == "proxies:":
                            new_clash_list.append(url)
                    except:
                        try:
                            text = res.text[:64]
                            text = base64.b64decode(text)
                            text = str(text)
                            if filter_base64(text):
                                new_v2_list.append(url)
                        except:
                            pass
            else:
                pass
        try:
            start_check(url)
        except:
            pass
        bar.update(1)

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
    with open(yaml_file.replace('.yaml', '_sub_store.txt'), 'w') as f:
        f.write(write_str)

def today_sub():
    today = datetime.datetime.now().strftime('%Y-%m-%d')
    if not os.path.exists(today):
        os.mkdir(today)
    write_sub_store('sub.yaml')

def main():
    # 执行 Git 操作
    git_operations()
    
    # 执行订阅抓取
    url_list_from_channel = get_url_form_channel()
    url_list_from_yaml = get_url_form_yaml('sub.yaml')
    all_url_list = url_list_from_channel + url_list_from_yaml
    start_check(all_url_list)
    today_sub()

if __name__ == "__main__":
    main()
