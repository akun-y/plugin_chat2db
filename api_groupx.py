from urllib.parse import quote

import requests

from common.log import logger
from config import conf
from plugins.plugin_comm.plugin_comm import EthZero, make_chat_sign_req


class ApiGroupx:
    def __init__(self, host=None) -> None:
        self.agent = conf().get("bot_account") or "123112312"
        if host:
            self.groupxHostUrl = host
        else:
            self.groupxHostUrl = conf().get("groupx_url") or 'https://groupx.mfull.cn'

    def post_chat_record(self, account, msg_json):
        account = (
            account.strip() if account else "0x0000000000000000000000000000000000000000"
        )
        post_url = f"{self.groupxHostUrl}/v1/chat/{account}"
        logger.info("post url: {}".format(post_url))
        try:
            response = requests.post(post_url, json=msg_json, verify=False)
            logger.info(
                f"post chat to group api:{response.reason} len:{len(response.content)}"
            )
            return response.json()
        except requests.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
            return None
        except Exception as err:
            logger.error(f"意外错误发生: {err}")
            return None

    # 获取我的减重信息
    def post_weight_loss(self, account, msg_json):
        # 未注册用户account为空
        url = f"{self.groupxHostUrl}/v1/health/weight-loss/{account}"

        return self._request(url, account, msg_json)
    def post_weight_loss_last_data(self, account, msg_json):
        # 未注册用户account为空
        url = f"{self.groupxHostUrl}/v1/health/weight-loss/last-data/{account}"

        return self._request(url, account, msg_json)

    # 设置我的医生
    def set_my_doctor_info(self, account, agent, doctor_name):
        if not account:
            return None

        post_url = f"{self.groupxHostUrl}/v1/chat/my-doctor/{account}"
        try:
            doctor_info = make_chat_sign_req(
                account,
                {
                    "account": account,
                    "doctorName": doctor_name,
                    "agent": agent,
                },
            )
            response = requests.post(post_url, json=doctor_info, verify=False)
            logger.info(
                f"post doctor to group api:{response.reason} len:{len(response.content)}"
            )
            return response.json() if response.status_code == 200 else None
        except requests.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
            return None
        except Exception as err:
            logger.error(f"set_my_doctor_info 意外错误发生: {err}")

    # 获取我的医生
    def get_itchat_user_info(self, account, user_id=None, user_name=None):
        # 未注册用户account为空
        url = f"{self.groupxHostUrl}/v1/wechat/itchat/user/get/{account or EthZero}"
        data = {
            "account": account,
            "agent": self.agent,
            "UserName": user_id,
            "NickName": user_name,
        }
        return self._request(url, account, data)

    # 获取我的医生
    def get_my_doctor_info(
        self, account, agent, user_id=None, user_name=None, doctor_name=None
    ):
        # 未注册用户account为空

        url = f"{self.groupxHostUrl}/v1/chat/my-doctor/get/{account}"
        data = {
            "account": account,
            "doctorName": doctor_name,
            "agent": agent,
            "wxUserId": user_id,
            "wxUserName": user_name,
        }
        return self._request(url, account, data)

    def get_doctor_of_group(self, group_id):
        url = f"{self.groupxHostUrl}/v1/chat/doctor-group/get/{group_id}"
        return self._request(url, EthZero)

    # 获取微信群信息
    def get_wxgroup_info(self, group_id):
        url = f"{self.groupxHostUrl}/v1/user/wxgroup/get/{group_id}"
        return self._request(url, EthZero)

    def _request(self, url, account, data=None):
        try:
            logger.info(f"_request url:{url}")
            if data:
                data_req = make_chat_sign_req(account, data)
                response = requests.post(url, json=data_req, verify=False)
            else:
                response = requests.get(url, verify=False)
            logger.info(f"_response:{response.reason} len:{len(response.content)}")
            return response.json() if response.status_code == 200 else None
        except requests.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
            return None
        except Exception as err:
            logger.error(f"set_my_doctor_info 意外错误发生: {err}")

    def post_friends(self, bot_account, bot_nickname, friends):
        # 好友处理
        try:
            json_data = make_chat_sign_req(
                bot_account,
                {
                    "account": bot_account,
                    "NickName": bot_nickname,
                    "friends": friends,
                },
            )
            post_url = self.groupxHostUrl + "/v1/wechat/itchat/user/friends/"
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)

            logger.info(f"post friends to groupx api:{ response.reason}")
            return response.json() if response.status_code == 200 else False
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            logger.error("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
        except Exception as err:
            logger.error(f"发生意外错误: {err}")
        return False

    def post_groups(self, bot_account, bot_nickname, groups):
        try:
            json_data = make_chat_sign_req(
                bot_account,
                {
                    "account": bot_account,
                    "NickName": bot_nickname,
                    "groups": groups,
                },
            )

            post_url = self.groupxHostUrl + "/v1/wechat/itchat/user/groups/"
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)
            return response.json()
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            logger.error("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
        except Exception as err:
            logger.error(f"发生意外错误: {err}")
        return False

    def get_myknowledge(self, bot_account, data):
        try:
            json_data = make_chat_sign_req(
                bot_account,
                {
                    "account": bot_account,
                    "receiver": data.get("receiver", ""),
                    "receiverName": data.get("receiver_name", ""),
                    "isGroup": data.get("isgroup", False),
                    "groupName": data.get("group_name", ""),
                    "groupId": data.get("group_id", ""),
                    "user": data.get("user", None),
                },
            )

            post_url = (
                self.groupxHostUrl + "/v1/user/friend/get-knowledge/" + bot_account
            )
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)
            return response.json()
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            logger.error("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
        except Exception as err:
            logger.error(f"发生意外错误: {err}")
        return False

    def qcloud_get_cos_policy(self, ext_name):
        # 传入文件后缀，后端生成随机的 COS 对象路径，并返回上传域名、PostObject 接口要用的 policy 签名
        # 参考服务端示例：https://github.com/tencentyun/cos-demo/server/post-policy/
        response = requests.get(
            f"{self.groupxHostUrl}/v1/util/tencent-cos/post-policy/{ext_name}"
        )
        if response.status_code == 200:
            return response.json().get("data")
        else:
            return f"Error: {response.status_code}"
