#!/usr/bin/env python
# encoding: utf-8
import hashlib
import re
import sys
import time
import urllib
from binascii import b2a_hex

import chardet
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

from libs.lib_log_print.logger_printer import output
from libs.lib_requests.requests_const import *
from urllib.parse import urlparse

requests.packages.urllib3.disable_warnings()
sys.dont_write_bytecode = True  # 设置不生成pyc文件


# 判断列表内的元素是否存在有包含在字符串内的
def list_ele_in_str(list_=None, str_=None, default=False):
    if list_ is None:
        list_ = []

    flag = False
    if list_:
        for ele in list_:
            if ele in str_:
                flag = True
                break
    else:
        flag = default
    return flag


# 处理错误消息
def show_requests_error(url_info, common_error_list, module_name, error_info):
    # 把常规错误的关键字加入列表common_error_list内,列表为空时都作为非常规错误处理
    common_error_flag = list_ele_in_str(common_error_list, str(error_info), default=False)
    if common_error_flag:
        output(f"[-] 当前目标 {url_info} COMMON ERROR ON Acquire [{module_name}]: [{error_info}]", level="error")
    else:
        output(f"[-] 当前目标 {url_info} OTHERS ERROR ON Acquire [{module_name}]: [{error_info}]", level="error")


# 支持重试等操作的请求库
def requests_plus(req_url,
                  req_method='GET',
                  req_headers=None,
                  req_data=None,
                  req_proxies=None,
                  req_timeout=10,
                  verify_ssl=False,
                  req_allow_redirects=False,
                  req_stream=False,
                  retry_times=0,
                  const_sign=None,
                  add_host_header=None,
                  add_refer_header=None,
                  ignore_chinese_error_msg=None):

    # 设置本请求默认标记 # const_sign 原样返回输入的值, 用来标记线程的信息
    # const_sign = const_sign if const_sign else time.time()
    const_sign = const_sign or str(time.time())

    # 设置默认请求头
    if not req_headers:
        req_headers = {'User-Agent': 'Mozilla/4.0 (compatible; MSIE 5.5; Windows NT)',
                       'Accept-Encoding': '' }

    # 需要动态添加host字段
    if add_host_header:
        req_headers["Host"] = urlparse(req_url).netloc

    # 需要动态添加refer字段
    if add_refer_header:
        req_headers["Referer"] = req_url

    # 设置需要接受的参数的默认值 #如果返回结果是默认值,说明程序异常没有获取到
    resp_status = DEFAULT_RESP_DICT[RESP_STATUS]  # 响应状态码 赋值默认值 NUM_MINUS
    resp_bytes_head = DEFAULT_RESP_DICT[RESP_BYTES_HEAD]  # 响应头字节 赋值默认值 NULL_BYTES
    resp_content_length = DEFAULT_RESP_DICT[RESP_CONTENT_LENGTH]  # 响应内容长度 赋值默认值 NUM_MINUS
    resp_text_size = DEFAULT_RESP_DICT[RESP_TEXT_SIZE]  # 响应内容大小 赋值默认值 NUM_MINUS
    resp_text_title = DEFAULT_RESP_DICT[RESP_TEXT_TITLE]  # 响应文本标题 赋值默认值 NULL_TITLE
    resp_text_hash = DEFAULT_RESP_DICT[RESP_TEXT_HASH]  # 响应文本HASH 赋值默认值 NULL_TEXT_HASH
    resp_redirect_url = DEFAULT_RESP_DICT[RESP_REDIRECT_URL]  # 响应重定向URL 赋值默认值 NULL_REDIRECT_URL

    try:
        resp = request_retry(req_url=req_url,
                             req_method=req_method,
                             req_headers=req_headers,
                             req_data=req_data,
                             req_proxies=req_proxies,
                             req_timeout=req_timeout,
                             verify_ssl=verify_ssl,
                             req_allow_redirects=req_allow_redirects,
                             req_stream=req_stream)

        resp_status = resp.status_code

        # 排除由于代理服务器导致的访问BUG
        if list_ele_in_str(ERROR_PAGE_KEY, resp.text.lower(), False):
            output("[!] 当前由于代理服务器问题导致响应状态码错误...Fixed...", level="error")
            resp_status = NUM_MINUS
    except Exception as error:
        # 当错误原因时一般需要重试的错误时,直接忽略输出,进行访问重试
        current_module = RESP_STATUS
        # 把常规错误的关键字加入列表内,列表为空时都作为非常规错误处理
        module_common_error_list = ["retries",
                                    "Read timed out",
                                    "codec can't encode",
                                    "No host supplied",
                                    "Exceeded 30 redirects",
                                    'WSAECONNRESET']
        show_requests_error(req_url, module_common_error_list, current_module, error)
        # 如果是数据编码错误,需要进行判断处理
        if "codec can't encode" in str(error):
            # 如果是数据编码错误,就不再进行尝试 ,返回固定结果状态码
            # 'latin-1' codec can't encode characters in position 17-18: ordinal not in range(256)
            if ignore_chinese_error_msg:
                # 不需要重试的结果 设置resp_status标记为1,
                resp_status = NUM_ONE
                output(f"[-] 当前目标 {req_url} 中文数据编码错误,但是已经开启中文编码处理功能,忽略本次错误!!!", level="debug")
            else:
                # 需要手动访问重试的结果
                output(f"[-] 当前目标 {req_url} 中文数据编码错误,需要针对中文编码进行额外处理,返回固定结果!!!", level="error")
        elif "No host supplied" in str(error):
            # 不需要重试的结果 设置resp_status标记为1,
            resp_status = NUM_ONE
            output(f"[-] 当前目标 {req_url} 格式输入错误,忽略本次结果!!!", level="error")
        else:
            # 如果服务器没有响应,但是也有可能存在能访问的URL,因此不能简单以状态码判断结果
            # 如果是其他访问错误,就进程访问重试
            if retry_times > 0:
                output(f"[-] 当前目标 {req_url} 开始进行倒数第 {retry_times} 次重试, TIMEOUT * 1.5...", level="error")
                return requests_plus(req_url=req_url,
                                     req_method=req_method,
                                     req_headers=req_headers,
                                     req_data=req_data,
                                     req_proxies=req_proxies,
                                     req_timeout=req_timeout * 1.5,
                                     verify_ssl=verify_ssl,
                                     req_allow_redirects=req_allow_redirects,
                                     retry_times=retry_times - 1,
                                     const_sign=const_sign,
                                     add_host_header=add_host_header,
                                     add_refer_header=add_refer_header,
                                     ignore_chinese_error_msg=ignore_chinese_error_msg
                                     )

            else:
                # 如果重试次数为小于0,返回固定结果-1
                output(f"[-] 当前目标 {req_url}  剩余重试次数为0,返回固定结果,需要后续手动进行验证...", level="error")
    else:
        # 当获取到响应结果时,获取三个响应关键匹配项目
        #############################################################
        # 1、resp_bytes_head 获取响应内容的前十字节 # 需要流模式才能获取
        current_module = RESP_BYTES_HEAD
        try:
            resp_bytes_head = b2a_hex(resp.raw.read(10)).decode()
            if resp_bytes_head.strip() == "":
                resp_bytes_head = BLANK_BYTES
            else:
                pass
                # output(RESP_BYTES_HEAD, resp_bytes_head) #需要流模式才能获取resp_bytes_head
        except Exception as error:
            # 当错误原因时一般需要重试的错误时,直接忽略输出,进行访问重试
            module_common_error_list = []  # 把常规错误的关键字加入列表内,列表为空时都作为非常规错误处理
            show_requests_error(req_url, module_common_error_list, current_module, error)
        #############################################################
        # 2、resp_content_length 获取响应的content_length头部
        current_module = RESP_CONTENT_LENGTH
        try:
            resp_content_length = int(str(resp.headers.get('Content-Length')))
        except Exception as error:
            module_common_error_list = ["invalid literal for int()"]  # 把常规错误的关键字加入列表内,列表为空时都作为非常规错误处理
            show_requests_error(req_url, module_common_error_list, current_module, error)
        #############################################################
        # 3、resp_text_size 获取响应内容实际长度,如果响应长度过大就放弃读取,从resp_content_length进行读取
        current_module = RESP_TEXT_SIZE

        if resp_content_length >= 1024000 * 5:
            # 结果文本长度太大,不进行实际获取
            resp_text_size = resp_content_length
        else:
            try:
                resp_text_size = len(resp.text)
            except Exception as error:
                module_common_error_list = ["content-encoding: gzip", "Connection broken: IncompleteRead"]
                # 把常规错误的关键字加入列表内,列表为空时都作为非常规错误处理
                # Received response with content-encoding: gzip, but failed to decode it. # 返回gzip不解压报错
                # ('Connection broken: IncompleteRead(22 bytes read)', IncompleteRead(22 bytes read)) # 使用流模式导致不完全读取报错
                show_requests_error(req_url, module_common_error_list, current_module, error)
        #############################################################
        # 4、resp_text_title 获取网页标题,如果resp_text_size获取到了就直接获取
        current_module = RESP_TEXT_TITLE
        # 如果resp_text_size没有获取到,说明没有resp_text 不参考上级处理结果
        encode_content = ""
        try:
            if resp_content_length >= 1024000 * 5:
                # 如果返回值太大,就忽略获取结果
                resp_text_title = IGNORE_TITLE
            else:
                # 解决响应解码问题
                # 0、使用import chardet
                encode_content = resp.content  # output(type(resp.content)) # bytes类型
                code_result = chardet.detect(encode_content)  # 利用chardet来检测这个网页使用的是什么编码方式
                # output(encode_content,code_result)  # 扫描到压缩包时,没法获取编码结果
                # 取code_result字典中encoding属性，如果取不到，那么就使用utf-8
                encoding = code_result.get("encoding", "utf-8")
                if not encoding: encoding = "utf-8"
                encode_content = encode_content.decode(encoding, 'replace')
                # 1、字符集编码，可以使用r.encoding='xxx'模式，然后再r.text()会根据设定的字符集进行转换后输出。
                # resp.encoding='utf-8'
                # output(resp.text)，

                # 2、请求后的响应response,先获取bytes 二进制类型数据，再指定encoding，也可
                # output(resp.content.decode(encoding="utf-8"))

                # 3、使用apparent_encoding可获取程序真实编码
                # resp.encoding = resp.apparent_encoding
                # encode_content = req.content.decode(encoding, 'replace').encode('utf-8', 'replace')
                # encode_content = resp.content.decode(resp.encoding, 'replace')  # 如果设置为replace，则会用?取代非法字符；
                re_find_result_list = re.findall(r"<title.*?>(.+?)</title>", encode_content)
                resp_text_title = ",".join(re_find_result_list)
                # 解决所有系统下字符串无法编码输出的问题,比如windows下控制台gbk的情况下,不能gbk解码就是BUG
                # output(f"当前控制台输出编码为:{sys.stdout.encoding}", level="error")
                # 解决windows下韩文无法输出的问题,如果不能gbk解码就是window BUG
                # if sys.platform.lower().startswith('win'):
                try:
                    resp_text_title.encode(sys.stdout.encoding)
                except Exception as error:
                    resp_text_title = urllib.parse.quote(resp_text_title.encode('utf-8'))
                    output(f"[!] 字符串使用当前控制台编码 {sys.stdout.encoding} 编码失败,"
                           f"自动转换为UTF-8型URL编码 {resp_text_title}, "
                           f"ERROR:{error}",
                           level="error")
                if resp_text_title.strip() == "":
                    resp_text_title = BLANK_TITLE
        except Exception as error:
            module_common_error_list = []  # 把常规错误的关键字加入列表内,列表为空时都作为非常规错误处理
            show_requests_error(req_url, module_common_error_list, current_module, error)
        #############################################################
        # 5、resp_text_hash 获取网页内容hash
        current_module = RESP_TEXT_HASH
        # 如果resp_text_title是空值,说明结果存在问题
        if resp_text_title != NULL_TITLE and encode_content != "":
            try:
                if resp_content_length >= 1024000 * 5:
                    # 如果返回值太大,就忽略获取结果
                    resp_text_hash = IGNORE_TEXT_HASH
                else:
                    resp_text_hash = hashlib.md5(resp.content).hexdigest()
            except Exception as error:
                module_common_error_list = []  # 把常规错误的关键字加入列表内,列表为空时都作为非常规错误处理
                show_requests_error(req_url, module_common_error_list, current_module, error)
        #############################################################
        # 6、resp_redirect_url 获取重定向后的URL
        current_module = RESP_REDIRECT_URL
        try:
            if req_url.strip() == resp_redirect_url.strip():
                resp_redirect_url = RAW_REDIRECT_URL
            else:
                resp_redirect_url = resp.url.strip()
        except Exception as error:
            module_common_error_list = []  # 把常规错误的关键字加入列表内,列表为空时都作为非常规错误处理
            show_requests_error(req_url, module_common_error_list, current_module, error)
    finally:
        # 最终合并所有获取到的结果
        current_resp_dict = {
            REQ_URL: req_url,  # 请求的URL
            CONST_SIGN: const_sign,  # 请求的标记,自定义标记,原样返回
            RESP_STATUS: resp_status,  # 响应状态码
            RESP_BYTES_HEAD: resp_bytes_head,  # 响应头字节
            RESP_CONTENT_LENGTH: resp_content_length,  # 响应内容长度
            RESP_TEXT_SIZE: resp_text_size,  # 响应内容大小
            RESP_TEXT_TITLE: resp_text_title,  # 响应文本标题
            RESP_TEXT_HASH: resp_text_hash,  # 响应文本HASH
            RESP_REDIRECT_URL: resp_redirect_url,  # 响应重定向URL
        }
        output(f"[*] 当前目标 {req_url} 请求返回结果集合:{current_resp_dict}")
        return current_resp_dict


# 支持基本重试的请求操作
def request_retry(req_url,
                  req_method='GET',
                  req_headers=None,
                  req_data=None,
                  req_proxies=None,
                  req_timeout=10,
                  verify_ssl=False,
                  req_allow_redirects=False,
                  retry_times=0,
                  req_stream=False
                  ):
    retry_strategy = Retry(
        total=retry_times,  # 重试的最大次数
        backoff_factor=1,  # 重试的延迟时间因子 默认值为0，表示不延迟。
        status_forcelist=[429, 500, 502, 503, 504],  # 需要强制重试的HTTP状态码列表。
        allowed_methods=["HEAD", "GET", "OPTIONS"],  # 允许进行重试的HTTP请求方法列表。
        connect=5,  # 连接超时时间
        read=5,  # 读取超时时间
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)
    session = requests.Session()
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    try:
        response = session.request(url=req_url,
                                   method=req_method,
                                   headers=req_headers,
                                   data=req_data,
                                   proxies=req_proxies,
                                   timeout=req_timeout,
                                   verify=verify_ssl,
                                   allow_redirects=req_allow_redirects,
                                   stream=req_stream)
        return response
    except Exception as error:
        output(f"error:{error}")
        return None

# if __name__ == '__main__':
#     target_url_path_list = ['http://www.baidu.com/201902.iso',
#                             'http://www.baidu.com/%%path%%_4_.gz',
#                             'http://www.baidu.com/2013.7z',
#                             'http://www.baidu.com/201804.rar',
#                             'http://www.baidu.com/201706.z']
#
#     # 导入PY3多线程池模块
#     from concurrent.futures import ThreadPoolExecutor, as_completed
#
#     threads_count = 3  # 线程池线程数
#     with ThreadPoolExecutor(max_workers=threads_count) as pool:
#         all_task = []
#         for url in target_url_path_list:
#             # 把请求任务加入线程池
#             task = pool.submit(requests_plus, req_url=url)
#             all_task.append(task)
#         # 输出线程返回的结果
#         for future in as_completed(all_task):
#             output(future, future.result())