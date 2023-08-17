# encoding:utf-8


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

@plugins.register(
    name="Chat2db",
    desire_priority=900,
    hidden=False,
    desc="存储及同步聊天记录",
    version="0.3.20230817",
    author="akun.yunqi",
)


class Chat2db(Plugin):
    def __init__(self):
        super().__init__()
        try:
            self.groupxHostUrl = "https://groupx.mfull.cn" #conf().get("groupx_host_url")
            self.model = conf().get("model")
            curdir = os.path.dirname(__file__)
            db_path = os.path.join(curdir, "chat2db.db")
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            c = self.conn.cursor()
            c.execute('''CREATE TABLE IF NOT EXISTS chat_records
                        (sessionid TEXT, msgid INTEGER, user TEXT,recv TEXT,reply TEXT, type TEXT, timestamp INTEGER, is_triggered INTEGER,
                        PRIMARY KEY (sessionid, msgid))''')

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

            btype = Bridge().btype['chat']
            if btype not in [const.OPEN_AI, const.CHATGPT, const.CHATGPTONAZURE, const.BAIDU, const.LINKAI]:
                raise Exception("[Summary] init failed, not supported bot type")
            self.bot = bot_factory.create_bot(Bridge().btype['chat'])
            self.handlers[Event.ON_SEND_REPLY] = self.on_send_reply
            logger.info("[Summary] inited")
        except Exception as e:
            logger.warn("[Save2db] init failed, ignore or see https://github.com/akun-y/plugin_save2db .")
            raise e
    def post_insert_record(self, userName: str, userid: str,  conversation_id: str, action: str, jailbreak: str, content_type: str, internet_access: bool, role, content, response: str):
            logger.info("post_insert_record: {} {} {} {} {} {} {} {}" .format(userName, userid, conversation_id, action, content_type, role, content, response))
            query_json = {
                "payload": {
                    "userAvator": "https://pix.veryjack.com/i/2023/04/04/fsxnkv.webp",
                    "userName": userName,
                    "title": "iKonw-on-wechat",
                    "message": content,
                    "openId": userid,
                    "conversationId": conversation_id,
                    "action": action,
                    "jailbreak": jailbreak,
                    "contentType": content_type,
                    "internetAccess": internet_access,
                    "aiResponse": response,
                    "model": self.model
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
            logger.info("post url:",post_url)

            response = requests.post(
                post_url, json=query_json, verify=False)
            ret = response.text
            print("post chat to group api:", ret)
            return ret

    def _insert_record(self, session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered = 0):
        c = self.conn.cursor()
        logger.debug("[Summary] insert record: {} {} {} {} {} {} {} {}" .format(session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered))
        c.execute("INSERT OR REPLACE INTO chat_records VALUES (?,?,?,?,?,?,?,?)", (session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered))
        self.conn.commit()

    def _get_records(self, session_id, start_timestamp=0, limit=9999):
        c = self.conn.cursor()
        c.execute("SELECT * FROM chat_records WHERE sessionid=? and timestamp>? ORDER BY timestamp DESC LIMIT ?", (session_id, start_timestamp, limit))
        return c.fetchall()

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

        self.post_insert_record(username, cmsg.from_user_id, ctx.get('session_id'), "ask", "default", str(ctx.type), False, "user", recvMsg, replyMsg)
        e_context.action = EventAction.CONTINUE
    def get_help_text(self, **kwargs):
        help_text = "存储聊天记录到数据库"
        return help_text
