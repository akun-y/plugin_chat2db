import requests
from common.log import logger
class ApiGroupx:
    
    def __init__(self,host) -> None:
        self.groupxHostUrl = host
        
    def post_chat_record(self, msg_json):
        post_url = self.groupxHostUrl+'/v1/chat/0xb8F33dAb7b6b24F089d916192E85D7403233328A'
        logger.info("post url: {}".format(post_url))
        try:
            response = requests.post(
                post_url, json=msg_json, verify=False)
            logger.info("post chat to group api:", response.text)
            return response.text
        except requests.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
            return None
        except Exception as err:
            logger.error(f"意外错误发生: {err}")
            return None