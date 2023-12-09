# encoding:utf-8
import logging
import os
import sqlite3
import time
import traceback
from memory_profiler import profile
from datetime import datetime, timedelta

import plugins
from plugins.plugin_chat2db.chat2db_reply import CustomReply
import requests
from bot import bot_factory
from bridge.bridge import Bridge
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import check_contain, check_prefix
from channel.chat_message import ChatMessage
from chatgpt_tool_hub.chains.llm import LLMChain
from chatgpt_tool_hub.models import build_model_params
from chatgpt_tool_hub.models.model_factory import ModelFactory
from chatgpt_tool_hub.prompts import PromptTemplate
from common import const
from common.log import logger
from common.tmp_dir import TmpDir
from config import conf, global_config, load_config
from lib import itchat
from lib.itchat.content import FRIENDS
from plugins import *
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_chat2db.api_tentcent import ApiTencent
from plugins.plugin_chat2db.comm import EthZero, is_eth_address, makeGroupReq
from plugins.plugin_chat2db.head_img_manager import HeadImgManager
from plugins.plugin_chat2db.user_refresh_thread import UserRefreshThread
from plugins.plugin_chat2db.UserManager import UserManager

from plugins.plugin_chat2db.chat2db_reply import CustomReply
from plugins.plugin_chat2db.chat2db_knowledge import chat2db_refresh_knowledge
from lib.itchat.async_components.contact import update_friend


@plugins.register(
    name="Chat2db",
    desire_priority=990,
    hidden=False,
    desc="存储及同步聊天记录",
    version="0.4.20231119",
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
            self.robot_account = self.config.get("account")
            self.robot_name = self.config.get("name")
            self.groupxHostUrl = self.config.get("groupx_host_url")
            self.receiver = self.config.get("account")
            self.systemName = self.config.get("system_name")
            self.registerUrl = self.config.get("register_url")
            self.webQrCodeFile = self.config.get("web_qrcode_file")
            self.agentQrCodeFile = self.config.get("agent_qrcode_file")
            self.prefix_cmd = self.config.get("prefix_cmd")  # 修改后的命令前缀
            self.prefix_deny = self.config.get("prefix_deny")
        # 全局配置
        self.channel_type = conf().get("channel_type", "wx")

        self.groupx = ApiGroupx(self.groupxHostUrl)
        self.tencent = ApiTencent(self.groupxHostUrl)
        # 用于管理用户的知识库,确定是否可以更新.
        self.user_manager = UserManager(self.groupx)
        # 应答一些自定义的回复信息
        self.my_reply = CustomReply(
            self.config, self.groupx, self.user_manager)

        self.model = conf().get("model")
        self.curdir = os.path.dirname(__file__)
        self.saveFolder = os.path.join(self.curdir, 'saved')
        self.saveSubFolders = {'webwxgeticon': 'icons', 'webwxgetheadimg': 'headimgs', 'webwxgetmsgimg': 'msgimgs',
                               'webwxgetvideo': 'videos', 'webwxgetvoice': 'voices', '_showQRCodeImg': 'qrcodes'}

        self.conn = sqlite3.connect(os.path.join(
            self.saveFolder, "chat2db.db"), check_same_thread=False)

        self.s = requests.Session()

        self._create_table()
        self._create_table_friends()
        self._create_table_groups()

        btype = Bridge().btype['chat']
        if btype not in [const.OPEN_AI, const.CHATGPT, const.CHATGPTONAZURE, const.BAIDU, const.LINKAI]:
            raise Exception("[Summary] init failed, not supported bot type")
        self.bot = bot_factory.create_bot(Bridge().btype['chat'])

        # self.handlers[Event.ON_RECEIVE_MESSAGE] = self.on_handle_context
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.handlers[Event.ON_SEND_REPLY] = self.on_send_reply

        UserRefreshThread(self.conn, self.config)

        # 管理用户及群的头像
        self.img_service = HeadImgManager(self.conn, self.groupxHostUrl)

        logger.info(f"======>[Chat2db] inited, config={self.config}")

    
    def post_to_groupx(self, account, cmsg,  conversation_id: str, action: str, jailbreak: str, content_type: str, internet_access: bool, role, content, response: str):
        # 发送人头像
        if (cmsg.is_group):
            user_id = cmsg.actual_user_id
            avatar = self.img_service.get_head_img_url(user_id)
            nickName = cmsg.actual_user_nickname
            wxGroupId = cmsg.other_user_id
            wxGroupName = cmsg.other_user_nickname
            user = {'account': account,
                    'NickName': nickName,
                    'UserName': user_id,
                    'HeadImgUrl': avatar
                    }
        else:
            user_id = cmsg.from_user_id
            avatar = self.img_service.get_head_img_url(user_id)
            nickName = cmsg.from_user_nickname
            user = {**cmsg._rawmsg.user,
                    'account': account, 'HeadImgUrl': avatar}
            wxGroupId = ''
            wxGroupName = ''  # 用于判断是否群聊

        # 接收人头像
        recvAvatar = self.img_service.get_head_img_url(cmsg.to_user_id)
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
            logger.debug("create table [chat_records] column: {}" .format(column))
            if column[1] == 'is_triggered':
                column_exists = True
                break
        if not column_exists:
            self.conn.execute(
                "ALTER TABLE chat_records ADD COLUMN is_triggered INTEGER DEFAULT 0;")
            self.conn.execute("UPDATE chat_records SET is_triggered = 0;")

        self.conn.commit()

    def _insert_record(self, session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered=0):
        c = self.conn.cursor()
        logger.debug("[chat_records] insert record: {} {} {} {} {} {} {} {}" .format(
            session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered))
        c.execute("INSERT OR REPLACE INTO chat_records VALUES (?,?,?,?,?,?,?,?)",
                  (session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered))
        self.conn.commit()

    def _get_records(self, session_id, start_timestamp=0, limit=9999):
        c = self.conn.cursor()
        c.execute("SELECT * FROM chat_records WHERE sessionid=? and timestamp>? ORDER BY timestamp DESC LIMIT ?",
                  (session_id, start_timestamp, limit))
        return c.fetchall()

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
    # 发送微信消息提醒用户登录或扫码

    def _send_reg_msg(self, UserName, ActNickName):
        msg = f'点击链接或扫码登录,有效提高答疑质量. \n {self.registerUrl} '
        msg = f'@{ActNickName} {msg}' if ActNickName else msg
        itchat.send_msg(msg, toUserName=UserName)
        itchat.send_image(fileDir=self.webQrCodeFile, toUserName=UserName)
        # itchat.send_image(fileDir=self.agentQrCodeFile, toUserName=UserName)

    # 上传图片到腾讯cos
    
    def _upload_pic(self, ctx):
        try:
            # 单聊时发送的图片给作为消息发给服务器
            cmsg: ChatMessage = ctx['msg']
            logger.info("[save2db] on_handle_context. content: %s" %
                        cmsg.content)

            user = cmsg.from_user_nickname
            session_id = ctx.get('session_id')

            self._insert_record(session_id, cmsg.msg_id, user,
                                cmsg.content, "", str(ctx.type), cmsg.create_time)

            # 上传图片到腾讯cos
            # 文件处理
            ctx.get("msg").prepare()
            file_path = ctx.content
            img_url = "12"
            img_file = os.path.abspath(cmsg.content)
            if os.path.exists(img_file):
                img_url = self.tencent.qcloud_upload_file(
                    self.groupxHostUrl, img_file)

            account = cmsg._rawmsg.User.RemarkName
            logger.info("[save2db] on_handle_context. eth_addr: %s" % account)
            return self.post_to_groupx(account, cmsg, session_id, "recv", "default", str(ctx.type), False, "user",  img_url, '')
        except Exception as e:
            logger.error(f"upload_img error: {e}")
            return None

    # 当收到好友请求时，执行以下函数
    # @itchat.msg_register(FRIENDS)
    # def add_friend(msg):
        # aa = itchat.accept_friend(msg['Text'])
        # msg.User.verify()
        # logger.info(f"接受好友请求 {msg.user.UserName} - {aa}")
        # 接受好友请求
        # msg.user.verify()
        # 向新好友发送问候消息
        # msg.user.send('Nice to meet you!')
    # Hello
    def _reply_sharing(self, ctx):
        pass
        # ContextType.ACCEPT_FRIEND = 19 # 同意好友请求
        # ContextType.JOIN_GROUP = 20  # 加入群聊
        # ContextType.PATPAT = 21  # 拍了拍
        # logger.warn("[save2db] on_handle_context. type: %s " % ctx.type)

        # USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/54.0.2840.71 Safari/537.36'
        # if ctx.type in [ContextType.SHARING]:
        #     logger.info("[save2db] on_handle_context. type: %s " % ctx.type)
        #     logger.info("接受好友邀请")

        #     print(ctx.get('Type'))
        #     print(ctx.kwargs['msg'])
        #     print(ctx.content)
        #     #itchat.accept_friend(msg)
        #     headers = {
        #     'ContentType': 'application/json; charset=UTF-8',
        #     'User-Agent' : USER_AGENT, }
        #     try:
        #         r = self.s.get(ctx.content, headers=headers)
        #     except:
        #         logger.info("获取邀请失败")
        #     return
        # if ctx.type in [ContextType.ACCEPT_FRIEND, ContextType.JOIN_GROUP,ContextType.PATPAT]:
        #     logger.warn("[save2db] on_handle_context. type: %s " % ctx.type)
        #     logger.warn("这些操作需要处理下")

    # 过滤掉原有命令
    def _filter_command(self, e_context: EventContext):
        ctx = e_context['context']
        if ctx.type not in [ContextType.TEXT]:
            return
        content = ctx.content

        if content[0] in self.prefix_deny:
            logger.info("[save2db] _filter_command. 拒绝: %s" % content)
            e_context.action = EventAction.BREAK_PASS
            return True
        if content.startswith(self.prefix_cmd):
            logger.info("[save2db] _filter_command. 接力: %s" % content)
            new_content = content[len(self.prefix_cmd):]
            # 过滤并还原回原有命令
            e_context.content = new_content
            e_context['context']['content'] = new_content
            e_context.action = EventAction.CONTINUE
            return True
        return False

    # 处理医生分配
    def _set_my_doctor(self, e_context: EventContext, is_group: bool):
        if is_group:
            return False  # 群中不允许设置医生

        ctx = e_context['context']
        msg = ctx.get("msg")
        content = ctx.content

        name = content[3:].strip()

        userid = msg.from_user_id
        act_user = itchat.update_friend(userid)
        account = act_user.RemarkName

        result = self.groupx.set_my_doctor_info(account, self.receiver, name)

        logger.info("[save2db] doctor: %s " % result)

        if result:
            doctor = result
            if doctor:
                itchat.send_msg(
                    f"医生对接成功!\n----------------\n医生:{name}({doctor.get('department')})\n{doctor.get('intro')}\n擅长:{doctor.get('skill')}", toUserName=userid)
            else:
                name = result.get("professionalName") or result.get("name")
                department = result.get("department", '')
                itchat.send_msg(
                    f"医生对接失败!\n----------------\n先前已自动对接医生:{name}({department})", toUserName=userid)
        else:
            itchat.send_msg(
                f"没找到你要对接的医生:‘{name}’\n请确认医生真实姓名.", toUserName=userid)
        e_context.action = EventAction.BREAK_PASS
        return True
    # 查询已经分配的医生

    def _get_my_doctor(self, e_context: EventContext, is_group: bool):
        ctx = e_context['context']
        msg = ctx.get("msg")
        content = ctx.content
        name = content[3:]
        userid = msg.from_user_id

        if is_group:
            act_user = itchat.update_friend(msg.actual_user_id)
            account = act_user.RemarkName
        else:
            act_user = itchat.update_friend(userid)
            account = act_user.RemarkName

        result = self.groupx.get_my_doctor_info(account, self.receiver, name)

        logger.info("[save2db] doctor: %s " % result)

        if result:
            doctorName = result.get("professionalName") or result.get("name")
            doctorDepartment = result.get("department", '')
            if is_group:
                itchat.send_msg(
                    f"@{act_user.NickName}\n查询医生成功!\n----------------\n你的医生是‘{doctorName}({doctorDepartment})’", toUserName=userid)
            else:
                itchat.send_msg(
                    f"查询成功!\n----------------\n你的医生是‘{doctorName}({doctorDepartment})’", toUserName=userid)
        else:
            itchat.send_msg(f"没找到你的医生.", toUserName=userid)
        e_context.action = EventAction.BREAK_PASS
        return True
    # 收到消息 ON_RECEIVE_MESSAGE

    
    def on_handle_context(self, e_context: EventContext):
        # self.sessionid = e_context["context"]["session_id"]
        # self.bot.sessions.build_session(self.sessionid, system_prompt="self.desc")
        # 过滤掉原有的一些命令
        if self._filter_command(e_context):
            return

        # 匹配用户知识库,从服务器拉取知识库并更新到本地
        if chat2db_refresh_knowledge(self.groupx, self.robot_account, self.user_manager, e_context):
            return

        # 处理一些问候性提问及测试提问
        if self.my_reply.reply_hello(e_context):
            return
        # 用户加群
        if self.my_reply.reply_join_group(e_context):
            return
        # 用户拍一拍机器人
        if self.my_reply.reply_patpat(e_context):
            return

        ctx = e_context['context']
        if ctx.type not in [ContextType.IMAGE, ContextType.TEXT]:
            return

        content = ctx.content
        is_group = ctx.get("isgroup", False)
        if is_group:
            if (content.startswith('@医生')):
                self._get_my_doctor(e_context, is_group)
            return  # 群聊天不处理图片,不处理医生分配
        # 处理图片相关内容
        if ctx.type == ContextType.IMAGE:  # 处理图片
            upload = self._upload_pic(ctx)
            logger.info("[save2db] upload image: %s " % upload)
        if ctx.type == ContextType.TEXT and content.startswith('@医生'):  # 对接医生
            name = content[3:].strip()
            if len(name) < 1:
                self._get_my_doctor(e_context, is_group)
                return
            if self._set_my_doctor(e_context, is_group):
                return

        e_context.action = EventAction.CONTINUE

     # 发送回复前
    def on_send_reply(self, e_context: EventContext):

        if e_context["reply"].type not in [ReplyType.TEXT]:
            return

        ctx = e_context['context']
        reply = e_context["reply"]
        recvMsg = ctx.content
        replyMsg = reply.content
        logger.debug("[save2db] on_decorate_reply. content: %s==>%s" %
                     (recvMsg, replyMsg))

        cmsg: ChatMessage = e_context['context']['msg']

        session_id = ctx.get('session_id')
        isGroup = ctx.get("isgroup", False)

        username = cmsg.actual_user_nickname if isGroup else cmsg.from_user_nickname
        userid = cmsg.actual_user_id if isGroup else cmsg.from_user_id
        # act_user = itchat.update_friend(userid)
        act_user = itchat.search_friends(userName=userid)
        if not act_user:
            act_user = itchat.update_friend(userid)
            
        account = act_user.RemarkName

        try:
            self._insert_record(session_id, cmsg.msg_id, username,
                                recvMsg, replyMsg, str(ctx.type), cmsg.create_time)

            result = self.post_to_groupx(account, cmsg, session_id, "ask", "default", str(
                ctx.type), False, "user", recvMsg, replyMsg)
            if (result is not None):
                logger.info(result)
                # ethAddr存在到RemarkName 中
                retAccount = result.get('account', None)

                if is_eth_address(retAccount):
                    if (account != retAccount):
                        # 更新account到 RemarkName中
                        itchat.set_alias(act_user.UserName, retAccount)
                        act_user.update()
                        itchat.dump_login_status()
                else:
                    # 发送微信消息提醒点击登录或扫码
                    self._send_reg_msg(cmsg.from_user_id,
                                       username if isGroup else None)

                self.user_manager.set_my_doctor(
                    userid, result.get('myDoctor', None))
                self.user_manager.update_knowledge(userid, replyMsg)

        except Exception as e:
            logger.error("on_send_reply: {}".format(e))

        e_context.action = EventAction.CONTINUE

    def _load_config_template(self):
        logger.error(
            "No Chat2db plugin config.json, use plugins/plugin_Chat2db/config.json.template")
        try:
            plugin_config_path = os.path.join(
                os.getcwd(), "config.json.template")
            if os.path.exists(plugin_config_path):
                with open(plugin_config_path, "r", encoding="utf-8") as f:
                    plugin_conf = json.load(f)
                    plugin_conf["midjourney"]["enabled"] = False
                    plugin_conf["summary"]["enabled"] = False
                    return plugin_conf
        except Exception as e:
            logger.exception(e)

    def get_help_text(self, **kwargs):
        help_text = "存储聊天记录到数据库"
        return help_text
