# encoding:utf-8


from bridge.context import ContextType
from bridge.reply import Reply, ReplyType
from channel.chat_message import ChatMessage
from common.log import logger
from lib import itchat
from plugins import *

# 应答一些自定义的回复信息,包括拍一拍，加群欢迎，Hello回复


class CustomReply:
    def __init__(self, config, groupx, user_manager):
        self.config = config
        self.groupx = groupx
        self.user_manager = user_manager

        self.robot_account = conf().get("bot_account")
        self.robot_name = self.config.get("name")
        self.robot_desc = self.config.get("description")
        self.patpat_message = self.config.get("patpat_message")  # 拍拍是否使用配置信息

    def reply_join_group(self, e_context: EventContext):
        ctx = e_context["context"]
        if ctx.type != ContextType.JOIN_GROUP:
            return
        logger.info("reply_join_group")

        msg: ChatMessage = e_context["context"]["msg"]

        welcome_msg = None
        group = self.user_manager.get_group_info(msg.from_user_id)
        if group:
            welcome_msg = group.get("joinWelcomeInfo", None)

        if welcome_msg:
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = welcome_msg
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            logger.info(f"reply_join_group: {welcome_msg}")
            return True
        return False

    def _patpat_config_message(self, e_context: EventContext):
        reply = Reply()
        reply.type = ReplyType.TEXT
        reply.content = self.patpat_message
        e_context["reply"] = reply
        e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
        logger.info(f"reply_patpat: {self.patpat_message}")
        return True

    def reply_patpat(self, e_context: EventContext):
        ctx = e_context["context"]
        if ctx.type != ContextType.PATPAT:
            return
        logger.info("reply_patpat")

        if self.patpat_message:
            return self._patpat_config_message(e_context)

        msg = ctx.get("msg")
        is_group = ctx.get("isgroup")

        intro = self.robot_desc
        if is_group:
            result = self.user_manager.get_doctor_of_group(msg.from_user_id)
            if result:
                logger.info(
                    f"patpat doctor found:{is_group} - {msg.from_user_nickname}"
                )

                extra_information = result.get("other")
                introduction = result.get("intro")
                department = result.get("department")
                name = result.get("professionalName")
                country = result.get("country")

                intro = {introduction, name, department, extra_information, country}
                logger.info(f"patpat doctor:{intro}")
        else:
            user_id = msg.from_user_id
            user_name = msg.from_user_nickname
            user = itchat.update_friend(user_id)
            if not user:
                return

            doctor = self.user_manager.get_my_doctor(
                user.RemarkName, self.robot_account, user_id, user_name
            )

            if doctor:
                intro = doctor.get("intro")

        if not intro:
            intro = self.robot_desc
            logger.info(
                f"patpat doctor not found,use robot desc;{is_group} - {msg.from_user_nickname}"
            )
        else:
            logger.info(f"patpat use doctor:{is_group} - {msg.from_user_nickname}")

        e_context["context"].type = ContextType.TEXT
        e_context["context"].content = f"请根据如下内容随机使用一种风格做总结介绍,限100字以内:\n{intro}"
        e_context.action = EventAction.BREAK  # 事件结束，进入默认处理逻辑
        return True

    def reply_hello(self, e_context: EventContext):
        try:
            ctx = e_context["context"]

            if ctx.type not in [ContextType.TEXT]:
                return

            msg = ctx.get("msg")
            content = ctx.content

            content = content.strip()
            content = content.lower()
            content_len = len(content)
            if content == "hello":
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
            elif content == "hi":
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "Hi"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK  # 事件结束，进入默认处理逻辑，一般会覆写reply
                return True
            elif content.startswith("王医生文章") and content_len < 7:
                reply = Reply()
                reply.type = ReplyType.TEXT
                reply.content = "https://mp.weixin.qq.com/s/uqof_p_PE4XWA-7J3JBHKQ"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS  # 事件结束，进入默认处理逻辑，一般会覆写reply
                return True
            elif content.startswith("好医生") and content_len < 5:
                reply = Reply()
                reply.type = ReplyType.IMAGE_URL
                reply.content = "https://iknowm-1257847067.cos.ap-nanjing.myqcloud.com/images/202401/IMG_202401_330311.jpg"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS  # 事件结束，进入默认处理逻辑，一般会覆写reply
                return True
            elif content.startswith("王医生") and content_len < 5:
                reply = Reply()
                reply.type = ReplyType.IMAGE_URL
                reply.content = "http://iknowm-1257847067.cos.ap-nanjing.myqcloud.com/images/202401/IMG_202401_288557.jpg"
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS  # 事件结束，进入默认处理逻辑，一般会覆写reply
                return True

        except Exception as e:
            logger.error("_reply_hello: {}".format(e))
        return False
