# -*- coding=utf-8
# 腾讯云对象存储 SDK
import sys
import os
import logging
from common.log import logger
import requests


def qcloud_get_cos_policy(groupx_url, ext_name) :
    # 传入文件后缀，后端生成随机的 COS 对象路径，并返回上传域名、PostObject 接口要用的 policy 签名
    # 参考服务端示例：https://github.com/tencentyun/cos-demo/server/post-policy/
    response = requests.get(f"{groupx_url}/v1/util/tencent-cos/post-policy/{ext_name}")
    if response.status_code == 200:
        return response.json().get('data')
    else:
        return f"Error: {response.status_code}"


def qcloud_upload_bytes(groupx_url, data) :
    files = {'file': data}  # 'file' 是服务器上接受文件的字段名
    cos_policy= qcloud_get_cos_policy(groupx_url, "jpg")
    formData = {
        "key": cos_policy['cosKey'],
        "policy": cos_policy['policy'], 
        "success_action_status": 200,
        'q-sign-algorithm': cos_policy['qSignAlgorithm'],
        'q-ak': cos_policy['qAk'],
        'q-key-time': cos_policy['qKeyTime'],
        'q-signature': cos_policy['qSignature'],
    }
    # 构建HTTP请求
    
    response = requests.post(
        "https://"+cos_policy['cosHost'],
        files=files,
        data=formData)

    # 处理响应
    if response.status_code == 200:
        logger.info("文件上传成功!")
        file_url = f"https://{cos_policy['cosHost']}/{cos_policy['cosKey'].replace('%2F', '/')}"
    else:
        logger.info(f"文件上传失败，状态码: {response.status_code}")
        logger.info(response.text)  # 如果有错误信息，可以打印出来
        file_url=""

    return file_url

def qcloud_upload_file(groupx_url, file_path) :
    files = {'file': open(file_path, 'rb')}  # 'file' 是服务器上接受文件的字段名
    file_name, file_extension = os.path.splitext(file_path)
    logger.info(f'文件名: {file_name}')
    logger.info(f'扩展名: {file_extension}')

    cos_policy= qcloud_get_cos_policy(groupx_url, file_extension[1:])
    formData = {
        "key": cos_policy['cosKey'],
        "policy": cos_policy['policy'], 
        "success_action_status": 200,
        'q-sign-algorithm': cos_policy['qSignAlgorithm'],
        'q-ak': cos_policy['qAk'],
        'q-key-time': cos_policy['qKeyTime'],
        'q-signature': cos_policy['qSignature'],
    }
    # 构建HTTP请求
    
    response = requests.post(
        "https://"+cos_policy['cosHost'],
        files=files,
        data=formData)

    # 处理响应
    if response.status_code == 200:
        logger.info("文件上传成功!")
        file_url = f"https://{cos_policy['cosHost']}/{cos_policy['cosKey'].replace('%2F', '/')}"
    else:
        logger.info(f"文件上传失败，状态码: {response.status_code}")
        logger.info(response.text)  # 如果有错误信息，可以打印出来
        file_url=""

    return file_url


