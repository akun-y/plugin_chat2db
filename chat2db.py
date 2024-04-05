# encoding:utf-8
import os
import sqlite3

import requests
from PIL import ImageFont

import plugins
from bridge.context import ContextType
from bridge.reply import ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from config import conf
from lib import itchat
from lib.itchat.content import FRIENDS
from plugins import *
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_chat2db.api_tencent import ApiTencent
from plugins.plugin_chat2db.chat2db_knowledge import chat2db_refresh_knowledge
from plugins.plugin_chat2db.chat2db_reply import CustomReply
from plugins.plugin_chat2db.head_img_manager import HeadImgManager
from plugins.plugin_chat2db.user_refresh_thread import UserRefreshThread
from plugins.plugin_chat2db.UserManager import UserManager

from plugins.plugin_comm import *
from plugins.plugin_comm.remark_name_info import RemarkNameInfo
from plugins.plugin_comm.plugin_comm import (
    get_itchat_user,
    is_eth_address,
    is_valid_string,
    make_chat_sign_req,
)
from plugins.plugin_comm.pick_tables_markdown import pick_tables_from_markdown
from plugins.plugin_comm.mixedtext_to_image import (
    html_to_image,
    is_html,
    markdown_to_html,
)


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
        self.path = os.path.dirname(__file__)
        self.config = super().load_config()
        if not self.config:
            # 未加载到配置，使用模板中的配置
            self.config = self._load_config_template()
        if self.config:
            self.robot_account = self.config.get("account")
            self.robot_name = self.config.get("name")
            self.receiver = self.config.get("account")
            self.systemName = self.config.get("system_name")
            self.registerUrl =conf().get("iknow_reg_url")
            self.webQrCodeFile = self.config.get("web_qrcode_file")
            self.agentQrCodeFile = self.config.get("agent_qrcode_file")
            self.prefix_cmd = self.config.get("prefix_cmd")  # 修改后的命令前缀
            self.prefix_deny = self.config.get("prefix_deny")
        # 全局配置
        self.channel_type = conf().get("channel_type", "wx")

        self.groupx = ApiGroupx()
        self.tencent = ApiTencent()
        # 用于管理用户的知识库,确定是否可以更新.
        self.user_manager = UserManager(self.groupx)
        # 应答一些自定义的回复信息
        self.my_reply = CustomReply(self.config, self.groupx, self.user_manager)
        # 字体文件
        self.tmp_dir = os.path.join(os.path.dirname(__file__), "saved")
        font_path = os.path.join(os.path.dirname(__file__), "yahei2.ttf")
        self.font = ImageFont.truetype(font_path, 20)

        self.model = conf().get("model")
        self.curdir = os.path.dirname(__file__)
        self.saveFolder = os.path.join(self.curdir, "saved")
        self.saveSubFolders = {
            "webwxgeticon": "icons",
            "webwxgetheadimg": "headimgs",
            "webwxgetmsgimg": "msgimgs",
            "webwxgetvideo": "videos",
            "webwxgetvoice": "voices",
            "_showQRCodeImg": "qrcodes",
        }

        self.conn = sqlite3.connect(
            os.path.join(self.saveFolder, "chat2db.db"), check_same_thread=False
        )

        self.s = requests.Session()

        self._create_table()
        self._create_table_friends()
        self._create_table_groups()

        # self.handlers[Event.ON_RECEIVE_MESSAGE] = self.on_handle_context
        self.handlers[Event.ON_HANDLE_CONTEXT] = self.on_handle_context
        self.handlers[Event.ON_SEND_REPLY] = self.on_send_reply

        UserRefreshThread(self.conn, self.config)

        # 管理用户及群的头像
        self.img_service = HeadImgManager(self.conn)

        logger.info(f"======>[Chat2db] inited")

    def post_to_groupx(
        self,
        account,
        group_object_id,
        cmsg,
        conversation_id: str,
        action: str,
        jailbreak: str,
        content_type: str,
        internet_access: bool,
        role,
        content,
        response: str,
    ):
        # 发送人头像
        if cmsg.is_group:
            user_id = cmsg.actual_user_id
            avatar = self.img_service.get_head_img_url(user_id)
            nickName = cmsg.actual_user_nickname
            wxGroupId = cmsg.other_user_id
            wxGroupName = cmsg.other_user_nickname

        else:
            user_id = cmsg.from_user_id
            avatar = self.img_service.get_head_img_url(user_id)
            nickName = cmsg.from_user_nickname
            wxGroupId = ""
            wxGroupName = ""  # 用于判断是否群聊
        # 发送人详情
        user = get_itchat_user(user_id)
        # 接收人头像
        recvAvatar = self.img_service.get_head_img_url(cmsg.to_user_id)
        source = f"{self.systemName} {self.channel_type}"
        query_json = {
            "receiver": self.receiver,
            "receiverName": cmsg.to_user_nickname,
            "receiverAvatar": recvAvatar,
            "conversationId": conversation_id,
            "action": action,
            "model": self.model,
            "internetAccess": internet_access,
            "aiResponse": response,
            "userName": nickName,
            "userAvatar": avatar,
            "userId": user_id,
            "message": content,
            "messageId": cmsg.msg_id,
            "messageType": content_type,
            "wxReceiver": cmsg.to_user_id,
            "wxUser": user,
            "wxGroupId": wxGroupId,
            "wxGroupName": wxGroupName,
            "wxGroupObjectId": group_object_id,
            "source": f"{source} group" if cmsg.is_group else f"{source} personal",
        }

        return self.groupx.post_chat_record(account, query_json)

    def _create_table(self):
        c = self.conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS chat_records
                    (sessionid TEXT, msgid INTEGER, user TEXT,recv TEXT,reply TEXT, type TEXT, timestamp INTEGER, is_triggered INTEGER,
                    PRIMARY KEY (timestamp, msgid))"""
        )

        # 后期增加了is_triggered字段，这里做个过渡，这段代码某天会删除
        c = c.execute("PRAGMA table_info(chat_records);")
        column_exists = False
        for column in c.fetchall():
            logger.debug("create table [chat_records] column: {}".format(column))
            if column[1] == "is_triggered":
                column_exists = True
                break
        if not column_exists:
            self.conn.execute(
                "ALTER TABLE chat_records ADD COLUMN is_triggered INTEGER DEFAULT 0;"
            )
            self.conn.execute("UPDATE chat_records SET is_triggered = 0;")

        self.conn.commit()

    def _insert_record(
        self, session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered=0
    ):
        c = self.conn.cursor()
        logger.debug(
            "[chat_records] insert record: {} {} {} {} {} {} {} {}".format(
                session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered
            )
        )
        c.execute(
            "INSERT OR REPLACE INTO chat_records VALUES (?,?,?,?,?,?,?,?)",
            (session_id, msg_id, user, recv, reply, msg_type, timestamp, is_triggered),
        )
        self.conn.commit()

    def _get_records(self, session_id, start_timestamp=0, limit=9999):
        c = self.conn.cursor()
        c.execute(
            "SELECT * FROM chat_records WHERE sessionid=? and timestamp>? ORDER BY timestamp DESC LIMIT ?",
            (session_id, start_timestamp, limit),
        )
        return c.fetchall()

    def _create_table_friends(self):
        c = self.conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS friends_records
                    (selfUserName TEXT, selfNickName TEXT, selfHeadImgUrl TEXT,
                    UserName TEXT, NickName TEXT, HeadImgUrl TEXT,
                    PRIMARY KEY (NickName))"""
        )
        self.conn.commit()

    def _create_table_groups(self):
        c = self.conn.cursor()
        c.execute(
            """CREATE TABLE IF NOT EXISTS groups_records
                    (selfUserName TEXT, selfNickName TEXT, selfDisplayName TEXT,
                    UserName TEXT, NickName TEXT, HeadImgUrl TEXT,
                    PYQuanPin TEXT, EncryChatRoomId TEXT,
                    PRIMARY KEY (NickName))"""
        )
        self.conn.commit()

    # 发送微信消息提醒用户登录或扫码

    def _send_reg_msg(self, UserName, ActNickName):
        msg = f"点击链接或扫码登录,有效提高答疑质量. \n {self.registerUrl} "
        msg = f"@{ActNickName} {msg}" if ActNickName else msg
        itchat.send_msg(msg, toUserName=UserName)
        itchat.send_image(fileDir=self.webQrCodeFile, toUserName=UserName)
        # itchat.send_image(fileDir=self.agentQrCodeFile, toUserName=UserName)

    # 上传图片到腾讯cos

    def _upload_pic(self, ctx):
        try:
            # 单聊时发送的图片给作为消息发给服务器
            cmsg: ChatMessage = ctx["msg"]
            logger.info("[save2db] on_handle_context. content: %s" % cmsg.content)

            user = cmsg.from_user_nickname
            session_id = ctx.get("session_id")

            self._insert_record(
                session_id,
                cmsg.msg_id,
                user,
                cmsg.content,
                "",
                str(ctx.type),
                cmsg.create_time,
            )

            # 上传图片到腾讯cos
            # 文件处理
            ctx.get("msg").prepare()
            file_path = ctx.content
            img_url = "12"
            img_file = os.path.abspath(cmsg.content)
            if os.path.exists(img_file):
                img_url = self.tencent.qcloud_upload_file(img_file)

            account = RemarkNameInfo(cmsg._rawmsg.User.RemarkName).get_account()
            group_object_id = ""
            if cmsg.is_group:
                group_object_id = cmsg._rawmsg.ToUserName
            logger.info("[save2db] on_handle_context. eth_addr: %s" % account)
            return self.post_to_groupx(
                account,
                group_object_id,
                cmsg,
                session_id,
                "recv",
                "default",
                str(ctx.type),
                False,
                "user",
                img_url,
                "",
            )
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
        ctx = e_context["context"]
        if ctx.type not in [ContextType.TEXT]:
            return
        content = ctx.content
        logger.info(self.robot_account)
        if content[0] in self.prefix_deny:
            logger.info("[save2db] _filter_command. 拒绝: %s" % content)
            e_context.action = EventAction.BREAK_PASS
            return True
        if content.startswith(self.prefix_cmd):
            logger.info("[save2db] _filter_command. 接力: %s" % content)
            new_content = content[len(self.prefix_cmd) :]
            # 过滤并还原回原有命令
            e_context.content = new_content
            e_context["context"]["content"] = new_content
            e_context.action = EventAction.CONTINUE
            return True
        return False

    # 处理医生分配
    def _set_my_doctor(self, e_context: EventContext, is_group: bool):
        if is_group:
            return False  # 群中不允许设置医生

        ctx = e_context["context"]
        msg = ctx.get("msg")
        content = ctx.content

        name = content[3:].strip()

        userid = msg.from_user_id
        act_user = itchat.update_friend(userid)
        account = RemarkNameInfo(act_user.RemarkName).get_account()

        result = self.groupx.set_my_doctor_info(account, self.receiver, name)

        logger.info("[save2db] doctor: %s " % result)

        if result:
            doctor = result
            if doctor:
                itchat.send_msg(
                    f"医生对接成功!\n----------------\n医生:{name}({doctor.get('department')})\n{doctor.get('intro')}\n擅长:{doctor.get('skill')}",
                    toUserName=userid,
                )
            else:
                name = result.get("professionalName") or result.get("name")
                department = result.get("department", "")
                itchat.send_msg(
                    f"医生对接失败!\n----------------\n先前已自动对接医生:{name}({department})",
                    toUserName=userid,
                )
        else:
            itchat.send_msg(f"没找到你要对接的医生:‘{name}’\n请确认医生真实姓名.", toUserName=userid)
        e_context.action = EventAction.BREAK_PASS
        return True

    # 查询已经分配的医生

    def _get_my_doctor(self, e_context: EventContext, is_group: bool):
        ctx = e_context["context"]
        msg = ctx.get("msg")
        content = ctx.content
        name = content[3:]
        userid = msg.from_user_id

        if is_group:
            act_user = itchat.update_friend(msg.actual_user_id)
            result = self.groupx.get_doctor_of_group(msg.from_user_id)
        else:
            act_user = itchat.update_friend(userid)
            account = RemarkNameInfo(act_user.RemarkName).get_account() or EthZero
            result = self.groupx.get_my_doctor_info(
                account, self.receiver, userid, msg.from_user_nickname, name
            )

        logger.info("[save2db] doctor: %s " % result)

        if result:
            doctorName = result.get("professionalName") or result.get("name")
            doctorDepartment = result.get("department", "")
            if is_group:
                itchat.send_msg(
                    f"@{act_user.NickName}\n查询医生成功!\n----------------\n你的医生是‘{doctorName}({doctorDepartment})’",
                    toUserName=userid,
                )
            else:
                itchat.send_msg(
                    f"查询成功!\n----------------\n你的医生是‘{doctorName}({doctorDepartment})’",
                    toUserName=userid,
                )
        else:
            itchat.send_msg(f"没找到你的医生.", toUserName=userid)
        e_context.action = EventAction.BREAK_PASS
        return True

    # 收到消息 ON_RECEIVE_MESSAGE

    def on_handle_context(self, e_context: EventContext):
        # 过滤掉原有的一些命令
        if self._filter_command(e_context):
            return

        # 匹配用户知识库,从服务器拉取知识库并更新到本地
        if chat2db_refresh_knowledge(
            self.groupx, self.robot_account, self.user_manager, e_context
        ):
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

        ctx = e_context["context"]
        if ctx.type not in [ContextType.IMAGE, ContextType.TEXT]:
            return

        content = ctx.content
        is_group = ctx.get("isgroup", False)
        if is_group:
            if content.startswith("@医生"):
                self._get_my_doctor(e_context, is_group)
            return  # 群聊天不处理图片,不处理医生分配
        # 处理图片相关内容
        if ctx.type == ContextType.IMAGE:  # 处理图片
            upload = self._upload_pic(ctx)
            logger.info("[save2db] upload image: %s " % upload)
        if ctx.type == ContextType.TEXT and content.startswith("@医生"):  # 对接医生
            name = content[3:].strip()
            if len(name) < 1:
                self._get_my_doctor(e_context, is_group)
                return
            if self._set_my_doctor(e_context, is_group):
                return

        e_context.action = EventAction.CONTINUE

    def _get_user(self, user_id):
        user = itchat.search_friends(userName=user_id)
        if not user:
            user = itchat.update_friend(user_id)
        return user if user else {}

    # 发送回复前

    def on_send_reply(self, e_context: EventContext):
        if e_context["reply"].type not in [ReplyType.TEXT]:
            return

        ctx = e_context["context"]
        reply = e_context["reply"]
        recvMsg = ctx.content
        replyMsg = reply.content
        logger.debug(
            "[save2db] on_decorate_reply. content: %s==>%s" % (recvMsg, replyMsg)
        )

        cmsg: ChatMessage = e_context["context"]["msg"]

        session_id = ctx.get("session_id")
        is_group = ctx.get("isgroup", False)

        username = cmsg.actual_user_nickname if is_group else cmsg.from_user_nickname
        userid = cmsg.actual_user_id if is_group else cmsg.from_user_id
        # 获取微信用户信息
        act_user = self._get_user(userid)
        rm = RemarkNameInfo(act_user.RemarkName)
        old_account = rm.get_account()
        old_user_object_id = rm.get_object_id()
        # 获取微信群信息
        group_id = ""
        group_object_id = ""
        if is_group:
            group_id = cmsg.from_user_id
            group_user = self._get_user(cmsg.from_user_id)
            group_object_id = group_user.RemarkName

        try:
            self._insert_record(
                session_id,
                cmsg.msg_id,
                username,
                recvMsg,
                replyMsg,
                str(ctx.type),
                cmsg.create_time,
            )
            # 保存到groupx
            result = self.post_to_groupx(
                old_account,
                group_object_id,
                cmsg,
                session_id,
                "ask",
                "default",
                str(ctx.type),
                False,
                "user",
                recvMsg,
                replyMsg,
            )
            if result is not None:
                logger.info(f"记录微信端用户信息成功===>{result}")
                # ethAddr存在到RemarkName 中
                ret_account = result.get("account", None)
                group_object_id = result.get("groupObjectId", None)
                user_object_id = result.get("userObjectId", None)

                # 设置group的备注,object,account,方便下次找回.
                if is_group and group_object_id:
                    group_user = self._get_user(group_id)
                    old_group_object_id = group_user.RemarkName

                    if old_group_object_id != group_object_id:
                        itchat.set_alias(group_id, group_object_id)
                        group_user.update()
                        itchat.dump_login_status()
                        self.groupx.post_groups(
                            self.robot_account,
                            self.robot_name,
                            [group_user],
                        )
                        logger.info(f"获得groupx提供的用户群objectId===>{old_group_object_id}")
                # 存储account,objectId 到user RemarkName中,方便下次找回.
                update_remarkname_flag = False

                if is_eth_address(ret_account) and (old_account != ret_account):
                    # 更新account到 RemarkName中
                    rm.set_account(ret_account)
                    update_remarkname_flag = True
                    logger.info(f"获得用户account===>{ret_account}")

                if (
                    is_valid_string(user_object_id)
                    and old_user_object_id != user_object_id
                ):
                    rm.set_object_id(user_object_id)
                    update_remarkname_flag = True
                    logger.info(f"获得用户的objectId===>{user_object_id}")

                if update_remarkname_flag:
                    itchat.set_alias(act_user.UserName, rm.get_remark_name())
                    act_user.update()
                    itchat.dump_login_status()
                    self.groupx.post_friends(
                        self.robot_account, self.robot_name, [act_user]
                    )

                # 发送微信消息提醒点击登录或扫码
                # self._send_reg_msg(cmsg.from_user_id,
                #                username if is_group else None)

                self.user_manager.set_my_doctor(userid, result.get("myDoctor", None))
                self.user_manager.update_knowledge(userid, replyMsg)
            # 处理应答信息中markdown html
            img_sent = self._proc_html_markdown(
                replyMsg,
                cmsg.from_user_id,
                cmsg.actual_user_id,
                cmsg.actual_user_nickname,
                is_group,
            )
            if img_sent:
                e_context.action = EventAction.BREAK_PASS
                reply.action = EventAction.BREAK_PASS
                return
        except Exception as e:
            logger.error("on_send_reply: {}".format(e))

        e_context.action = EventAction.CONTINUE

    def _proc_html_markdown(
        self, reply_msg, to_user_id, actual_user_id, actual_user_nickname, is_group
    ):
        output_image_path = os.path.join(self.tmp_dir, f"{to_user_id}-img.png")

        img_files = []
        # 查找markdown table
        md_tables, other_text = pick_tables_from_markdown(reply_msg)
        if md_tables:
            for index, md_table in enumerate(md_tables):
                if len(md_table) == 0:
                    continue
                html_content = markdown_to_html(md_table)
                md_file_path = os.path.join(self.tmp_dir, f"md_table_{index}.png")
                img_file = html_to_image(html_content, md_file_path, self.font)
                if img_file:
                    img_files.append(img_file)
        # 查找html
        if is_html(other_text):
            img_file = html_to_image(other_text, output_image_path, self.font)
            if img_file:
                img_files.append(img_file)
            print(f"HTML content converted to image:{output_image_path}")
        else:
            print("No HTML content to convert.")
        # 有图片生成，发送图片
        if img_files:
            if other_text:
                msg = f"@{actual_user_nickname} " if actual_user_nickname else ""
                msg = msg + other_text
                if msg:
                    itchat.send_msg(msg, toUserName=to_user_id)
            for file in img_files:
                print(f"Sending image:{file}")
                itchat.send_image(fileDir=file, toUserName=to_user_id)
            return True
        # 普通文本，啥都没有
        else:
            print("No image to send.")
            return False

    def _load_config_template(self):
        logger.error(
            "No Chat2db plugin config.json, use plugins/plugin_Chat2db/config.json.template"
        )
        try:
            plugin_config_path = os.path.join(os.getcwd(), "config.json.template")
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
