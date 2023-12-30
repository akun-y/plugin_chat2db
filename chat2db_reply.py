# encoding:utf-8
import logging
import os
import sqlite3
import time
import traceback
from datetime import datetime, timedelta
from lib import itchat
import plugins
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
from plugins import *
from plugins.plugin_chat2db.api_groupx import ApiGroupx
from plugins.plugin_comm.comm import EthZero, make_chat_sign_req
from plugins.plugin_chat2db.head_img_manager import HeadImgManager
from plugins.plugin_chat2db.user_refresh_thread import UserRefreshThread
from plugins.plugin_chat2db.UserManager import UserManager

# 应答一些自定义的回复信息,包括拍一拍，加群欢迎，Hello回复


class CustomReply:
    def __init__(self, config, groupx, user_manager):
        self.config = config
        self.groupx = groupx
        self.user_manager = user_manager

        self.robot_account =  self.config.get("account")
        self.robot_name =  self.config.get("name")
        self.robot_desc =  self.config.get("description")
        self.patpat_message =  self.config.get("patpat_message") #拍拍是否使用配置信息

    def reply_join_group(self, e_context: EventContext):

        ctx = e_context["context"]
        if ctx.type != ContextType.JOIN_GROUP: return
        logger.info("reply_join_group")

        msg: ChatMessage = e_context["context"]["msg"]

        welcome_msg = None
        group = self.user_manager.get_group_info(msg.from_user_id)
        if group :
            welcome_msg = group.get('joinWelcomeInfo', None)

        if welcome_msg:
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content = welcome_msg
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            logger.info(f"reply_join_group: {welcome_msg}")
            return True
        return False
    def _patpat_config_message(self,  e_context: EventContext):
            reply = Reply()
            reply.type = ReplyType.TEXT
            reply.content =self.patpat_message
            e_context["reply"] = reply
            e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
            logger.info(f"reply_patpat: {self.patpat_message}")
            return True
    def reply_patpat(self, e_context: EventContext):
        ctx = e_context["context"]
        if ctx.type != ContextType.PATPAT: return
        logger.info("reply_patpat")

        if self.patpat_message:
            return self._patpat_config_message(e_context)

        msg = ctx.get("msg")
        is_group = ctx.get("isgroup")

        intro = self.robot_desc
        if is_group:
            result = self.user_manager.get_doctor_of_group(msg.from_user_id)
            if result:
                extra_information = result.get("other")
                introduction = result.get("intro")
                department = result.get("department")
                name = result.get("professionalName")
                country = result.get("country")

                intro = {introduction, name, department, extra_information, country}
        else :
            user_id= msg.from_user_id
            user_name = msg.from_user_nickname
            user = itchat.update_friend(user_id)
            if not user: return

            doctor = self.user_manager.get_my_doctor(user.RemarkName, self.robot_account, user_id, user_name)

            if doctor: intro = doctor.get('intro')

        if not intro: 
            intro = self.robot_desc
            logger.info(f"patpat doctor not found,use robot desc;{is_group} - {msg.from_user_nickname}")
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
            if content == "hello":
                reply = Reply()
                reply.type = ReplyType.TEXT
                msg: ChatMessage = e_context["context"]["msg"]
                if e_context["context"]["isgroup"]:
                    reply.content = (
                        f"Hello, {msg.actual_user_nickname} from {msg.from_user_nickname}"
                    )
                else:
                    reply.content = f"Hello, {msg.from_user_nickname}"
                    # reply.content = """以下是从提供的网页中提取的数据，并以表格形式呈现：
                    
                    
                    #     | 国家 | 首都 | 人口 (km²) | 面积 (km²) |
                    #     | :--: | :--: | :--: | :--: |
                    #     | 中国 | 北京 | 144376万 (约) | 960万 (约) |
                    #     | 美国 | 华盛顿特区 | 3317万 (约) | 973万 (约) |
                    #     | 印度 | 新德里 | 13968万 (约) | 328万 (约) |
                    #     | 巴西 | 巴西利亚 | 21247万 (约) | 85.9万 (约) |
                    #     | 俄罗斯 | 莫斯科 | 1462万 (约) | 17.5万 (约) |
                    #     | 加拿大 | 渥太华 | 3899万 (约) | 998万 (约) |
                    #     | 澳大利亚 | 堪培拉 | 2569万 (约) | 76.8万 (约) |
                    #     | 日本 | 东京都中心区（首府）*  |  *  |  *  |

                    #     请注意，由于网页内容可能随时更改，因此某些数据可能存在变化。建议在获取最新数据时参考官方来源。此外，人口和面积数据仅供参考，具体数据可能存在误差。
                    #     """
                e_context["reply"] = reply
                e_context.action = EventAction.BREAK_PASS  # 事件结束，并跳过处理context的默认逻辑
                return True
            elif content.startswith("你好") or content.startswith("您好"):
                reply = Reply()
                reply.type = ReplyType.TEXT
                msg: ChatMessage = e_context["context"]["msg"]
                if e_context["context"]["isgroup"]:
                    reply.content = (
                        f"你好, {msg.actual_user_nickname} 来自群:{msg.from_user_nickname}"
                    )
                else:
                    reply.content = f"你好啊, {msg.from_user_nickname}"
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
        except Exception as e:
            logger.error("_reply_hello: {}".format(e))
        return False
