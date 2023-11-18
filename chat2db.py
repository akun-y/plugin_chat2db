# encoding:utf-8
import logging
import os
import sqlite3

import requests
from bridge.bridge import Bridge
import time
from bot import bot_factory
from bridge.bridge import Bridge
from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_channel import check_contain, check_prefix
from channel.chat_message import ChatMessage
from common.tmp_dir import TmpDir
from datetime import datetime, timedelta

from lib import itchat
from lib.itchat.content import FRIENDS
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
from plugins.plugin_chat2db.UserManager import UserManager
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
            self.robot_account =  self.config.get("account")
            self.robot_name =  self.config.get("name")
            self.groupxHostUrl = self.config.get("groupx_host_url")
            self.receiver =  self.config.get("account")
            self.systemName =  self.config.get("system_name")
            self.registerUrl = self.config.get("register_url")
            self.webQrCodeFile = self.config.get("web_qrcode_file")
            self.agentQrCodeFile = self.config.get("agent_qrcode_file")
            self.prefix_cmd = self.config.get("prefix_cmd") #修改后的命令前缀
        self.prefix_deny = self.config.get("prefix_deny")
        #全局配置
        self.channel_type = conf().get("channel_type", "wx")

        self.groupx = ApiGroupx(self.groupxHostUrl)

        self.model = conf().get("model")
        self.curdir = os.path.dirname(__file__)
        self.saveFolder = os.path.join(self.curdir, 'saved')
        self.saveSubFolders = {'webwxgeticon': 'icons', 'webwxgetheadimg': 'headimgs', 'webwxgetmsgimg': 'msgimgs',
                               'webwxgetvideo': 'videos', 'webwxgetvoice': 'voices', '_showQRCodeImg': 'qrcodes'}

        self.conn = sqlite3.connect(os.path.join(self.saveFolder, "chat2db.db"), check_same_thread=False)

        self.s = requests.Session()

        self._create_table()
        self._create_table_avatar()
        self._create_table_friends()
        self._create_table_groups()
        # 用于管理用户的知识库,确定是否可以更新.
        self.user_manager = UserManager()
        btype = Bridge().btype['chat']
        if btype not in [const.OPEN_AI, const.CHATGPT, const.CHATGPTONAZURE, const.BAIDU, const.LINKAI]:
            raise Exception("[Summary] init failed, not supported bot type")
        self.bot = bot_factory.create_bot(Bridge().btype['chat'])

        #self.handlers[Event.ON_RECEIVE_MESSAGE] = self.on_handle_context
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
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
    #发送微信消息提醒用户登录或扫码
    def _send_reg_msg(self, UserName, ActNickName):
        msg = f'点击链接或扫码登录,有效提高答疑质量. \n {self.registerUrl} '
        msg = f'@{ActNickName} {msg}' if ActNickName else msg
        itchat.send_msg(msg, toUserName=UserName)
        itchat.send_image(fileDir=self.webQrCodeFile, toUserName=UserName)
        #itchat.send_image(fileDir=self.agentQrCodeFile, toUserName=UserName)

    # 上传图片到腾讯cos
    def _upload_pic(self, ctx):
        try:
            # 单聊时发送的图片给作为消息发给服务器
            cmsg : ChatMessage = ctx['msg']
            logger.info("[save2db] on_handle_context. content: %s" % cmsg.content)

            user = cmsg.from_user_nickname
            session_id = ctx.get('session_id')

            self._insert_record(session_id, cmsg.msg_id, user, cmsg.content, "", str(ctx.type), cmsg.create_time)

            # 上传图片到腾讯cos
            # 文件处理
            ctx.get("msg").prepare()
            file_path = ctx.content
            img_url ="12"
            img_file = os.path.abspath(cmsg.content)
            if os.path.exists(img_file):
                img_url = qcloud_upload_file(self.groupxHostUrl, img_file)

            account = cmsg._rawmsg.User.RemarkName
            logger.info("[save2db] on_handle_context. eth_addr: %s" % account)
            return self.post_to_groupx(account, cmsg, session_id, "recv", "default", str(ctx.type), False, "user",  img_url, '')
        except Exception as e:
            logger.error(f"upload_img error: {e}")
            return None

    def _set_my_doctor(self, account, doctor_name):
        logger.info("[save2db] set_my_doctor: %s " % doctor_name)

        return self.groupx.set_my_doctor_info(account, self.receiver, doctor_name)

    # 当收到好友请求时，执行以下函数
    #@itchat.msg_register(FRIENDS)
    #def add_friend(msg):
        #aa = itchat.accept_friend(msg['Text'])
        #msg.User.verify()
        #logger.info(f"接受好友请求 {msg.user.UserName} - {aa}")
        # 接受好友请求
        #msg.user.verify()
        # 向新好友发送问候消息
        #msg.user.send('Nice to meet you!')
    #Hello
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
        if ctx.type not in [ContextType.TEXT]: return
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

    def _reply_hello(self, e_context: EventContext):
        try:
            ctx = e_context['context']
            if ctx.type not in [ContextType.TEXT]: return

            msg = ctx.get("msg")
            content = ctx.content

            content = content.strip()
            content = content.lower()
            if content == "hello" :
                reply = Reply()
                reply.type = ReplyType.TEXT
                msg: ChatMessage = e_context["context"]["msg"]
                if e_context["context"]["isgroup"]:
                    reply.content = f"Hello, {msg.actual_user_nickname} from {msg.from_user_nickname}"
                else:
                    reply.content = f"Hello, {msg.from_user_nickname}"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
                return True
            if content == "hi":
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "Hi"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK  # 事件结束，进入默认处理逻辑，一般会覆写reply
                return True
        except Exception as e:
            logger.error("_reply_hello: {}".format(e))
        return False

    def _append_know(self, user_session, know):
        count = 0
        # 倒序遍历
        for index, value in enumerate(know[::-1]):
            title = value.get('title', None)
            content = value.get('content', None)

            if title and content:
                user_session.append({'role': 'user', 'content': title})
                user_session.append({'role': 'assistant', 'content': content})
                count += 1
                logger.info(f'user session append user {title}')
                logger.info(f'user session append assistant {content}')
            if index >40:
                logger.warn("知识库内容太多了,超过了40条")
                break;
        return count;
    def _refresh_myknowledge(self, e_context: EventContext):
        try:
            ctx = e_context['context']
            if ctx.type == ContextType.TEXT:
                msg = ctx.get("msg")

                isgroup =  ctx.get("isgroup", False)
                if isgroup: user= itchat.update_friend(msg.actual_user_id)
                else: user= msg._rawmsg.user

                session_id = ctx.get("session_id")
                all_sessions = Bridge().get_bot("chat").sessions
                user_session = all_sessions.build_session(session_id).messages
                sess_len = len(user_session)
                logger.info(f"===>用户 user session 长度为{sess_len}")
                #已经使用过知识库了
                if sess_len > 0:
                    #使用知识库如果超过1天了,那么再更新下.
                    if self.user_manager.should_update(user.UserName) == False:
                        know = self.user_manager.get_knowledge(user.UserName)
                        self._append_know(user_session, know)
                        return False
                    logger.info("===>原知识库已经超过24小时,更新知识库...")
                # 从groupx 获取know
                data = self.groupx.get_myknowledge(self.robot_account, {
                    "isgroup": isgroup,
                    'group_name': msg.from_user_nickname if isgroup else None,
                    'group_id' : msg.from_user_id if isgroup else None,
                    'receiver' : msg.to_user_id,
                    'receiver_name' : msg.to_user_nickname,
                    "user": user
                    })

                know = data.get("knowledges", {})

                # logger.info("chat2db knowledge:\n用户:%s \n %s" % (user.NickName, json.dumps(know, ensure_ascii=False, indent=2)))

                count = 0
                if len(know) > 0:
                    if(len(user_session)<1): # 新用户,session为空
                        user_session.append({
                            'role': 'user',
                            'content': '你好，我叫"'+user.NickName+'",后续我的提问请从会话中查询结果.如请优先使用会话中的内容做答疑解,不要在提问中说明你是机器人,引用会话时不要解释,不要有其他说明'})
                        user_session.append({
                            'role': 'assistant',
                            'content': '好的,我记住了'})

                        logger.warn("新用户,初始化user session")

                    self.user_manager.update_knowledge(user.UserName, know)
                    count = self._append_know(user_session,know)
                    
                logger.warn(f"=====>添加{user.NickName}的医生{data.get('doctorProName')}的知识库成功,共{count}条知识库")
                return False
        except Exception as e:
            logger.error(e)
            return False
    #收到消息 ON_RECEIVE_MESSAGE
    def on_handle_context(self, e_context: EventContext):
        # 过滤掉原有的一些命令
        if self._filter_command(e_context): return
        # 匹配用户知识库,从服务器拉取知识库并更新到本地
        if self._refresh_myknowledge(e_context): return
        # 处理一些问候性提问及测试提问
        if self._reply_hello(e_context) : return

        ctx = e_context['context']

        # 处理图片相关内容
        if ctx.get("isgroup", False): return # 群聊天不处理图片,不处理医生分配
        if ctx.type not in [ContextType.IMAGE, ContextType.TEXT]: return

        content = ctx.content

        if ctx.type == ContextType.IMAGE: #处理图片
            upload = self._upload_pic(ctx)
            logger.info("[save2db] upload image: %s " % upload)
        if ctx.type == ContextType.TEXT and content.startswith('@'): # 对接医生
            name = content[1:]
            userid = e_context['context']['msg'].from_user_id
            act_user = itchat.update_friend(userid)
            account = act_user.RemarkName

            result = self._set_my_doctor(account, name)

            logger.info("[save2db] doctor: %s " % result)

            if result:
                doctor = result.get("doctor")
                itchat.send_msg(f"医生对接成功!\n----------------\n医生:{name}({doctor.get('department')})\n{doctor.get('intro')}\n擅长:{doctor.get('skill')}", toUserName=userid)
            else :
                itchat.send_msg(f"没找到你要对接的医生:{name}\n请确认医生真实姓名.", toUserName=userid)
            e_context.action = EventAction.BREAK_PASS
            return

        e_context.action = EventAction.CONTINUE

     # 发送回复前
    def on_send_reply(self, e_context: EventContext):

        if e_context["reply"].type not in [ReplyType.TEXT]: return

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
                    # 发送微信消息提醒点击登录或扫码
                    self._send_reg_msg(cmsg.from_user_id, username if isGroup else None)
                    # 继续后续消息

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
