from libs.lib_file_operate.file_path import file_is_exist


def file_type(file_path):
    """判断文件类型gbk、utf-8"""
    file_type = "gbk"
    try:
        data = open(file_path, 'r', encoding=file_type)
        data.read()
    except UnicodeDecodeError:
        file_type = "utf-8"
    else:
        data.close()
    return file_type


def file_encoding(file_path: str):
    """
    获取文件编码类型

    :param file_path: 文件路径
    :return:
    """
    if file_is_exist(file_path):
        with open(file_path, 'rb') as f:
            return string_encoding(f.read())
    else:
        return "utf-8"


def string_encoding(data: bytes):
    # 简单的判断文件编码类型
    # 说明：UTF兼容ISO8859-1和ASCII，GB18030兼容GBK，GBK兼容GB2312，GB2312兼容ASCII
    CODES = ['UTF-8', 'GB18030', 'BIG5']
    # UTF-8 BOM前缀字节
    UTF_8_BOM = b'\xef\xbb\xbf'

    """
    获取字符编码类型

    :param data: 字节数据
    :return:
    """
    # 遍历编码类型
    for code in CODES:
        try:
            data.decode(encoding=code)
            if 'UTF-8' == code and data.startswith(UTF_8_BOM):
                return 'UTF-8-SIG'
            return code
        except UnicodeDecodeError:
            continue
    return 'unknown'