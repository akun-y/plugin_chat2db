import requests
from common.log import logger


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
