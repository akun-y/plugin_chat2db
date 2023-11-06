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
from common.tmp_dir import TmpDir

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
from plugins.plugin_chat2db.comm import EthZero, makeGroupReq
from plugins.plugin_chat2db.user_refresh_thread import UserRefreshThread
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from config import conf, load_config, global_config


@plugins.register(
    name="Chat2db",
    desire_priority=900,
    hidden=False,
    desc="存储及同步聊天记录",
    version="0.4.20231106",
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
            self.receiver =  self.config.get("account")
            self.systemName =  self.config.get("system_name")
            self.registerUrl = self.config.get("register_url")
            self.webQrCodeFile = self.config.get("web_qrcode_file")

        #全局配置
        self.channel_type = conf().get("channel_type", "wx")

        self.groupx = ApiGroupx(self.groupxHostUrl)

        self.model = conf().get("model")
        self.curdir = os.path.dirname(__file__)
        self.saveFolder = os.path.join(self.curdir, 'saved')
        self.saveSubFolders = {'webwxgeticon': 'icons', 'webwxgetheadimg': 'headimgs', 'webwxgetmsgimg': 'msgimgs',
                               'webwxgetvideo': 'videos', 'webwxgetvoice': 'voices', '_showQRCodeImg': 'qrcodes'}

        self.conn = sqlite3.connect(os.path.join(self.saveFolder, "chat2db.db"), check_same_thread=False)

        self._create_table()
        self._create_table_avatar()
        self._create_table_friends()
        self._create_table_groups()

        btype = Bridge().btype['chat']
        if btype not in [const.OPEN_AI, const.CHATGPT, const.CHATGPTONAZURE, const.BAIDU, const.LINKAI]:
            raise Exception("[Summary] init failed, not supported bot type")
        self.bot = bot_factory.create_bot(Bridge().btype['chat'])

        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_recv_message
        self.handlers[Event.ON_SEND_REPLY] = self.on_send_reply

        UserRefreshThread(self.conn, self.config)

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

        try:

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
        except requests.HTTPError as http_err:
            logger.error(f"HTTP错误发生: {http_err}")
            return None
        except Exception as err:
            logger.error(f"意外错误发生: {err}")
            return None
    def post_to_groupx(self, account, cmsg,  conversation_id: str, action: str, jailbreak: str, content_type: str, internet_access: bool, role, content, response: str):
            #发送人头像
            if(cmsg.is_group) :
                user_id= cmsg.actual_user_id
                avatar = self.get_head_img(user_id)
                nickName = cmsg.actual_user_nickname
                wxGroupId = cmsg.other_user_id
                wxGroupName = cmsg.other_user_nickname
                user={'account': account,
                    'NickName': nickName,
                    'UserName': user_id,
                    'HeadImgUrl': avatar
                    }
            else :
                user_id= cmsg.from_user_id
                avatar = self.get_head_img(user_id)
                nickName = cmsg.from_user_nickname
                user= { **cmsg._rawmsg.user, 'account': account, 'HeadImgUrl': avatar}
                wxGroupId=''
                wxGroupName='' #用于判断是否群聊

            #接收人头像
            recvAvatar = self.get_head_img(cmsg.to_user_id)
            source = f"{self.systemName} {self.channel_type}"
            query_json = makeGroupReq(account, {
                    'receiver': self.receiver,
                    'receiverName': cmsg.to_user_nickname,
                    'receiverAvatar': recvAvatar,

                    'conversationId': conversation_id,
                    'action': action,
                    'model': self.model,
                    'internetAccess': internet_access,
                    'aiResponse': response,

                    'userName': nickName,
                    'userAvatar': avatar,
                    'userId': user_id,
                    'message': content,
                    'messageId': cmsg.msg_id,
                    'messageType': content_type,

                    "wxReceiver": cmsg.to_user_id,
                    "wxUser": user,
                    "wxGroupId": wxGroupId,
                    "wxGroupName": wxGroupName,

                    "source": f"{source} group" if cmsg.is_group else f"{source} personal",
                })
            return self.groupx.post_chat_record(account, query_json)

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
        c.execute("INSERT OR REPLACE INTO chat_records VALUES (?,?,?,?,?,?,?,?)", (session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered))
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
    def _create_table_friends(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS friends_records
                    (selfUserName TEXT, selfNickName TEXT, selfHeadImgUrl TEXT,
                    UserName TEXT, NickName TEXT, HeadImgUrl TEXT,
                    PRIMARY KEY (NickName))''')
        self.conn.commit()
    def _create_table_groups(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS groups_records
                    (selfUserName TEXT, selfNickName TEXT, selfDisplayName TEXT,
                    UserName TEXT, NickName TEXT, HeadImgUrl TEXT,
                    PYQuanPin TEXT, EncryChatRoomId TEXT,
                    PRIMARY KEY (NickName))''')
        self.conn.commit()
    def _send_reg_msg(self, UserName, ActNickName):
        msg = f'首次使用,请点击链接或扫码登录后再次使用 \n {self.registerUrl}'
        msg = f'@{ActNickName} {msg}' if ActNickName else msg
        itchat.send_msg(msg, toUserName=UserName)
        itchat.send_image(fileDir=self.webQrCodeFile, toUserName=UserName)

    #收到消息 ON_RECEIVE_MESSAGE
    def on_recv_message(self, e_context: EventContext):
        ctx = e_context['context']
        if ctx.get("isgroup", False): return # 群聊天不处理图片
        if ctx.type not in [ContextType.IMAGE]: return #只处理图片

        # 单聊时发送的图片给作为消息发给服务器
        cmsg : ChatMessage = ctx['msg']
        logger.info("[save2db] on_recv_message. content: %s" % cmsg.content)

        user = cmsg.from_user_nickname
        session_id = ctx.get('session_id')

        eth_addr = cmsg._rawmsg.User.RemarkName
        logger.info("[save2db] on_recv_message. eth_addr: %s" % eth_addr)
        #wechat_id = cmsg.from_contact_id
        #print(wechat_id)
        #wechat_id = cmsg.talker().contact_id
        #print(wechat_id)

        self._insert_record(session_id, cmsg.msg_id, user, cmsg.content, "", str(ctx.type), cmsg.create_time)

        # 上传图片到腾讯cos
        # 文件处理
        ctx.get("msg").prepare()
        file_path = ctx.content
        img_url ="12"
        img_file = os.path.abspath(cmsg.content)
        if os.path.exists(img_file):
            img_url = qcloud_upload_file(self.groupxHostUrl, img_file)

        self.post_to_groupx('', cmsg, session_id, "recv", "default", str(ctx.type), False, "user",  img_url, '')
        e_context.action = EventAction.CONTINUE
     # 发送回复前
    def on_send_reply(self, e_context: EventContext):
        if e_context["reply"].type not in [ReplyType.TEXT]:
            return
        ctx = e_context['context']
        reply = e_context["reply"]
        recvMsg = ctx.content
        replyMsg = reply.content
        logger.debug("[save2db] on_decorate_reply. content: %s==>%s" % (recvMsg, replyMsg))

        cmsg : ChatMessage = e_context['context']['msg']

        session_id = ctx.get('session_id')
        isGroup = ctx.get("isgroup", False)

        username = cmsg.actual_user_nickname if isGroup else cmsg.from_user_nickname
        userid = cmsg.actual_user_id if isGroup else cmsg.from_user_id
        act_user = itchat.update_friend(userid)
        account = act_user.RemarkName

        try:
            self._insert_record(session_id, cmsg.msg_id, username, recvMsg, replyMsg, str(ctx.type), cmsg.create_time)

            result = self.post_to_groupx(account, cmsg, session_id, "ask", "default", str(ctx.type), False, "user", recvMsg, replyMsg)
            if (result is not None):
                logger.info(result)
                #ethAddr存在到RemarkName 中
                retAccount = result.get('account', None)
                if retAccount is None or retAccount == EthZero :
                    self._send_reg_msg(cmsg.from_user_id, username if isGroup else None)
                    e_context.action = EventAction.BREAK_PASS
                    return
                if(retAccount and account != retAccount):
                    #更新account到 RemarkName中
                    itchat.set_alias( act_user.UserName, retAccount)
                    act_user.update()
                    itchat.dump_login_status()

        except Exception as e:
            logger.error("on_send_reply: {}".format(e))

        e_context.action = EventAction.CONTINUE

    def get_help_text(self, **kwargs):
        help_text = "存储聊天记录到数据库"
        return help_text
