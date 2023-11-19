import requests
from common.log import logger
from plugins.plugin_chat2db.comm import makeGroupReq


class ApiGroupx:

    def __init__(self, host) -> None:
        self.groupxHostUrl = host

    def post_chat_record(self, account, msg_json):
        account = account.strip() if account else "0x0000000000000000000000000000000000000000"
        post_url = f"{self.groupxHostUrl}/v1/chat/{account}"
        logger.info("post url: {}".format(post_url))
        try:
            response = requests.post(
                post_url, json=msg_json, verify=False)
            logger.info(f"post chat to group api:{response.reason} len:{len(response.content)}")
            return response.json()
        except requests.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
            return None
        except Exception as err:
            logger.error(f"意外错误发生: {err}")
            return None
    # 设置我的医生
    def set_my_doctor_info(self, account, agent, doctor_name):
        if not account : return None

        post_url = f"{self.groupxHostUrl}/v1/chat/my-doctor/{account}"
        try:
            doctor_info = makeGroupReq(account, {
                'account': account,
                    'doctorName': doctor_name,
                    'agent': agent,
                })
            response = requests.post(
                post_url, json=doctor_info, verify=False)
            logger.info(f"post doctor to group api:{response.reason} len:{len(response.content)}")
            return response.json() if response.status_code == 200 else None
        except requests.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
            return None
        except Exception as err:
            logger.error()

    def post_friends(self, bot_account, bot_nickname, bot_id, friends):
        #好友处理
        try:
            json_data = makeGroupReq(bot_account, {
                "account": bot_account,
                'NickName': bot_nickname,
                'UserName': bot_id,
                'friends': friends
                })
            post_url = self.groupxHostUrl+'/v1/wechat/itchat/user/friends/'
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)

            print("post friends to groupx api:", response.reason)
            return response.json() if response.status_code == 200 else False
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP错误发生: {http_err}")
        except Exception as err:
            print(f"发生意外错误: {err}")
        return False;
    def post_groups(self, bot_account, bot_nickname, bot_id, groups):
        try:
            json_data = makeGroupReq(bot_account, {
                'account': bot_account,
                'NickName': bot_nickname,
                'UserName': bot_id,
                'groups': groups,
                })

            post_url = self.groupxHostUrl+'/v1/wechat/itchat/user/groups/'
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)
            return response.json()
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP错误发生: {http_err}")
        except Exception as err:
            print(f"发生意外错误: {err}")
        return False;
    def get_myknowledge(self, bot_account, data):
        try:
            json_data = makeGroupReq(bot_account, {
                'account': bot_account,
                'receiver': data.get('receiver', ''),
                'receiverName': data.get('receiver_name', ''),
                'isGroup': data.get('isgroup', False),
                'groupName': data.get('group_name', ''),
                'groupId': data.get('group_id', ''),
                'user': data.get('user', None),
                })

            post_url = self.groupxHostUrl+'/v1/user/friend/get-knowledge/'+bot_account
            logger.info("post url: {}".format(post_url))

            response = requests.post(post_url, json=json_data, verify=False)
            return response.json()
        except ZeroDivisionError:
            # 捕获并处理 ZeroDivisionError 异常
            print("好友列表, 错误发生")
        except requests.exceptions.HTTPError as http_err:
            print(f"HTTP错误发生: {http_err}")
        except Exception as err:
            print(f"发生意外错误: {err}")
        return False;
    def qcloud_get_cos_policy(self, ext_name) :
        # 传入文件后缀，后端生成随机的 COS 对象路径，并返回上传域名、PostObject 接口要用的 policy 签名
        # 参考服务端示例：https://github.com/tencentyun/cos-demo/server/post-policy/
        response = requests.get(f"{self.groupxHostUrl}/v1/util/tencent-cos/post-policy/{ext_name}")
        if response.status_code == 200:
            return response.json().get('data')
        else:
            return f"Error: {response.status_code}"
