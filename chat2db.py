# encoding:utf-8


import logging
import os
import sqlite3

import requests
from bridge.bridge import Bridge
import json
import time
from bot import bot_factory
from bridge.bridge import Bridge
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import check_contain, check_prefix
from channel.chat_message import ChatMessage
from config import conf
from lib import itchat
import plugins
from plugins import *
from common import const
from chatgpt_tool_hub.chains.llm import LLMChain
from chatgpt_tool_hub.models import build_model_params
from chatgpt_tool_hub.models.model_factory import ModelFactory
from chatgpt_tool_hub.prompts import PromptTemplate
import plugins
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from common.log import logger
from plugins import *
from plugins.plugin_chat2db.api_tentcent import qcloud_upload_bytes, qcloud_upload_file


@plugins.register(
    name="Chat2db",
    desire_priority=900,
    hidden=False,
    desc="存储及同步聊天记录",
    version="0.4.20231012",
    author="akun.yunqi",
)


class Chat2db(Plugin):

    def __init__(self):
        super().__init__()

        self.config = super().load_config()
        if not self.config:
            # 未加载到配置，使用模板中的配置
            self.config = self._load_config_template()
        if self.config:
            self.groupxHostUrl = self.config.get("groupx_host_url")

        self.model = conf().get("model")
        self.curdir = os.path.dirname(__file__)
        self.saveFolder = os.path.join(self.curdir, 'saved')
        self.saveSubFolders = {'webwxgeticon': 'icons', 'webwxgetheadimg': 'headimgs', 'webwxgetmsgimg': 'msgimgs',
                               'webwxgetvideo': 'videos', 'webwxgetvoice': 'voices', '_showQRCodeImg': 'qrcodes'}

        self.conn = sqlite3.connect(os.path.join(self.saveFolder, "chat2db.db"), check_same_thread=False)

        self._create_table()
        self._create_table_avatar()

        btype = Bridge().btype['chat']
        if btype not in [const.OPEN_AI, const.CHATGPT, const.CHATGPTONAZURE, const.BAIDU, const.LINKAI]:
            raise Exception("[Summary] init failed, not supported bot type")
        self.bot = bot_factory.create_bot(Bridge().btype['chat'])
        self.handlers[Event.ON_SEND_REPLY] = self.on_send_reply

        logger.info(f"[Chat2db] inited, config={self.config}")

    def _saveFile(self, filename, data, api=None):
        fn = filename
        if self.saveSubFolders[api]:
            dirName = os.path.join(self.saveFolder, self.saveSubFolders[api])
            if not os.path.exists(dirName):
                os.makedirs(dirName)
            fn = os.path.join(dirName, filename)
            logging.debug('Saved file: %s' % fn)
            with open(fn, 'wb') as f:
                f.write(data)
                f.close()
        return fn
    #从itchat获取头像
    def get_head_img_from_itchat(self, user_id):
        return itchat.get_head_img(user_id)

    #优先从本地获取头像,如无,则远程获取并存储到本地
    def get_head_img(self, user_id):
        avatar = self._get_records_avatar(user_id)
        if avatar:
            return avatar

        dirName = os.path.join(self.saveFolder, self.saveSubFolders['webwxgetheadimg'])
        avatar_file = os.path.join(dirName, f'headimg-{user_id}.png')
        if os.path.exists(avatar_file):
            avatar = qcloud_upload_file(self.groupxHostUrl, avatar_file)
        else :
            fileBody = self.get_head_img_from_itchat(user_id)
            avatar = qcloud_upload_bytes(self.groupxHostUrl, fileBody)

            fn = self._saveFile(avatar_file, fileBody, 'webwxgetheadimg')

        self._insert_record_avatar(user_id, avatar)

        return avatar
    def post_insert_record(self, cmsg,  conversation_id: str, action: str, jailbreak: str, content_type: str, internet_access: bool, role, content, response: str):
            #发送人头像
            if(cmsg.is_group) :
                user_id= cmsg.actual_user_id
                avatar = self.get_head_img(user_id)
                nickName = cmsg.actual_user_nickname
                wxGroupId = cmsg.from_user_id
                user={
                    'NickName': nickName,
                    'UserName': user_id,
                    'HeadImgUrl': avatar
                    }
            else :
                user_id= cmsg.from_user_id
                avatar = self.get_head_img(user_id)
                nickName = cmsg.from_user_nickname
                user= {**cmsg._rawmsg.user, 'HeadImgUrl': avatar}
                wxGroupId=''

            #接收人头像
            recvAvatar = self.get_head_img(cmsg.to_user_id)

            query_json = {
                "payload": {
                    'receiver': cmsg.to_user_id,
                    'receiverName': cmsg.to_user_nickname,
                    'receiverAvatar': recvAvatar,

                    'conversationId': conversation_id,
                    'action': action,
                    'model': self.model,
                    'internetAccess': internet_access,
                    'aiResponse': response,

                    'title': content,
                    'userName': nickName,
                    'userAvator': avatar,
                    'userId': user_id,
                    'message': content,
                    'messageId': cmsg.msg_id,
                    'messageType': content_type,

                    "wxReceiver": cmsg.to_user_id,
                    "wxUser": user,
                    "wxGroupId": wxGroupId,

                    "source": f"iKnow-on-wechat wx group {wxGroupId}" if cmsg.is_group else "iKnow-on-wechat wx " +"personal",
                },
                "params": {
                    "addr": "0xb8F33dAb7b6b24F089d916192E85D7403233328A",
                    "random": "a9a58d316a16206ca2529720d01f8a9d10779eb330902f4ec05cf358a3418a9f",
                    "nonce": "1a9b1b1d9e854196143504b776b65e9fb5c87fe4930466a8fe68763fa6e48aed",
                    "ts": "1680592645793",
                    "hash": "0xc324d54dc3f613b8b33ce60d3085b5fc16b9012fa1df733361b370fec663bc67",
                    "method": 2,
                    "msg": "Please sign this message"
                },
                "sig": "825ccf873738de91a77b0de19b0f2db7e549efcca36215743c184197173967d770b141201651b21d6d89d27dc8d6cde6ccdc3151af67ed29b5cdaed2cecf3950"
            }
            post_url = self.groupxHostUrl+'/v1/chat/0xb8F33dAb7b6b24F089d916192E85D7403233328A'
            logger.info("post url: {}".format(post_url))

            response = requests.post(
                post_url, json=query_json, verify=False)
            ret = response.text
            print("post chat to group api:", ret)
            return ret
    def _create_table(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS chat_records
                    (sessionid TEXT, msgid INTEGER, user TEXT,recv TEXT,reply TEXT, type TEXT, timestamp INTEGER, is_triggered INTEGER,
                    PRIMARY KEY (timestamp, msgid))''')

        # 后期增加了is_triggered字段，这里做个过渡，这段代码某天会删除
        c = c.execute("PRAGMA table_info(chat_records);")
        column_exists = False
        for column in c.fetchall():
            logger.debug("[Summary] column: {}" .format(column))
            if column[1] == 'is_triggered':
                column_exists = True
                break
        if not column_exists:
            self.conn.execute("ALTER TABLE chat_records ADD COLUMN is_triggered INTEGER DEFAULT 0;")
            self.conn.execute("UPDATE chat_records SET is_triggered = 0;")

        self.conn.commit()

    def _insert_record(self, session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered = 0):
        c = self.conn.cursor()
        logger.debug("[chat_records] insert record: {} {} {} {} {} {} {} {}" .format(session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered))
        c.execute("INSERT INTO chat_records VALUES (?,?,?,?,?,?,?,?)", (session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered))
        self.conn.commit()

    def _get_records(self, session_id, start_timestamp=0, limit=9999):
        c = self.conn.cursor()
        c.execute("SELECT * FROM chat_records WHERE sessionid=? and timestamp>? ORDER BY timestamp DESC LIMIT ?", (session_id, start_timestamp, limit))
        return c.fetchall()
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
     # 发送回复前
    def on_send_reply(self, e_context: EventContext):
        if e_context["reply"].type not in [ReplyType.TEXT]:
            return
        ctx = e_context['context']
        reply = e_context["reply"]
        recvMsg = ctx['msg'].content
        replyMsg = reply.content
        logger.debug("[save2db] on_decorate_reply. content: %s==>%s" % (recvMsg, replyMsg))

        cmsg : ChatMessage = e_context['context']['msg']
        username = None
        session_id = cmsg.from_user_id
        if conf().get('channel_type', 'wx') == 'wx' and cmsg.from_user_nickname is not None:
            session_id = cmsg.from_user_nickname # itchat channel id会变动，只好用群名作为session id

        if ctx.get("isgroup", False):
            username = cmsg.actual_user_nickname
            if username is None:
                username = cmsg.actual_user_id
        else:
            username = cmsg.from_user_nickname
            if username is None:
                username = cmsg.from_user_id

        is_triggered = False

        self._insert_record(session_id, cmsg.msg_id, username, recvMsg, replyMsg, str(ctx.type), cmsg.create_time, int(is_triggered))

        self.post_insert_record(cmsg, ctx.get('session_id'), "ask", "default", str(ctx.type), False, "user", recvMsg, replyMsg)
        e_context.action = EventAction.CONTINUE

    def get_help_text(self, **kwargs):
        help_text = "存储聊天记录到数据库"
        return help_text
