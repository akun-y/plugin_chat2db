import os
import sqlite3
import time
import requests

from lib import itchat
from common.log import logger
from plugins.plugin_chat2db.api_tencent import ApiTencent
from plugins.plugin_chat2db.file_store import MyFileStory


class HeadImgManager(object):
    def __init__(self, conn):
        super().__init__()
        self.curdir = os.path.dirname(__file__)
        self.saveFolder = os.path.join(self.curdir, 'saved')
        self.conn = conn
        #创建用于记录avatar的表
        self._create_table_avatar()

        self.my_store = MyFileStory()
        self.tencent = ApiTencent()
    # 存储头像到腾讯cos
    def _create_table_avatar(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS avatar_records
                    (user_id TEXT, avatar TEXT,timestamp INTEGER,PRIMARY KEY (user_id))''')
        self.conn.commit()
    def _insert_record_avatar(self, user_id, avatar):
        c = self.conn.cursor()
        timestamp = int(time.time())
        logger.debug("[avatar_records] insert record: {} {} {}" .format(user_id, avatar, timestamp))
        c.execute("INSERT OR REPLACE INTO avatar_records VALUES (?,?,?)", (user_id, avatar,  timestamp))
        self.conn.commit()
    # 查询是否已经存储过头像
    def _get_records_avatar(self, user_id):
        c = self.conn.cursor()
        c.execute("SELECT avatar FROM avatar_records WHERE user_id=? ", (user_id,))
        result = c.fetchone()
        if result:
            return result[0]  # 提取 avatar 字段的值
        else:
            return None

    #优先从本地获取头像,如无,则远程获取并存储到本地
    def get_head_img_url(self, user_id, isGroup=False):
        avatar = self._get_records_avatar(user_id)
        if avatar:
            return avatar
        try:
            avatar_file = self.my_store.get_avatar_file(user_id)
            if avatar_file:
                avatar = self.tencent.qcloud_upload_file( avatar_file)
            else :
                if(isGroup) : fileBody = itchat.get_head_img(None, user_id)
                else : fileBody = itchat.get_head_img(user_id)

                avatar = self.tencent.qcloud_upload_bytes( fileBody)

                fn = self.my_store.save_avatar_file(user_id, fileBody)

            self._insert_record_avatar(user_id, avatar)

            return avatar
        except requests.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
            return None
        except Exception as err:
            logger.error(f"意外错误发生: {err}")
            return None
